"""Per-user read positions, folders and stars with business/assignment checks."""
import hashlib
import json
import frappe
from relay_core import features
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
    if doc.folder:
        from relay_core.chat_folders import own_folder
        own_folder(doc.folder)
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
        if folder is not None:
            features.require('folders')
            doc.folder=folder or None
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
    assignment=frappe.db.get_value('Relay Conversation Assignment',{'relay_contact':contact},['team','assigned_to','assigned_by'],as_dict=True) or {}
    return dict(state, unread=unread, unread_more=False, assignment=assignment, can_assign=frappe.has_permission('Relay Conversation Assignment', 'write'))


@frappe.whitelist(methods=['GET'])
def directory(query='', before=None, after=None, starred=0, folder='', mode='all', team=None, medium=None, since=None, channel=None):
    """Filter before pagination and expose only accessible conversation previews.

    `since` returns only conversations active at or after that time, so a live client can update the changed rows.
    `channel` narrows a medium to one Relay Channel, such as one WhatsApp number."""
    require_access()
    if not isinstance(query,str) or len(query)>80 or any(ord(c)<32 for c in query) or not isinstance(folder,str) or len(folder)>140 or bool(before)+bool(after)+bool(since)>1:
        frappe.throw('Invalid conversation search')
    if str(starred) not in ('0','1') or mode not in ('all','mine','unread','unassigned'):
        frappe.throw('Invalid conversation filter')
    from pypika import Order
    from pypika.functions import Coalesce
    contact=frappe.qb.DocType('Relay Contact');saved=frappe.qb.DocType('Relay Conversation State')
    assignment=frappe.qb.DocType('Relay Conversation Assignment');message=frappe.qb.DocType('Relay Message')
    filters={}
    if medium not in (None, '', 'WhatsApp', 'Telegram', 'Email'):frappe.throw('Invalid medium')
    channel_names=frappe.get_list('Relay Channel',filters={'channel':medium},pluck='name',limit_page_length=0) if medium else None
    if channel:
        if channel not in (channel_names or []):frappe.throw('Invalid channel')
        channel_names=[channel]
    activity=Coalesce(contact.last_message_at,contact.creation)
    search=frappe.qb.get_query('Relay Contact',fields=['name','contact','display_name','last_message_at','creation'],filters=filters,
                               ignore_permissions=False,order_by='',limit=31)
    if medium:
        channels=frappe.qb.DocType('Relay Channel')
        endpoints=frappe.qb.DocType('Relay Contact Endpoint')
        available=[channel] if channel else frappe.qb.from_(channels).select(channels.name).where(channels.channel==medium)
        search=search.where(contact.name.isin(frappe.qb.from_(endpoints).select(endpoints.relay_contact).where(endpoints.channel.isin(available))))
    if before or after:
        cursor=before or after;validate_reference(cursor,'CON');anchor,_=readable_contact(cursor)
        stamp=anchor.last_message_at or anchor.creation
        condition=((activity>stamp)|((activity==stamp)&(contact.name>cursor))) if before else ((activity<stamp)|((activity==stamp)&(contact.name<cursor)))
        search=search.where(condition)
    if since:
        search=search.where(activity>=activity_time(since))
    search=search.orderby(activity,order=Order.asc if before else Order.desc).orderby(contact.name,order=Order.asc if before else Order.desc)
    if query.strip():
        pattern='%'+ '%'.join('\\'+c if c in '%_\\' else c for c in query.strip())+'%'
        search=search.where(contact.display_name.like(pattern)|contact.name.like(pattern))
    if folder: features.require('folders')
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
        search=search.where(contact.name.notin(assigned_contacts()))
    if team:
        if not isinstance(team,str) or len(team)>140:frappe.throw('Invalid team')
        from relay_core.teams import readable_filter_team
        readable_filter_team(team)
        search=search.where(contact.name.isin(frappe.qb.from_(assignment).select(assignment.relay_contact).where(assignment.team==team)))
    rows=search.run(as_dict=True);more=len(rows)>30;page=rows[:30]
    if before:page.reverse()
    items=directory_items(page,channel_names)
    return {'items':items,'previous':{'before':page[0].name} if page and (more if before else bool(after)) else None,
            'next':{'after':page[-1].name} if page and (bool(before) if before else more) else None}


