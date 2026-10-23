"""Per-user read positions, folders and stars with business/assignment checks."""
import hashlib
import json
import frappe
from relay_core.permissions import require_access, readable_contact
from relay_core.api import validate_reference


def state_key(contact, user=None):
    return hashlib.sha256(((user or frappe.session.user)+':'+contact).encode()).hexdigest()


def validate_state(doc):
    require_access()
    if doc.user != frappe.session.user or doc.owner != frappe.session.user:
        frappe.throw('Conversation state belongs to its user', frappe.PermissionError)
    readable_contact(doc.relay_contact)
    previous = doc.get_doc_before_save()
    if doc.get('chat_views') != (previous.get('chat_views') if previous else None):
        frappe.throw('Chat positions are maintained by the inbox service', frappe.PermissionError)
    if (bool(doc.get('exact_reads')) != bool(previous.get('exact_reads') if previous else False) or (doc.get('read_baseline') or '') != (previous.get('read_baseline') or '' if previous else '')) and not getattr(frappe.flags,'relay_read_write',False):
        frappe.throw('Read evidence is maintained by the inbox service', frappe.PermissionError)
    if doc.state_key != state_key(doc.relay_contact): frappe.throw('Invalid conversation state key')
    if doc.folder and (not isinstance(doc.folder,str) or len(doc.folder)>50 or any(ord(c)<32 for c in doc.folder)):
        frappe.throw('Folder names must contain at most 50 printable characters')
    if doc.last_read:
        validate_reference(doc.last_read,'MSG')
        message=frappe.get_doc('Relay Message',doc.last_read);message.check_permission('read')
        if message.relay_contact!=doc.relay_contact: frappe.throw('Read position belongs to another contact')
        previous=doc.get_doc_before_save()
        if previous and previous.last_read and previous.last_read>doc.last_read: doc.last_read=previous.last_read


@frappe.whitelist(methods=['POST'])
def update(contact, last_read=None, starred=None, folder=None):
    require_access(); readable_contact(contact)
    key=state_key(contact)
    # Serialize per-user updates across tabs and workers without locking other users.
    with frappe.cache.lock('relay-inbox-'+key, timeout=10, blocking_timeout=3):
        name=frappe.db.get_value('Relay Conversation State', {'state_key':key},'name')
        doc=frappe.get_doc('Relay Conversation State',name) if name else frappe.new_doc('Relay Conversation State')
        doc.user=frappe.session.user;doc.relay_contact=contact;doc.state_key=key
        if last_read is not None:
            validate_reference(last_read,'MSG')
            marker=frappe.get_doc('Relay Message',last_read);marker.check_permission('read')
            if marker.relay_contact!=contact:frappe.throw('Read position belongs to another contact')
            if not marker.get('legacy_source'):doc.last_read=last_read
        if starred is not None:
            if str(starred) not in ('0','1','True','False'): frappe.throw('Invalid starred flag')
            doc.starred=int(str(starred) in ('1','True'))
        if folder is not None: doc.folder=folder.strip() if isinstance(folder,str) else folder
        old_cursor=frappe.db.get_value('Relay Conversation State',name,'last_read') if name else None
        doc.last_seen=frappe.utils.now_datetime();doc.save()
        if doc.last_read != old_cursor:
            from relay_core.realtime import contact_changed
            contact_changed(contact,'reads')
        frappe.db.commit()
    return read(contact)


@frappe.whitelist(methods=['GET'])
def read(contact):
    require_access();readable_contact(contact)
    state=frappe.db.get_value('Relay Conversation State',{'state_key':state_key(contact)},['last_read','starred','folder','last_seen'],as_dict=True) or {}
    unread=unread_count(contact)
    assignment=frappe.db.get_value('Relay Conversation Assignment',{'relay_contact':contact},['team','assigned_to'],as_dict=True) or {}
    roles=set(frappe.get_roles())
    return dict(state, unread=unread, unread_more=False, assignment=assignment, can_assign=bool(roles.intersection({'System Manager','Relay Communication Manager'})))


