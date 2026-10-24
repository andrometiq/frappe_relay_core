"""Permission-filtered WhatsApp timeline for one business record."""
import hashlib
import json
import frappe
from relay_core.permissions import require_access, readable_contact
from relay_core.api import validate_reference


def check_type(doctype):
    require_access()
    if not isinstance(doctype, str) or not frappe.db.exists('Relay Contact Type', {'business_doctype':doctype, 'enabled':1}):
        frappe.throw('Choose a configured business type', frappe.PermissionError)
    if not frappe.has_permission(doctype, 'read'):
        frappe.throw('Business type is not readable', frappe.PermissionError)


def state_key(doctype, name, user=None):
    identity=json.dumps([user or frappe.session.user,doctype,name],separators=(',',':'))
    return hashlib.sha256(identity.encode()).hexdigest()


def validate_state(doc):
    require_access()
    if doc.user!=frappe.session.user or doc.owner!=frappe.session.user:
        frappe.throw('Business conversation state belongs to its user',frappe.PermissionError)
    check_type(doc.business_doctype)
    frappe.get_doc(doc.business_doctype,doc.business_name).check_permission('read')
    if doc.state_key!=state_key(doc.business_doctype,doc.business_name):
        frappe.throw('Invalid business conversation state key')
    if doc.last_read:
        page=messages(doc.business_doctype,doc.business_name,names=[doc.last_read],limit=1)
        if not page['items']:
            frappe.throw('Read position belongs to another business conversation',frappe.PermissionError)


def _state(doctype,name,*,create=False,lock=False):
    key=state_key(doctype,name)
    state_name=frappe.db.get_value('Relay Business Conversation State',{'state_key':key},'name',for_update=lock)
    if state_name:return frappe.get_doc('Relay Business Conversation State',state_name)
    if not create:return None
    return frappe.get_doc({'doctype':'Relay Business Conversation State','state_key':key,
        'user':frappe.session.user,'business_doctype':doctype,'business_name':name})


def _position(value):
    raw=json.loads(value) if isinstance(value,str) else (value or {})
    return raw if isinstance(raw,dict) else {}


def _assert_messages(doctype,name,names):
    if isinstance(names,str):names=frappe.parse_json(names)
    if not isinstance(names,list) or not names or len(names)>50 or any(not isinstance(item,str) for item in names):
        frappe.throw('Choose between 1 and 50 visible messages')
    unique=list(dict.fromkeys(names))
    page=messages(doctype,name,names=unique,limit=len(unique))
    rows={row['name']:row for row in page['items']}
    if set(rows)!=set(unique):
        frappe.throw('A message belongs to another business conversation',frappe.PermissionError)
    return unique,rows


def changed(doctype,name,kind='reads'):
    frappe.publish_realtime('relay_changed',{'kind':kind},doctype=doctype,docname=name,after_commit=True)


@frappe.whitelist(methods=['GET'])
def view_state(doctype,name):
    check_type(doctype);frappe.get_doc(doctype,name).check_permission('read')
    state=_state(doctype,name)
    if not state:return {}
    position=_position(state.chat_view)
    if position.get('name'):
        try:_assert_messages(doctype,name,[position['name']])
        except (frappe.PermissionError,frappe.ValidationError):return {}
    return dict(position,last_read=state.last_read)


@frappe.whitelist(methods=['POST'])
def save_view(doctype,name,message,offset=0,at_bottom=0):
    check_type(doctype);frappe.get_doc(doctype,name).check_permission('read')
    validate_reference(message,'MSG');_assert_messages(doctype,name,[message])
    try:offset=float(offset)
    except (ValueError,TypeError):frappe.throw('Invalid viewport offset')
    if not -2000<=offset<=2000 or str(at_bottom) not in ('0','1'):
        frappe.throw('Invalid viewport position')
    key=state_key(doctype,name)
    with frappe.cache.lock('relay-business-inbox-'+key,timeout=10,blocking_timeout=3):
        state=_state(doctype,name,create=True,lock=True)
        state.chat_view=json.dumps({'name':message,'offset':offset,'atBottom':str(at_bottom)=='1'})
        state.last_seen=frappe.utils.now_datetime()
        state.save(ignore_permissions=True);frappe.db.commit()
    return {'saved':True}


