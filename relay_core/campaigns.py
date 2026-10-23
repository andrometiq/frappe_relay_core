"""Bounded, explicit multi-channel campaigns backed by stable Hub delivery keys."""
import hashlib
import re
import time
import frappe
from relay_core import whatsapp
from relay_core.permissions import require_access
from relay_core.automation.contracts import canonical
from relay_core.automation.service import internal_save
from relay_core.settings import value as connection_value

ACTIVE=('Pending','Dispatching','Queued','Uncertain')


def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def campaign(name,active=False):
    require_access(manage=True);doc=frappe.get_doc('Relay Campaign',name);doc.check_permission('read')
    frappe.get_doc(doc.business_doctype,doc.business_name).check_permission('read')
    channel=frappe.get_doc('Relay Channel',doc.channel);channel.check_permission('read')
    if channel.channel not in ('WhatsApp','Telegram','Email') or active and (not channel.enabled or channel.account!=connection_value('relay_hub_account') or doc.account!=channel.account):
        frappe.throw('Campaign channel is disabled or belongs to another Hub account')
    return doc


def prepared(doc,contact,arguments=None):
    args=frappe.parse_json(arguments) if arguments else frappe.parse_json(doc.arguments)
    if doc.operation in ('telegram.send','email.send'):
        from relay_core.channel_campaigns import prepare
        return prepare(doc,contact,args)
    payload=whatsapp.prepare(doc.operation,args,contact,doc.business_doctype,doc.business_name)
    if doc.operation=='messages.send':
        from relay_core.timeline import page_query
        relay=frappe.db.get_value('Relay Contact',{'contact':contact},'name')
        rows=page_query(['name','sent_at','creation'],{'relay_contact':relay or '', 'channel':doc.channel,'direction':'Incoming','legacy_source':['is','not set']},1).run(as_dict=True)
        if not rows or frappe.utils.get_datetime(rows[0].sent_at or rows[0].creation)<frappe.utils.add_to_date(frappe.utils.now_datetime(),hours=-24):
            frappe.throw('Use an approved template when there is no recent incoming WhatsApp message')
    return payload


@frappe.whitelist(methods=['GET'])
def channels():
    require_access(manage=True)
    return frappe.get_list('Relay Channel',filters={'channel':'WhatsApp','account':connection_value('relay_hub_account'),'enabled':1},fields=['name','account','channel'],page_length=20)


@frappe.whitelist(methods=['POST'])
def create(title,channel,business_doctype,business_name,operation,arguments,request_key):
    require_access(manage=True)
    if not isinstance(title,str) or not 1<=len(title.strip())<=140 or not isinstance(request_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}',request_key):frappe.throw('Provide a campaign title and stable request key')
    if operation not in ('messages.send','templates.send'):frappe.throw('Choose a WhatsApp text or template campaign')
    args=frappe.parse_json(arguments) if isinstance(arguments,str) else arguments
    if not isinstance(args,dict) or len(canonical(args).encode())>16000:frappe.throw('Invalid campaign content')
    if operation=='email.send':
        if set(args)!={'subject','body'} or not isinstance(args['subject'],str) or not 1<=len(args['subject'].strip())<=998 or any(c in args['subject'] for c in '\r\n') or not isinstance(args['body'],str) or not 1<=len(args['body'].strip())<=10000:frappe.throw('Provide an email subject and body of at most 10000 characters')
    elif operation in ('messages.send','telegram.send'):
        if set(args)!={'body'} or not isinstance(args['body'],str) or not 1<=len(args['body'].strip())<=4096:frappe.throw('Message must contain 1–4096 characters')
    elif set(args)-{'name','language','components'} or not re.fullmatch(r'[a-z0-9_]{1,100}',str(args.get('name',''))) or not re.fullmatch(r'[A-Za-z_]{2,12}',str(args.get('language',''))):frappe.throw('Select a valid template name and language')
    key=digest([frappe.session.user,request_key])
    with frappe.cache.lock('relay-campaign-create:'+key,timeout=15):
        existing=frappe.db.get_value('Relay Campaign',{'request_key':key},'name')
        if existing:
            doc=campaign(existing)
            if (doc.title,doc.channel,doc.business_doctype,doc.business_name,doc.operation,frappe.parse_json(doc.arguments))!=(title.strip(),channel,business_doctype,business_name,operation,args):frappe.throw('Request key already used for a different campaign')
            return {'name':doc.name}
        frappe.get_doc(business_doctype,business_name).check_permission('read')
        if not whatsapp.configured_business_type(business_doctype):frappe.throw('Configure this business type in Desk first')
        target=frappe.get_doc('Relay Channel',channel);target.check_permission('read')
        if target.channel!='WhatsApp' or not target.enabled or target.account!=connection_value('relay_hub_account'):frappe.throw('Choose the enabled WhatsApp channel for this Hub account')
        doc=frappe.get_doc(dict(doctype='Relay Campaign',title=title.strip(),channel=channel,business_doctype=business_doctype,business_name=business_name,
            operation=operation,arguments=canonical(args),status='Draft',account=target.account,request_key=key))
        internal_save(doc,new=True);frappe.db.commit();return {'name':doc.name}