def assigned_contacts():
    """Conversations with an agent, or with a team while teams are on. The Unassigned tab shows the rest."""
    from pypika.functions import Coalesce
    assignment=frappe.qb.DocType('Relay Conversation Assignment')
    taken=Coalesce(assignment.assigned_to,'')!=''
    if features.is_enabled('teams'):taken=taken|(Coalesce(assignment.team,'')!='')
    return frappe.qb.from_(assignment).select(assignment.relay_contact).where(taken)


def activity_time(value):
    try:
        if not isinstance(value,str) or len(value)>32: raise ValueError
        return frappe.utils.get_datetime(value)
    except (TypeError, ValueError):
        frappe.throw('Invalid conversation activity time')


PREVIEW_FIELDS = ['name','relay_contact','content','message_data','transcript','channel','creation','sent_at','business_doctype','business_name']


def directory_items(rows, channels=None):
    """Previews, reads, unread counts and assignments for one page in a fixed number of queries.

    Rows come from the Relay Contact permission query, and every lookup here runs under the
    Relay Message and Relay Channel permission queries."""
    names=[row.name for row in rows]
    if not names: return []
    from relay_core.api import business_types
    configured=set(business_types())
    providers=dict(frappe.get_list('Relay Channel',fields=['name','channel'],as_list=True,limit_page_length=0))
    latest=latest_messages(names,channels)
    states={row.relay_contact:row for row in frappe.get_all('Relay Conversation State',
        filters={'state_key':['in',[state_key(name) for name in names]]},fields=['relay_contact','starred','folder',*READ_FIELDS])}
    unread=unread_counts({name:read_position(states.get(name)) for name in names},channels)
    assignments={row.relay_contact:{'team':row.team,'assigned_to':row.assigned_to,'assigned_by':row.assigned_by} for row in frappe.get_all(
        'Relay Conversation Assignment',filters={'relay_contact':['in',names]},fields=['relay_contact','team','assigned_to','assigned_by'])}
    items=[]
    for row in rows:
        last=latest.get(row.name) or {}
        if last.get('channel') not in providers: last={}
        state=states.get(row.name) or {}
        business=({'doctype':last['business_doctype'],'name':last['business_name']}
                  if last.get('business_doctype') in configured and last.get('business_name') else None)
        items.append(dict(row,provider=providers.get(last.get('channel')),channel=last.get('channel'),business=business,assignment=assignments.get(row.name,{}),id=row.name,
                          starred=state.get('starred',0),folder=state.get('folder',''),
                          latest_preview=directory_preview(last),latest_at=last.get('sent_at') or last.get('creation'),
                          unread=unread.get(row.name,0),unread_more=False))
    return items


def latest_messages(contacts, channels=None):
    """The newest readable message of each conversation: one indexed LIMIT 1 lookup per contact in one statement."""
    if channels is not None and not channels: return {}
    from relay_core.timeline import page_query
    message=frappe.qb.DocType('Relay Message')
    base=page_query(PREVIEW_FIELDS,{'channel':['in',channels]} if channels is not None else {},1)
    parts=[base.where(message.relay_contact==contact) for contact in contacts]
    union=parts[0]
    for part in parts[1:]: union=union*part  # UNION ALL keeps each part's ORDER BY and LIMIT.
    return {row.relay_contact:row for row in union.run(as_dict=True)}


def directory_preview(message):
    """Use the thread's plain text, with legacy content decoded for text rendering."""
    from relay_core.message_display import business_choice_label
    label = business_choice_label(message)
    if label:
        return label
    from relay_core.messaging import object_value
    from relay_core.message_types import preview
    data = object_value(message.get('message_data') or {})
    if data.get('kind') and message.get('transcript'):
        return (preview(data) + ': ' + message['transcript'])[:200]
    if data.get('kind'):
        return preview(data)[:200]
    # Older messages have only sanitized HTML content. Decode after stripping tags;
    # API consumers must render this plain-text preview as text, never as HTML.
    from html import unescape
    from frappe.utils import strip_html
    return unescape(strip_html(message.get('content') or ''))[:200]


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
    target=whatsapp_channel=None
    if message:
        from relay_core.messaging import readable_source
        source,channel,context=readable_source(message)
        if source.relay_contact!=contact:frappe.throw('Typing source belongs to another contact',frappe.PermissionError)
        from relay_core.whatsapp_presence import direct_channel
        whatsapp_channel=direct_channel(channel,context)
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
            from relay_core.hub_channels import hub_arguments
            try:whatsapp.client().call_tool('telegram.typing',hub_arguments(channel,target))
            except Exception:pass  # Ephemeral feedback must never block composing or retry.
    if whatsapp_channel and str(active) in ('1','True'):
        from relay_core import whatsapp_presence
        try:whatsapp_presence.typing(contact,whatsapp_channel)
        except Exception:frappe.log_error('WhatsApp typing indicator was not queued')
    return {'ok': True}