@frappe.whitelist(methods=['POST'])
def mark_visible(doctype,name,messages,last_read=None):
    check_type(doctype);frappe.get_doc(doctype,name).check_permission('read')
    names,rows=_assert_messages(doctype,name,messages)
    if last_read is not None and last_read not in names:frappe.throw('Read cursor must be visible')
    user=frappe.session.user;key=state_key(doctype,name);created=False
    with frappe.cache.lock('relay-business-inbox-'+key,timeout=15,blocking_timeout=3):
        previous=getattr(frappe.flags,'relay_read_write',False);frappe.flags.relay_read_write=True
        try:
            state=_state(doctype,name,create=True,lock=True)
            if last_read and (not state.last_read or last_read>state.last_read):state.last_read=last_read
            state.last_seen=frappe.utils.now_datetime();state.save(ignore_permissions=True)
            for message in names:
                read_key=hashlib.sha256((user+':'+message).encode()).hexdigest()
                if frappe.db.exists('Relay Message Read',{'read_key':read_key}):continue
                frappe.get_doc({'doctype':'Relay Message Read','user':user,'relay_contact':rows[message]['relay_contact'],
                    'message':message,'read_key':read_key}).insert(ignore_permissions=True);created=True
            if created:changed(doctype,name)
            frappe.db.commit()
        finally:frappe.flags.relay_read_write=previous
    return {'marked':names,'last_read':state.last_read}


@frappe.whitelist(methods=['GET'])
def presence(doctype,name):
    check_type(doctype);frappe.get_doc(doctype,name).check_permission('read')
    cutoff=frappe.utils.add_to_date(frappe.utils.now_datetime(),seconds=-90)
    rows=frappe.get_all('Relay Business Conversation State',filters={'business_doctype':doctype,'business_name':name,
        'last_seen':['>',cutoff]},fields=['user'],order_by='last_seen desc',limit_page_length=11)
    users=[]
    for row in rows:
        if row.user==frappe.session.user or not frappe.db.get_value('User',row.user,'enabled'):continue
        if not frappe.get_doc(doctype,name).has_permission('read',user=row.user):continue
        users.append({'name':row.user,'full_name':frappe.db.get_value('User',row.user,'full_name'),
            'typing':bool(frappe.cache.get_value('relay-business-typing-'+state_key(doctype,name,row.user)))})
    return {'users':users[:10]}


@frappe.whitelist(methods=['POST'])
def typing(doctype,name,contact,active=1,message=None):
    """Publish an agent typing state inside one permission-checked business room."""
    check_type(doctype);frappe.get_doc(doctype,name).check_permission('read')
    if str(active) not in ('0','1','True','False'):
        frappe.throw('Invalid typing state')
    readable_contact(contact)
    from relay_core.business_access import candidates,reference
    if (doctype,name) not in candidates(contact):
        frappe.throw('Contact is not linked to this business conversation',frappe.PermissionError)
    if message:
        validate_reference(message,'MSG')
        source=frappe.get_doc('Relay Message',message);source.check_permission('read')
        if source.relay_contact!=contact or reference(source)!=(doctype,name):
            frappe.throw('Typing source belongs to another business conversation',frappe.PermissionError)
    key='relay-business-typing-'+state_key(doctype,name)
    if str(active) in ('1','True'):
        frappe.cache.set_value(key,True,expires_in_sec=8)
    else:
        frappe.cache.delete_value(key)
    changed(doctype,name,'presence')
    return {'ok':True}