@frappe.whitelist(methods=['POST'])
def add_recipients(name,contacts):
    doc=campaign(name)
    contacts=frappe.parse_json(contacts) if isinstance(contacts,str) else contacts
    if not isinstance(contacts,list) or not 1<=len(contacts)<=50:frappe.throw('Add 1–50 distinct business contacts at a time')
    entries=[]
    for value in contacts:
        item={'contact':value} if isinstance(value,str) else value
        if not isinstance(item,dict) or set(item)-{'contact','arguments'} or not isinstance(item.get('contact'),str):frappe.throw('Invalid campaign recipient')
        args=frappe.parse_json(doc.arguments)
        override=item.get('arguments') or {}
        if not isinstance(override,dict) or set(override)-({'subject','body'} if doc.operation=='email.send' else {'body'} if doc.operation in ('messages.send','telegram.send') else {'components'}):frappe.throw('Only message content can vary per recipient')
        args={**args,**override}
        if len(canonical(args).encode())>16000:frappe.throw('Recipient content is too large')
        if doc.operation in ('messages.send','telegram.send') and (not isinstance(args.get('body'),str) or not 1<=len(args['body'].strip())<=4096):frappe.throw('Message must contain 1–4096 characters')
        if doc.operation=='email.send' and (not isinstance(args.get('subject'),str) or not 1<=len(args['subject'].strip())<=998 or any(c in args['subject'] for c in '\r\n') or not isinstance(args.get('body'),str) or not 1<=len(args['body'].strip())<=10000):frappe.throw('Invalid email subject or body')
        if doc.operation=='templates.send' and (not isinstance(args.get('components',[]),list) or len(args.get('components',[]))>20):frappe.throw('Invalid template parameters')
        entries.append((item['contact'],args))
    if len({item[0] for item in entries})!=len(entries):frappe.throw('Choose distinct business contacts')
    with frappe.cache.lock('relay-campaign:'+name,timeout=90):
        doc.reload()
        if doc.status!='Draft':frappe.throw('Recipients are fixed after a campaign starts')
        existing_contacts=set(frappe.get_all('Relay Campaign Recipient',filters={'campaign':name,'contact':['in',[entry[0] for entry in entries]]},pluck='contact',limit_page_length=50))
        if frappe.db.count('Relay Campaign Recipient',{'campaign':name})+sum(contact not in existing_contacts for contact,_ in entries)>1000:frappe.throw('A campaign supports up to 1000 recipients')
        for contact,args in entries:
            key=digest([name,contact])
            payload=prepared(doc,contact,args)
            existing=frappe.db.get_value('Relay Campaign Recipient',{'recipient_key':key},'prepared_hash')
            if existing:
                if existing!=digest(payload):frappe.throw('This contact already has different campaign content. Review its existing recipient row.')
                continue
            recipient=frappe.get_doc(dict(doctype='Relay Campaign Recipient',campaign=name,contact=contact,recipient_key=key,request_key='campaign-'+key,prepared_hash=digest(payload),destination=payload['to'],status='Pending',arguments=canonical(args)))
            internal_save(recipient,new=True)
        frappe.db.commit()
    return read(name)