@frappe.whitelist(methods=['GET'])
def directory(query='', before=None, after=None, starred=0, folder='', mode='all', team=None, medium=None):
    """Filter before pagination and expose only accessible conversation previews."""
    require_access()
    if not isinstance(query,str) or len(query)>80 or any(ord(c)<32 for c in query) or not isinstance(folder,str) or len(folder)>50 or before and after:
        frappe.throw('Invalid conversation search')
    if str(starred) not in ('0','1') or mode not in ('all','mine','unread','unassigned'):
        frappe.throw('Invalid conversation filter')
    from pypika import Order
    from pypika.functions import Coalesce
    contact=frappe.qb.DocType('Relay Contact');saved=frappe.qb.DocType('Relay Conversation State')
    assignment=frappe.qb.DocType('Relay Conversation Assignment');message=frappe.qb.DocType('Relay Message')
    filters={}
    if medium not in (None, 'WhatsApp'):frappe.throw('Invalid medium')
    activity=Coalesce(contact.last_message_at,contact.creation)
    search=frappe.qb.get_query('Relay Contact',fields=['name','contact','display_name','last_message_at','creation'],filters=filters,
                               ignore_permissions=False,order_by='',limit=31)
    if medium:
        channels=frappe.qb.DocType('Relay Channel')
        endpoints=frappe.qb.DocType('Relay Contact Endpoint')
        available=frappe.qb.from_(channels).select(channels.name).where(channels.channel==medium)
        search=search.where(contact.name.isin(frappe.qb.from_(endpoints).select(endpoints.relay_contact).where(endpoints.channel.isin(available))))
    if before or after:
        cursor=before or after;validate_reference(cursor,'CON');anchor,_=readable_contact(cursor)
        stamp=anchor.last_message_at or anchor.creation
        condition=((activity>stamp)|((activity==stamp)&(contact.name>cursor))) if before else ((activity<stamp)|((activity==stamp)&(contact.name<cursor)))
        search=search.where(condition)
    search=search.orderby(activity,order=Order.asc if before else Order.desc).orderby(contact.name,order=Order.asc if before else Order.desc)
    if query.strip():
        pattern='%'+ '%'.join('\\'+c if c in '%_\\' else c for c in query.strip())+'%'
        search=search.where(contact.display_name.like(pattern)|contact.name.like(pattern))
    if folder or str(starred)=='1':
        states=frappe.qb.from_(saved).select(saved.relay_contact).where(saved.user==frappe.session.user)
        if folder:states=states.where(saved.folder==folder)
        if str(starred)=='1':states=states.where(saved.starred==1)
        search=search.where(contact.name.isin(states))
    if mode=='unread':
        unseen=_unread_query(['relay_contact'])
        if medium:unseen=unseen.where(message.channel.isin(available))
        search=search.where(contact.name.isin(unseen))
    if mode=='mine':
        mine=frappe.qb.from_(assignment).select(assignment.relay_contact).where(assignment.assigned_to==frappe.session.user)
        search=search.where(contact.name.isin(mine))
    if mode=='unassigned':
        assigned=frappe.qb.from_(assignment).select(assignment.relay_contact).where((Coalesce(assignment.assigned_to,'')!='')|(Coalesce(assignment.team,'')!=''))
        search=search.where(contact.name.notin(assigned))
    if team:
        if not isinstance(team,str) or len(team)>140:frappe.throw('Invalid team')
        from relay_core.teams import readable_filter_team
        readable_filter_team(team)
        search=search.where(contact.name.isin(frappe.qb.from_(assignment).select(assignment.relay_contact).where(assignment.team==team)))
    channel_names=frappe.get_list('Relay Channel',filters={'channel':medium},pluck='name',limit_page_length=100) if medium else None
    rows=search.run(as_dict=True);more=len(rows)>30;page=rows[:30]
    if before:page.reverse()
    items=[]
    from relay_core.timeline import page_query
    for row in page:
        try:readable_contact(row.name)
        except frappe.PermissionError:continue
        latest_filters={'relay_contact':row.name}
        if medium:latest_filters['channel']=['in',channel_names]
        latest=page_query(['name','content','channel','creation','sent_at'],latest_filters,1).run(as_dict=True)
        state=frappe.db.get_value('Relay Conversation State',{'state_key':state_key(row.name)},['last_read','starred','folder'],as_dict=True) or {}
        unread=unread_count(row.name, channels=channel_names)
        last=latest[0] if latest else {}
        if last and not frappe.get_doc('Relay Channel',last.channel).has_permission('read'):last={}
        items.append(dict(row,id=row.name,starred=state.get('starred',0),folder=state.get('folder',''),
                          latest_preview=(last.get('content') or '')[:200],latest_at=last.get('sent_at') or last.get('creation'),
                          unread=unread,unread_more=False))
    return {'items':items,'previous':{'before':page[0].name} if page and (more if before else bool(after)) else None,
            'next':{'after':page[-1].name} if page and (bool(before) if before else more) else None}


