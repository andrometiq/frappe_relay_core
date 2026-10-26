"""Exact operator read evidence; provider delivery receipts remain separate."""
import hashlib
import frappe
from relay_core.permissions import require_access, readable_contact, can_read_contact_as


def can_read_message_as(doc,user):
    return bool(frappe.db.get_value('User',user,'enabled') and doc.has_permission('read',user=user))


def expected_readers(doc):
    if doc.get('business_doctype') and doc.get('business_name'):
        config=frappe.db.get_value('Relay Contact Type',{'business_doctype':doc.business_doctype,'enabled':1},
            ['grouping_field'],as_dict=True)
        if config is not None:
            field=config.grouping_field or ''
            value=frappe.db.get_value(doc.business_doctype,doc.business_name,field) if field else ''
            from relay_core.business_groups import key
            owner=frappe.db.get_value('Relay Business Group Claim',key(doc.business_doctype,field,value or ''),'assigned_to')
            if owner:return [owner]
    assignment=frappe.db.get_value('Relay Conversation Assignment',{'relay_contact':doc.relay_contact},
        ['team','assigned_to'],as_dict=True) or {}
    if assignment.get('assigned_to'):return [assignment['assigned_to']]
    if assignment.get('team'):
        return frappe.get_all('Relay Team Member',filters={'parent':assignment['team'],'parenttype':'Relay Team'},
            pluck='user',limit_page_length=100)
    return []


@frappe.whitelist(methods=['POST'])
def mark(contact, messages):
    require_access(); readable_contact(contact)
    if isinstance(messages, str): messages = frappe.parse_json(messages)
    if not isinstance(messages, list) or not messages or len(messages) > 50 or any(not isinstance(name, str) for name in messages):
        frappe.throw('Choose between 1 and 50 visible messages')
    names = list(dict.fromkeys(messages))
    for name in names:
        doc = frappe.get_doc('Relay Message', name); doc.check_permission('read')
        if doc.relay_contact != contact: frappe.throw('Message belongs to another conversation', frappe.PermissionError)
        frappe.get_doc('Relay Channel', doc.channel).check_permission('read')
    user = frappe.session.user
    from relay_core.inbox import state_key
    with frappe.cache.lock('relay-inbox-' + state_key(contact), timeout=15, blocking_timeout=3):
        previous = getattr(frappe.flags, 'relay_read_write', False)
        frappe.flags.relay_read_write = True
        try:
            state_name=frappe.db.get_value('Relay Conversation State',{'state_key':state_key(contact)},'name')
            state=frappe.get_doc('Relay Conversation State',state_name) if state_name else frappe.new_doc('Relay Conversation State')
            if not state.get('exact_reads'):
                state.user=user;state.relay_contact=contact;state.state_key=state_key(contact)
                state.read_baseline=state.last_read or '';state.exact_reads=1
                state.save()
            changed = False
            for name in names:
                key = hashlib.sha256((user+':'+name).encode()).hexdigest()
                if not frappe.db.exists('Relay Message Read', {'read_key':key}):
                    frappe.get_doc({'doctype':'Relay Message Read','user':user,'relay_contact':contact,'message':name,'read_key':key}).insert(ignore_permissions=True)
                    changed = True
            if changed:
                from relay_core.realtime import contact_changed
                contact_changed(contact, 'reads')
            frappe.db.commit()
        finally: frappe.flags.relay_read_write = previous
    from relay_core import whatsapp_presence
    try: whatsapp_presence.mark_read(contact, names)
    except Exception: frappe.log_error('WhatsApp read receipt was not queued')  # Operator reads stay recorded.
    return {'marked':names}