def _linked_contacts(doctype, name, query='', limit=31):
    if not isinstance(query,str) or len(query)>80 or any(ord(c)<32 for c in query):
        frappe.throw('Invalid contact search')
    filters=[['Dynamic Link','link_doctype','=',doctype],['Dynamic Link','link_name','=',name]]
    options={}
    if query.strip():
        pattern='%'+query.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        options['or_filters']=[['Contact',field,'like',pattern]
            for field in ('name','full_name','mobile_no','phone','email_id')]
    return frappe.get_list('Contact',filters=filters,
        fields=['name','full_name','mobile_no','phone','email_id'],order_by='name asc',
        page_length=limit,distinct=True,**options)


@frappe.whitelist(methods=['GET'])
def context(doctype,name):
    check_type(doctype);doc=frappe.get_doc(doctype,name);doc.check_permission('read')
    meta=frappe.get_meta(doctype)
    title=(doc.get(meta.title_field) if meta.title_field else None) or name
    contacts=_linked_contacts(doctype,name,limit=101)
    grouping_field=frappe.db.get_value('Relay Contact Type',{'business_doctype':doctype,'enabled':1},'grouping_field') or ''
    return {'name':name,'title':title,'doctype':doctype,'doctype_label':frappe._(doctype),
            'grouping_value':doc.get(grouping_field) if grouping_field else '',
            'contact_count':min(len(contacts),100),'contact_count_limited':len(contacts)>100}


@frappe.whitelist(methods=['GET'])
def records(doctype, query='', after=None):
    check_type(doctype)
    if not isinstance(query,str) or len(query)>80 or any(ord(c)<32 for c in query):
        frappe.throw('Invalid business record search')
    if after is not None and (not isinstance(after,str) or len(after)>140):
        frappe.throw('Invalid business record cursor')
    pattern='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    filters={'name':['like',pattern]}
    if after:filters=[['name','like',pattern],['name','>',after]]
    rows=frappe.get_list(doctype,filters=filters,fields=['name'],order_by='name asc',page_length=31)
    return {'items':rows[:30], 'next':rows[29].name if len(rows)>30 else None}