@frappe.whitelist(methods=['GET'])
def directory(after=None,query='',status=None):
    require_access(manage=True)
    query=(query or '').strip()
    if len(query)>140:frappe.throw('Campaign search is too long')
    allowed_statuses=('Draft','Running','Paused','Cancelling','Completed','Cancelled')
    if status and status not in allowed_statuses:frappe.throw('Invalid campaign status')
    filters={'name':['>',after]} if after else {}
    if status:filters['status']=status
    pattern=f'%{query}%'
    rows=frappe.get_list('Relay Campaign',filters=filters,
        or_filters=[['Relay Campaign','name','like',pattern],['Relay Campaign','title','like',pattern]] if query else None,
        fields=['name','title','status','creation'],order_by='name asc',page_length=31)
    items=[]
    for row in rows[:30]:
        try:campaign(row.name)
        except frappe.PermissionError:continue
        items.append(row)
    return {'items':items,'next':rows[29].name if len(rows)>30 else None}


@frappe.whitelist(methods=['GET'])
def read(name,after=None,status=None):
    doc=campaign(name)
    filters={'campaign':name}
    if after:filters['name']=['>',after]
    if status:
        if status not in (*ACTIVE,'Submitted','Rejected','Cancelled'):frappe.throw('Invalid recipient status')
        filters['status']=status
    rows=frappe.get_list('Relay Campaign Recipient',filters=filters,fields=['name','contact','status','delivery_id','delivery_status','provider_id','reason'],order_by='name asc',page_length=51)
    from pypika.functions import Count
    recipient=frappe.qb.DocType('Relay Campaign Recipient')
    counts=frappe.qb.from_(recipient).select(recipient.status,Count(recipient.name).as_('count')).where(recipient.campaign==name).groupby(recipient.status).run(as_dict=True)
    return {**{key:doc.get(key) for key in ('name','title','channel','business_doctype','business_name','operation','status','execution_user','last_error')},
            'arguments':frappe.parse_json(doc.arguments),'recipients':[row for row in rows[:50] if frappe.get_doc('Contact',row.contact).has_permission('read')],'next':rows[49].name if len(rows)>50 else None,'counts':{row.status:row.count for row in counts}}


@frappe.whitelist(methods=['POST'])
def control(name,action):
    doc=campaign(name,active=action in ('start','resume'))
    if action not in ('start','pause','resume','cancel'):frappe.throw('Invalid campaign action')
    with frappe.cache.lock('relay-campaign:'+name,timeout=90):
        doc.reload()
        if action=='start':
            if doc.status!='Draft':frappe.throw('Only draft campaigns can start')
            if not frappe.db.exists('Relay Campaign Recipient',{'campaign':name}):frappe.throw('Add recipients first')
            doc.execution_user=frappe.session.user;doc.status='Running'
        elif action=='pause':
            if doc.status!='Running':frappe.throw('Only running campaigns can pause')
            doc.status='Paused'
        elif action=='resume':
            if doc.status!='Paused':frappe.throw('Only paused campaigns can resume')
            doc.execution_user=frappe.session.user;doc.status='Running'
        else:
            if doc.status in ('Completed','Cancelled'):return read(name)
            doc.execution_user=frappe.session.user;doc.status='Cancelling'
        internal_save(doc);frappe.db.commit()
        if doc.status in ('Running','Cancelling'):frappe.enqueue('relay_core.campaigns.process',name=name,queue='long',timeout=120)
    return read(name)


def receipt(row,value):
    if value.get('key')!=row.request_key:raise ValueError('Delivery receipt key mismatch')
    row.delivery_id=str(value.get('id') or row.delivery_id or '')
    row.status={'queued':'Queued','submitting':'Queued','submitted':'Submitted','rejected':'Rejected','cancelled':'Cancelled','uncertain':'Uncertain'}.get(value.get('state'),'Uncertain')
    row.delivery_status=value.get('delivery_status') or ''
    result=value.get('result') or {}
    if row.status=='Submitted':
        messages=result.get('messages') or []
        row.provider_id=str(messages[0].get('id') or '') if messages else ''
    row.reason='Provider rejected this delivery; review Delivery activity.' if row.status=='Rejected' else ''
    internal_save(row)
    if row.status=='Submitted' and row.provider_id:record_message(row)