READ_FIELDS = ['exact_reads','last_read','read_baseline']


def read_position(state):
    """Messages after this name are unread: the exact-read baseline, else the legacy cursor."""
    state = state or {}
    return (state.get('read_baseline') if state.get('exact_reads') == 1 else state.get('last_read')) or ''


def _unread_query(fields, contact=None, position=None):
    """Unread incoming messages of the current user. For one contact the read position is a literal,
    so the relay_unread_messages index seeks straight to the unread rows."""
    query=unread_base(fields)
    if contact:
        if position is None:
            position=read_position(frappe.db.get_value('Relay Conversation State',{'state_key':state_key(contact)},READ_FIELDS,as_dict=True))
        return contact_unread(query,contact,position)
    from pypika.functions import Coalesce
    message=frappe.qb.DocType('Relay Message');saved=frappe.qb.DocType('Relay Conversation State')
    query=query.left_join(saved).on((saved.relay_contact==message.relay_contact)&(saved.user==frappe.session.user))
    legacy=(Coalesce(saved.exact_reads,0)==0)&(message.name>Coalesce(saved.last_read,''))
    exact=(saved.exact_reads==1)&(message.name>Coalesce(saved.read_baseline,''))
    return query.where(legacy|exact)


def unread_base(fields):
    """Readable incoming live messages the user has not read individually."""
    message=frappe.qb.DocType('Relay Message');evidence=frappe.qb.DocType('Relay Message Read')
    query=frappe.qb.get_query('Relay Message',fields=fields,filters={'direction':'Incoming','legacy_source':['is','not set']},
                              ignore_permissions=False,order_by='')
    # Anti-join on the unique (user, message) read: one index probe per message.
    query=query.left_join(evidence).on((evidence.message==message.name)&(evidence.user==frappe.session.user))
    return query.where(evidence.name.isnull())


def contact_unread(base, contact, position):
    message=frappe.qb.DocType('Relay Message')
    return base.where(message.relay_contact==contact).where(message.name>position)


def unread_counts(positions, channels=None):
    """Unread message count per contact for a page: one seek per contact from its read position, in one statement."""
    if not positions or channels is not None and not channels: return {}
    from pypika.functions import Count
    message=frappe.qb.DocType('Relay Message')
    base=unread_base(['relay_contact'])
    if channels is not None: base=base.where(message.channel.isin(channels))
    union=None
    for contact,position in positions.items():
        unseen=contact_unread(base,contact,position).as_('unseen')
        part=frappe.qb.from_(unseen).select(unseen.relay_contact,Count('*')).groupby(unseen.relay_contact)
        union=part if union is None else union*part
    return {contact:int(total) for contact,total in union.run()}


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
    state = {'channel': channel, 'first_unread': first_unread(contact, channel)}
    position = views.get(channel or 'combined') or {}
    if position.get('name'):
        doc = frappe.get_doc('Relay Message', position['name']); doc.check_permission('read')
        frappe.get_doc('Relay Channel', doc.channel).check_permission('read')
        if doc.relay_contact == contact and (not channel or doc.channel == channel):
            state.update(position)
    return state


def first_unread(contact, channel=None):
    """Oldest unread message in thread order, where the conversation opens."""
    from relay_core.timeline import timeline_time
    message = frappe.qb.DocType('Relay Message')
    query = _unread_query(['name'], contact)
    if channel:
        query = query.where(message.channel == channel)
    rows = query.orderby(timeline_time()).orderby(message.name).limit(1).run()
    return rows[0][0] if rows else None


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