@frappe.whitelist(methods=['GET'])
def coverage(message):
    require_access()
    doc = frappe.get_doc('Relay Message', message); doc.check_permission('read'); readable_contact(doc.relay_contact)
    frappe.get_doc('Relay Channel', doc.channel).check_permission('read')
    expected=sorted({user for user in expected_readers(doc) if can_read_message_as(doc,user)})
    # Unassigned conversations do not invent a required team; show bounded actual readers.
    readers = frappe.get_all('Relay Message Read', filters={'message':message},fields=['user','creation'],order_by='creation desc',limit_page_length=101)
    visible = [row for row in readers[:100] if can_read_message_as(doc,row.user)]
    # Required readers are looked up separately so older evidence is not lost at the display bound.
    required_seen = set(frappe.get_all('Relay Message Read', filters={'message':message,'user':['in',expected]},pluck='user',limit_page_length=100)) if expected else set()
    users=list(set(expected+[row.user for row in visible]))
    profiles={row.name:row for row in frappe.get_all('User',filters={'name':['in',users]},fields=['name','full_name','user_image'],limit_page_length=200)} if users else {}
    profile = lambda user: {'user':user,'full_name':profiles.get(user,{}).get('full_name') or user,'user_image':profiles.get(user,{}).get('user_image')}
    return {'read_by':[dict(profile(row.user),read_at=row.creation) for row in visible], 'more':len(readers)>100,
            'expected':len(expected),'read':len(required_seen),'unread_by':[profile(user) for user in expected if user not in required_seen],
            'complete':bool(expected) and len(required_seen)==len(expected)}


@frappe.whitelist(methods=['GET'])
def cursors(messages):
    """One current marker per operator, restricted to the visible message window."""
    require_access()
    if isinstance(messages,str):messages=frappe.parse_json(messages)
    if not isinstance(messages,list) or len(messages)>150 or any(not isinstance(name,str) for name in messages):
        frappe.throw('Choose up to 150 messages')
    if not messages:return {'readers':[],'more':False}
    rows=frappe.get_list('Relay Message',filters={'name':['in',list(set(messages))]},
        fields=['name','relay_contact','channel','business_doctype','business_name'],limit_page_length=150)
    allowed=[];contacts=set();channels=set()
    for row in rows:
        if row.relay_contact not in contacts:readable_contact(row.relay_contact);contacts.add(row.relay_contact)
        if row.channel not in channels:frappe.get_doc('Relay Channel',row.channel).check_permission('read');channels.add(row.channel)
        allowed.append(row.name)
    if not allowed:return {'readers':[],'more':False}
    state=frappe.qb.DocType('Relay Conversation State');business_state=frappe.qb.DocType('Relay Business Conversation State');read=frappe.qb.DocType('Relay Message Read')
    markers=(frappe.qb.from_(state).left_join(read).on((read.user==state.user)&(read.message==state.last_read))
        .select(state.user,state.relay_contact,state.last_read,read.creation.as_('read_at'))
        .where(state.last_read.isin(allowed)&state.relay_contact.isin(list(contacts)))
        .orderby(state.user).limit(101).run(as_dict=True))
    business_markers=(frappe.qb.from_(business_state).left_join(read).on((read.user==business_state.user)&(read.message==business_state.last_read))
        .select(business_state.user,business_state.business_doctype,business_state.business_name,
            business_state.last_read,read.creation.as_('read_at'))
        .where(business_state.last_read.isin(allowed)).orderby(business_state.user).limit(101).run(as_dict=True))
    marked={row.last_read for row in markers[:100]+business_markers[:100]}
    documents={name:frappe.get_doc('Relay Message',name) for name in marked}
    visible=[row for row in markers[:100] if can_read_message_as(documents[row.last_read],row.user)]
    for row in business_markers[:100]:
        doc=documents.get(row.last_read)
        if (doc and doc.get('business_doctype')==row.business_doctype and doc.get('business_name')==row.business_name
                and can_read_message_as(doc,row.user)):
            visible.append(row)
    visible=list({(row.user,row.last_read):row for row in visible}.values())[:100]
    profiles={row.name:row for row in frappe.get_all('User',filters={'name':['in',[v.user for v in visible]]},fields=['name','full_name','user_image'],limit_page_length=100)} if visible else {}
    return {'readers':[{'user':row.user,'full_name':profiles.get(row.user,{}).get('full_name') or row.user,
        'user_image':profiles.get(row.user,{}).get('user_image'),'last_read_message':row.last_read,'last_read_at':row.read_at} for row in visible],
        'more':len(markers)>100 or len(business_markers)>100}