def process(name,refresh_only=False):
    with frappe.cache.lock('relay-campaign:'+name,timeout=150,blocking_timeout=1):
        original=frappe.session.user
        deadline=time.monotonic()+55
        try:
            doc=frappe.get_doc('Relay Campaign',name)
            if doc.status not in ('Running','Paused','Cancelling') and not (refresh_only and doc.status=='Completed'):return
            if not frappe.db.get_value('User',doc.execution_user,'enabled'):raise frappe.PermissionError('Execution user disabled')
            frappe.set_user(doc.execution_user);campaign(name,active=doc.status=='Running' and not refresh_only)
            if doc.account!=connection_value('relay_hub_account'):raise ValueError('Hub account changed')
            if doc.operation in ('telegram.send','email.send'):
                from relay_core.channel_campaigns import tick
                tick(doc,refresh_only,deadline)
                return
            # Reconcile only a bounded set per tick; stable keys survive lost responses.
            inflight=frappe.get_all('Relay Campaign Recipient',filters={'campaign':name,'status':['in',['Dispatching','Queued','Uncertain']+(['Submitted'] if refresh_only else [])]},pluck='name',order_by='modified asc',limit_page_length=20)
            hub=None
            for target in inflight:
                if time.monotonic()>deadline:break
                row=frappe.get_doc('Relay Campaign Recipient',target)
                if hub is None:hub,_=whatsapp.checked_client()
                try:result=hub.call_tool('whatsapp.deliveries',{'request_key':row.request_key})
                except whatsapp.HubError:
                    if doc.status=='Running' and not row.delivery_id and not refresh_only:
                        row.status='Pending';internal_save(row)
                    else:
                        row.reason='Delivery journal unavailable; outcome remains unconfirmed.';internal_save(row)
                    frappe.db.commit();continue
                found=result.get('deliveries') or []
                if found:
                    receipt(row,found[0])
                    if doc.status=='Cancelling' and row.status=='Queued' and row.delivery_id:
                        try:
                            result=hub.call_tool('whatsapp.deliveries',{'request_key':row.request_key,'cancel_id':row.delivery_id})
                            if result.get('cancelled') is True:row.status='Cancelled';internal_save(row)
                        except whatsapp.HubError:
                            row.reason='Delivery could not be cancelled yet. Its provider state will be checked again.';internal_save(row)
                elif doc.status=='Cancelling':
                    row.status='Uncertain';row.reason='Hub admission was not confirmed. Cancellation remains pending until the journal can resolve it.';internal_save(row)
                elif doc.status=='Running':row.status='Pending';internal_save(row)
                frappe.db.commit()
            if doc.status=='Cancelling':
                pending=frappe.get_all('Relay Campaign Recipient',filters={'campaign':name,'status':'Pending'},pluck='name',limit_page_length=50)
                for target in pending:frappe.db.set_value('Relay Campaign Recipient',target,'status','Cancelled')
            elif doc.status=='Running' and not refresh_only and time.monotonic()<deadline:
                pending=frappe.get_all('Relay Campaign Recipient',filters={'campaign':name,'status':'Pending'},pluck='name',order_by='name asc',limit_page_length=25)
                batch=[];submitted=[]
                for target in pending:
                    row=frappe.get_doc('Relay Campaign Recipient',target)
                    try:
                        payload=prepared(doc,row.contact,row.arguments)
                        if digest(payload)!=row.prepared_hash:raise ValueError('Recipient or content changed')
                    except (ValueError,frappe.PermissionError,frappe.ValidationError):
                        row.status='Uncertain' if row.attempted else 'Rejected';row.reason='Recipient, business access or messaging window changed. Review the original delivery key before taking further action.';internal_save(row);continue
                    row.status='Dispatching';row.attempted=1;internal_save(row)
                    batch.append({'key':row.request_key,'message':payload});submitted.append(row)
                frappe.db.commit()
                if batch:
                    if hub is None:hub,_=whatsapp.checked_client()
                    result=hub.call_tool('whatsapp.enqueue',{'messages':batch})
                    by_key={value.get('key'):value for value in result.get('deliveries',[])}
                    for row in submitted:
                        if row.request_key in by_key:receipt(row,by_key[row.request_key])
                        else:row.status='Uncertain';internal_save(row)
            if not frappe.db.exists('Relay Campaign Recipient',{'campaign':name,'status':['in',list(ACTIVE)]}):
                doc.status='Cancelled' if doc.status=='Cancelling' else 'Completed';internal_save(doc)
            doc.last_error='';internal_save(doc);frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.db.set_value('Relay Campaign',name,'last_error','Campaign update failed. Check account configuration and recipient access; the same delivery keys will be retained during recovery.')
            # Dispatching entries stay recoverable with their original request keys.
        finally:
            frappe.set_user(original)
            frappe.db.set_value('Relay Campaign',name,'modified',frappe.utils.now_datetime());frappe.db.commit()