@frappe.whitelist(methods=['GET'])
def presence(contact):
    require_access();readable_contact(contact)
    from relay_core.permissions import can_read_contact_as
    cutoff=frappe.utils.add_to_date(frappe.utils.now_datetime(),seconds=-90)
    rows=frappe.get_all('Relay Conversation State',filters={'relay_contact':contact,'last_seen':['>',cutoff]},fields=['user'],order_by='last_seen desc',limit_page_length=11)
    users=[]
    for row in rows:
        if row.user!=frappe.session.user and can_read_contact_as(contact,row.user):
            users.append({'name':row.user,'full_name':frappe.db.get_value('User',row.user,'full_name'),'typing':bool(frappe.cache.get_value('relay-typing-'+state_key(contact,row.user)))})
    return {'users':users[:10]}


def message_created(doc, method=None):
    """Maintain the directory activity marker under the same insertion transaction."""
    contact=frappe.db.get_value('Relay Contact',doc.relay_contact,['last_message_at','last_message'],as_dict=True,for_update=True)
    if not contact:return
    stamp=frappe.utils.get_datetime(doc.get('sent_at') or doc.creation)
    old=frappe.utils.get_datetime(contact.last_message_at) if contact.last_message_at else None
    if old is None or stamp>old or stamp==old and doc.name>(contact.last_message or ''):
        frappe.db.set_value('Relay Contact',doc.relay_contact,{'last_message_at':stamp,'last_message':doc.name},update_modified=False)


def rebuild_activity(contact):
    """Bounded per-contact repair for upgrades; reads the latest historical message."""
    require_access(configure=True)
    from relay_core.timeline import page_query
    rows=page_query(['name','relay_contact','sent_at','creation'],{'relay_contact':contact},1).run(as_dict=True)
    if rows:message_created(rows[0])


@frappe.whitelist(methods=['POST'])
def typing(contact, active=1, message=None):
    require_access(); readable_contact(contact)
    if str(active) not in ('0','1','True','False'):
        frappe.throw('Invalid typing state')
    target=None
    if message:
        from relay_core.messaging import readable_source
        source,channel,context=readable_source(message)
        if source.relay_contact!=contact:frappe.throw('Typing source belongs to another contact',frappe.PermissionError)
        if channel.channel=='Telegram' and context.get('provider')=='Telegram' and str(context.get('chat_id'))==source.sender_endpoint:
            from relay_core.automation.provenance import integer
            target={'chat_id':integer(context.get('chat_id')),'message_thread_id':integer(context['message_thread_id'],positive=True) if context.get('message_thread_id') else 0}
            target_key='relay-provider-typing:'+channel.name+':'+str(target['chat_id'])+':'+str(target['message_thread_id'])
    key = 'relay-typing-' + state_key(contact)
    if str(active) in ('1','True'):
        frappe.cache.set_value(key, True, expires_in_sec=8)
    else:
        frappe.cache.delete_value(key)
    from relay_core.realtime import contact_changed
    contact_changed(contact, 'presence')
    if target and str(active) in ('1','True'):
        # A shared NX lease coalesces agents and browser tabs for this destination.
        if frappe.cache.set(frappe.cache.make_key(target_key),'1',nx=True,ex=4):
            from relay_core import whatsapp
            try:whatsapp.client().call_tool('telegram.typing',target)
            except Exception:pass  # Ephemeral feedback must never block composing or retry.
    return {'ok': True}


