"""Campaign directory, Telegram/email history and recovery; WhatsApp bulk lives in bulk_campaigns."""
import hashlib
import time
import frappe
from relay_core.permissions import require_access
from relay_core.automation.contracts import canonical
from relay_core.automation.service import internal_save
from relay_core.settings import value as connection_value

ACTIVE=('Pending','Dispatching','Queued','Uncertain')


def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def campaign(name,active=False):
    require_access(manage=True);doc=frappe.get_doc('Relay Campaign',name);doc.check_permission('read')
    if doc.business_doctype:
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
    frappe.throw('WhatsApp campaigns are unavailable in v1')


@frappe.whitelist(methods=['GET'])
def channels():
    require_access(manage=True)
    return frappe.get_list('Relay Channel',filters={'channel':'WhatsApp','account':connection_value('relay_hub_account'),'enabled':1},fields=['name','account','channel'],page_length=20)


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
        fields=['name','title','status','creation','template_name','total_count','sent_count','replied_count'],order_by='name asc',page_length=31)
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


def process(name,refresh_only=False):
    if frappe.db.get_value('Relay Campaign', name, 'operation') in ('messages.send', 'templates.send'):
        return
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
        except Exception:
            frappe.db.rollback()
            frappe.db.set_value('Relay Campaign',name,'last_error','Campaign update failed. Check account configuration and recipient access; the same delivery keys will be retained during recovery.')
            # Dispatching entries stay recoverable with their original request keys.
        finally:
            frappe.set_user(original)
            frappe.db.set_value('Relay Campaign',name,'modified',frappe.utils.now_datetime());frappe.db.commit()


def recover():
    from relay_core.bulk_campaigns import recover as recover_bulk
    recover_bulk()
    rows=frappe.get_all('Relay Campaign',filters={'status':['in',['Running','Paused','Cancelling']],'operation':['in',['telegram.send','email.send']]},pluck='name',order_by='modified asc',limit_page_length=10)
    for name in rows:frappe.enqueue('relay_core.campaigns.process',name=name,queue='long',timeout=120)


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