@frappe.whitelist(methods=['GET'])
def messages(doctype, name, before=None, after=None, channel=None, limit=50, from_date=None, to_date=None, medium=None, names=None, query=None, since=None):
    check_type(doctype)
    if not isinstance(name,str) or not name or len(name)>140:
        frappe.throw('Choose a business record')
    frappe.get_doc(doctype,name).check_permission('read')
    if sum(bool(value) for value in (before, after, since)) > 1:frappe.throw('Choose one message cursor')
    for value,prefix in ((before,'MSG'),(after,'MSG'),(since,'MSG'),(channel,'CH')):
        if value is not None:validate_reference(value,prefix)
    if isinstance(limit,bool) or not str(limit).isdigit() or not 1<=int(limit)<=100:
        frappe.throw('Message limit must be between 1 and 100')
    limit=int(limit)
    relay=frappe.qb.DocType('Relay Contact');link=frappe.qb.DocType('Dynamic Link')
    linked=(frappe.qb.from_(relay).join(link).on(relay.contact==link.parent).select(relay.name)
            .where((link.parenttype=='Contact') & (link.parentfield=='links') &
                   (link.link_doctype==doctype) & (link.link_name==name)))
    message=frappe.qb.DocType('Relay Message')
    filters={}
    if channel:filters['channel']=channel
    if query is not None:
        if not isinstance(query,str) or len(query)>100 or any(ord(c)<32 for c in query):frappe.throw('Invalid message search')
        if query.strip():filters['content']=['like','%'+query.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%']
    if names is not None:
        names=frappe.parse_json(names) if isinstance(names,str) else names
        if not isinstance(names,list) or not 1<=len(names)<=50:frappe.throw('Refresh between 1 and 50 messages')
        for item in names:validate_reference(item,'MSG')
        filters['name']=['in',names]
    fields=['name','relay_contact','channel','content','direction','status','creation','sent_at','provider_context',
            'message_type','message_data','reactions','edited_at','provider_id','sender_endpoint']
    # Frappe applies role/user permissions and the assignment query hook before LIMIT.
    from relay_core.timeline import page_query
    query=page_query(fields,filters,limit+1,before,since or after,ingestion=bool(since))
    if from_date is not None or to_date is not None:
        from relay_core.prepared_reports import date_range
        from pypika.functions import Coalesce
        start, end = date_range(from_date, to_date)
        timestamp = Coalesce(message.sent_at, message.creation)
        query = query.where((timestamp >= start) & (timestamp < end))
    # Only this business's messages belong in its timeline. Legacy unassociated
    # messages are visible only through the global single-business permission rule.
    scope=((message.business_doctype==doctype)&(message.business_name==name)) | (message.business_name.isnull() | (message.business_name==''))
    if medium not in (None, '', 'WhatsApp', 'Telegram', 'Email'):frappe.throw('Unsupported business inbox channel')
    channels=frappe.qb.DocType('Relay Channel')
    available=frappe.qb.from_(channels).select(channels.name)
    if medium:available=available.where(channels.channel==medium)
    query=query.where(message.channel.isin(available))
    watermark = []
    if not since and names is None:
        watermark = (page_query(['name'],filters,1,ingestion=True).where(message.relay_contact.isin(linked)).where(scope)
            .where(message.channel.isin(available)).run(as_dict=True))
    rows=query.where(message.relay_contact.isin(linked)).where(scope).run(as_dict=True)
    more=len(rows)>limit;page=rows[:limit]
    if not after and not since:page.reverse()
    readable={};items=[];channel_docs={}
    for row in page:
        if row.relay_contact not in readable:
            try:
                contact,_=readable_contact(row.relay_contact)
                readable[row.relay_contact]={
                    'label': contact.display_name or contact.name,
                    'frappe_contact': contact.contact or '',
                }
            except frappe.PermissionError:
                readable[row.relay_contact]=None
        if readable[row.relay_contact] is None:continue
        if row.channel not in channel_docs:
            channel_docs[row.channel] = frappe.get_doc('Relay Channel', row.channel)
            channel_docs[row.channel].check_permission('read')
        identity=readable[row.relay_contact]
        items.append(dict(row,contact_label=identity['label'],frappe_contact=identity['frappe_contact']))
    from relay_core.message_display import decorate_messages
    decorate_messages(items, channel_docs)
    cursor = page[-1].name if since and page else since if since else watermark[0].name if watermark else 'RELAY-MSG-0000000000'
    return {'items':items,'has_more':more,'ingestion_cursor':cursor,'first':page[0].name if page else None,'last':page[-1].name if page else None}


@frappe.whitelist(methods=['GET'])
def message_context(doctype,name,message,limit=25):
    validate_reference(message,'MSG')
    if isinstance(limit,bool) or not str(limit).isdigit() or not 1<=int(limit)<=50:frappe.throw('Context limit must be between 1 and 50')
    limit=int(limit)
    target=messages(doctype,name,names=[message],limit=1)
    if not target['items']:frappe.throw('Message is not available in this business conversation',frappe.PermissionError)
    older=messages(doctype,name,before=message,limit=limit)
    newer=messages(doctype,name,after=message,limit=limit)
    items=older['items']+target['items']+newer['items']
    return {'items':items,'first':items[0]['name'],'last':items[-1]['name'],
            'has_more':older['has_more'],'has_newer':newer['has_more'],'anchor':message}


@frappe.whitelist(methods=['GET'])
def contacts(doctype, name, query=''):
    check_type(doctype)
    frappe.get_doc(doctype,name).check_permission('read')
    rows=_linked_contacts(doctype,name,query,31)
    result=[]
    for row in rows[:30]:
        phone=(row.mobile_no or row.phone or '').strip()
        result.append({'value':row.name,'label':row.full_name or row.name,
                       'description':' · '.join(value for value in (phone,row.email_id) if value),
                       'has_phone':bool(phone)})
    return {'items':result,'has_more':len(rows)>30}