def _unread_query(fields, contact=None):
    from pypika.functions import Coalesce
    message=frappe.qb.DocType('Relay Message');saved=frappe.qb.DocType('Relay Conversation State');evidence=frappe.qb.DocType('Relay Message Read')
    filters={'direction':'Incoming','legacy_source':['is','not set']}
    if contact:filters['relay_contact']=contact
    query=frappe.qb.get_query('Relay Message',fields=fields,filters=filters,ignore_permissions=False,order_by='')
    query=query.left_join(saved).on((saved.relay_contact==message.relay_contact)&(saved.user==frappe.session.user))
    legacy=(Coalesce(saved.exact_reads,0)==0)&(message.name>Coalesce(saved.last_read,''))
    exact=(saved.exact_reads==1)&(message.name>Coalesce(saved.read_baseline,''))
    recorded=frappe.qb.from_(evidence).select(evidence.message).where(evidence.user==frappe.session.user)
    return query.where((legacy|exact)&message.name.notin(recorded))


def unread_count(contact, channel=None, channels=None):
    from pypika.functions import Count
    query = _unread_query(['name'], contact)
    if channel:
        query = query.where(frappe.qb.DocType('Relay Message').channel == channel)
    if channels is not None:
        query = query.where(frappe.qb.DocType('Relay Message').channel.isin(channels))
    return int(frappe.qb.from_(query.as_('unseen')).select(Count('*')).run()[0][0])


@frappe.whitelist(methods=['GET'])
def view_state(contact, channel=None):
    require_access(); readable_contact(contact)
    raw = frappe.db.get_value('Relay Conversation State', {'state_key':state_key(contact)}, 'chat_views')
    views = json.loads(raw) if isinstance(raw, str) else (raw or {})
    if channel is None: channel=views.get('_active','')
    if channel:
        validate_reference(channel, 'CH')
        frappe.get_doc('Relay Channel', channel).check_permission('read')
    position = views.get(channel or 'combined') or {}
    if position.get('name'):
        doc = frappe.get_doc('Relay Message', position['name']); doc.check_permission('read')
        frappe.get_doc('Relay Channel', doc.channel).check_permission('read')
        if doc.relay_contact != contact or channel and doc.channel != channel:
            return {}
        return dict(position,channel=channel)
    return {}


@frappe.whitelist(methods=['POST'])
def save_view(contact, message, channel='', offset=0, at_bottom=0):
    require_access(); readable_contact(contact); validate_reference(message, 'MSG')
    doc = frappe.get_doc('Relay Message', message); doc.check_permission('read')
    frappe.get_doc('Relay Channel', doc.channel).check_permission('read')
    if doc.relay_contact != contact or channel and doc.channel != channel:
        frappe.throw('Chat position belongs to another conversation', frappe.PermissionError)
    try: offset = float(offset)
    except (ValueError, TypeError): frappe.throw('Invalid viewport offset')
    if not -2000 <= offset <= 2000 or str(at_bottom) not in ('0','1'):
        frappe.throw('Invalid viewport position')
    key = state_key(contact)
    with frappe.cache.lock('relay-inbox-'+key, timeout=10, blocking_timeout=3):
        name = frappe.db.get_value('Relay Conversation State', {'state_key':key}, 'name')
        if not name:
            state=frappe.get_doc({'doctype':'Relay Conversation State','state_key':key,'user':frappe.session.user,'relay_contact':contact}).insert()
            name=state.name
        raw = frappe.db.get_value('Relay Conversation State', name, 'chat_views', for_update=True)
        views = json.loads(raw) if isinstance(raw,str) else (raw or {})
        view_key=channel or 'combined'
        if view_key not in views and len(views)>=100: views.pop(next(iter(views)))
        views['_active']=channel
        views[view_key]={'name':message,'offset':offset,'atBottom':str(at_bottom)=='1'}
        frappe.db.set_value('Relay Conversation State', name, 'chat_views', json.dumps(views), update_modified=False)
        frappe.db.commit()
    return {'saved':True}