def recover():
    rows=frappe.get_all('Relay Campaign',filters={'status':['in',['Running','Paused','Cancelling']]},pluck='name',order_by='modified asc',limit_page_length=10)
    for name in rows:frappe.enqueue('relay_core.campaigns.process',name=name,queue='long',timeout=120)


@frappe.whitelist(methods=['POST'])
def refresh(name):
    campaign(name)
    process(name,refresh_only=True)
    return read(name)


def record_message(row):
    """Mirror a confirmed provider submission into the shared conversation history."""
    from relay_core.message_updates import provider_key
    from relay_core.automation.provenance import conversation_key
    if not row.destination:return
    doc=frappe.get_doc('Relay Campaign',row.campaign)
    key=provider_key(doc.channel,row.destination,row.provider_id)
    existing=frappe.db.get_value('Relay Message',{'source_key':row.request_key},['name','status'],as_dict=True) or frappe.db.get_value('Relay Message',{'provider_message_key':key},['name','status'],as_dict=True)
    if existing:
        state={'delivered':'Delivered','read':'Read'}.get(row.delivery_status)
        rank={'Pending':0,'Sent':1,'Delivered':2,'Read':3,'Failed':0}
        if state and rank[state]>rank.get(existing.status,0):frappe.db.set_value('Relay Message',existing.name,'status',state)
        return
    person=frappe.get_doc('Contact',row.contact);person.check_permission('read')
    contact=frappe.db.get_value('Relay Contact',{'contact':person.name},'name')
    if not contact:
        contact=frappe.get_doc(dict(doctype='Relay Contact',contact=person.name,display_name=person.full_name or person.name,automation_paused=1)).insert(ignore_permissions=True).name
    args=frappe.parse_json(row.arguments or doc.arguments)
    text=args.get('body') if doc.operation!='templates.send' else 'Template: '+args['name']
    data={'kind':'text','text':text,'campaign':doc.name}
    if doc.operation=='templates.send':data['template']=args
    provider=frappe.db.get_value('Relay Channel',doc.channel,'channel')
    context={'provider':provider,'message_id':int(row.provider_id) if provider=='Telegram' else row.provider_id}
    if provider=='Telegram':context['chat_id']=int(row.destination)
    if provider=='Email':
        context['subject']=args['subject'];data['email']={'subject':args['subject'],'to':[row.destination],'cc':[],'attachments':[]}
    frappe.get_doc(dict(doctype='Relay Message',relay_contact=contact,channel=doc.channel,direction='Outgoing',
        status={'delivered':'Delivered','read':'Read'}.get(row.delivery_status,'Sent'),content=text,message_type='text',message_data=canonical(data),
        provider_id=row.provider_id,sender_endpoint=row.destination,provider_context=canonical(context),provider_message_key=key,
        source_key=row.request_key,conversation_key=conversation_key(doc.channel,row.destination,context))).insert(ignore_permissions=True)
