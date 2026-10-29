"""Exact operator read evidence; provider delivery receipts remain separate."""
import hashlib
import json
import frappe
from relay_core.permissions import require_access, readable_contact, can_read_contact_as

MAX_BUSINESS_CHATS = 100


def can_read_message_as(doc,user):
    return bool(frappe.db.get_value('User',user,'enabled') and doc.has_permission('read',user=user))


def expected_readers(doc):
    if doc.get('business_doctype') and doc.get('business_name'):
        if frappe.db.exists('Relay Contact Type', {'business_doctype':doc.business_doctype,'enabled':1}):
            from relay_core.business_groups import configuration
            field=next(iter(configuration(doc.business_doctype)), '')
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
    from relay_core.business_access import primary
    from relay_core.relay_chats import key_of
    owners, chats = {contact: primary(contact)}, {}
    for name in names:
        doc = frappe.get_doc('Relay Message', name); doc.check_permission('read')
        if doc.relay_contact != contact: frappe.throw('Message belongs to another conversation', frappe.PermissionError)
        frappe.get_doc('Relay Channel', doc.channel).check_permission('read')
        key = key_of(doc, owners)
        if key: chats[key] = max(chats.get(key, ''), name)
    from relay_core.conversation_state import fresh_write
    fresh_write(lambda: record_contact_reads(contact, names, chats))
    from relay_core import whatsapp_presence
    try: whatsapp_presence.mark_read(contact, names)
    except Exception: frappe.log_error('WhatsApp read receipt was not queued')  # Operator reads stay recorded.
    return {'marked':names}


def record_contact_reads(contact, names, chats):
    """Store the reads and lower the shared unread count of each chat; `chats` maps a chat key to its newest read message."""
    from relay_core.conversation_state import start_exact_reads
    from relay_core.relay_chats import mark_read
    start_exact_reads(contact)
    if insert_reads([(contact, name) for name in names]):
        from relay_core.realtime import contact_changed
        contact_changed(contact, 'reads')
    for key, newest in chats.items():
        mark_read(key, newest)
    frappe.db.commit()


def insert_reads(rows) -> bool:
    """Store the session user's reads of (contact, message) rows once. Return True when a read is new.

    Rows get hash names, as the shared naming series row serializes every reader."""
    user, now = frappe.session.user, frappe.utils.now_datetime()
    keys = {hashlib.sha256((user+':'+message).encode()).hexdigest(): (contact, message) for contact, message in rows}
    known = set(frappe.get_all('Relay Message Read', filters={'read_key':['in',list(keys)]}, pluck='read_key'))
    new = [(frappe.generate_hash(length=10), now, now, user, user, user, contact, message, key)
           for key, (contact, message) in keys.items() if key not in known]
    if new:
        frappe.db.bulk_insert('Relay Message Read', ['name','creation','modified','owner','modified_by','user','relay_contact','message','read_key'],
                              new, ignore_duplicates=True)
    return bool(new)


@frappe.whitelist(methods=['POST'])
def mark_chat(contact=None, read=1, business_doctype=None, business_name=None):
    """Mark the session user's chat read, or its newest incoming message unread, from the chat list.
    A business row names its record instead, and every chat of that row changes.

    It changes only this user's read state and sends no read receipt to the customer."""
    require_access()
    if bool(contact) == bool(business_doctype or business_name):
        frappe.throw('Choose one chat or one business record')
    if contact:
        readable_contact(contact)
    chats = [contact] if contact else business_chats(business_doctype, business_name)
    if str(read) not in ('0', '1'):
        frappe.throw('Invalid read flag')
    from relay_core import relay_chats
    from relay_core.conversation_state import fresh_write
    key = relay_chats.key_of({'relay_contact': contact}) if contact else (business_doctype, business_name)

    def write():
        for name in chats:
            set_chat_read(name, str(read) == '1')
        relay_chats.mark_read(key) if str(read) == '1' else relay_chats.mark_unread(key)
        frappe.db.commit()
    fresh_write(write)
    unread = frappe.db.get_value(relay_chats.CHAT, {'business_doctype': key[0], 'business_name': key[1]}, 'unread_count') or 0
    if contact:
        return {'contact': contact, 'unread': unread}
    return {'business': {'doctype': business_doctype, 'name': business_name}, 'contacts': chats, 'unread': unread}


def business_chats(doctype, name):
    """The chats of a business row: the user's readable Relay conversations of Contacts linked to the record."""
    from relay_core.business_inbox import check_type
    check_type(doctype)
    if not isinstance(name, str) or not name or len(name) > 140:
        frappe.throw('Choose a business record')
    frappe.get_doc(doctype, name).check_permission('read')
    people = frappe.get_all('Dynamic Link', filters={'link_doctype': doctype, 'link_name': name, 'parenttype': 'Contact',
                            'parentfield': 'links'}, pluck='parent', limit_page_length=MAX_BUSINESS_CHATS)
    if not people:
        return []
    return frappe.get_list('Relay Contact', filters={'contact': ['in', people]}, pluck='name', order_by='name asc',
                           limit_page_length=MAX_BUSINESS_CHATS)


def set_chat_read(contact, read):
    """Read moves both read positions to the newest message, so no per-message rows are written.
    Unread drops the user's read of the newest incoming message and, when the baseline covers it, moves the baseline
    to the message before it."""
    from relay_core.conversation_state import STATE, ensure_state, start_exact_reads
    filters = {'relay_contact': contact} if read else {'relay_contact': contact, 'direction': 'Incoming', 'legacy_source': ['is', 'not set']}
    newest = newest_message(filters)
    if not newest:
        return
    name = ensure_state(contact)
    start_exact_reads(contact)
    current = frappe.db.get_value(STATE, name, ['last_read', 'read_baseline'], as_dict=True, for_update=True)
    if read:
        values = {field: newest for field in ('last_read', 'read_baseline') if (current.get(field) or '') < newest}
    else:
        frappe.db.delete('Relay Message Read', {'user': frappe.session.user, 'message': newest})
        values = {'read_baseline': newest_message({'relay_contact': contact, 'name': ['<', newest]}) or ''} if (current.read_baseline or '') >= newest else {}
    if values:
        frappe.db.set_value(STATE, name, values, update_modified=False)
    from relay_core.realtime import contact_changed
    contact_changed(contact, 'reads')
    frappe.db.commit()


def newest_message(filters):
    """The newest message the session user can read under these filters; message names grow with time."""
    rows = frappe.get_list('Relay Message', filters=filters, order_by='name desc', limit_page_length=1, pluck='name')
    return rows[0] if rows else None


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
            'complete':bool(expected) and len(required_seen)==len(expected),'receipt_times':receipt_times(doc)}


def receipt_times(doc):
    """The provider's Sent, Delivered and Read times of a message, in the site's time zone."""
    from datetime import datetime, timezone
    from frappe.utils import convert_utc_to_system_timezone
    history = doc.get('message_updates') or {}
    if isinstance(history, str):
        history = json.loads(history)
    times = (history.get('delivery') or {}).get('times') or {}
    return {status: convert_utc_to_system_timezone(datetime.fromtimestamp(stamp, timezone.utc)).strftime('%Y-%m-%d %H:%M:%S')
            for status, stamp in times.items()}


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
