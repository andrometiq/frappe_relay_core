"""Account-scoped observed Telegram topics; never claims to enumerate all forums."""
import hashlib
import frappe
from relay_core.business_access import document_name
from relay_core.automation.provenance import integer
from relay_core.automation.service import internal_save
from relay_core.permissions import require_access, readable_contact
from relay_core.settings import value as connection_value


def remember(channel, chat_id, thread_id, *, title=None, state=None, timestamp=None):
    integer(chat_id);integer(thread_id, positive=True)
    if chat_id >= 0:raise ValueError('Topics require a group')
    if title is not None and (not isinstance(title,str) or not 1<=len(title.strip())<=128):raise ValueError('Invalid topic title')
    if state is not None and state not in ('Open','Closed','Hidden','Deleted'):raise ValueError('Invalid topic state')
    key=hashlib.sha256(f'{channel}:{chat_id}:{thread_id}'.encode()).hexdigest()
    stamp=frappe.utils.get_datetime(timestamp or frappe.utils.now_datetime())
    with frappe.cache.lock('relay-telegram-topic:'+key,timeout=30,blocking_timeout=5):
        name=frappe.db.get_value('Relay Telegram Topic',{'topic_key':key},'name')
        doc=frappe.get_doc('Relay Telegram Topic',name) if name else frappe.get_doc({'doctype':'Relay Telegram Topic','topic_key':key,'channel':channel,'chat_id':str(chat_id),'thread_id':str(thread_id),'title':'General' if thread_id==1 else f'Topic {thread_id}','state':'Open'})
        if name and title is None and state is None:return
        if doc.last_event_at and frappe.utils.get_datetime(doc.last_event_at)>stamp:return
        if title is not None:doc.title=title.strip()
        if state is not None:doc.state=state
        if title is not None or state is not None:doc.last_event_at=stamp
        internal_save(doc,new=not name)
        # This cache is independently replayable; commit before releasing its lock.
        frappe.db.commit()


def observe(payload, channel):
    raw=payload.get('payload')
    if payload.get('direction')!='inbound' or not isinstance(raw,dict):return
    message=raw.get('message')
    if not isinstance(message,dict):return
    chat=message.get('chat') or {}
    if chat.get('type')!='supergroup' or not chat.get('is_forum'):return
    chat_id=integer(chat.get('id'))
    if str(chat_id)!=payload.get('sender') or str(raw.get('update_id'))!=payload.get('provider_id'):raise ValueError('Topic event provenance mismatch')
    thread=message.get('message_thread_id')
    if thread is None:return
    integer(thread,positive=True)
    title=None;state=None
    for kind,status in [('forum_topic_created','Open'),('forum_topic_edited',None),('forum_topic_closed','Closed'),('forum_topic_reopened','Open'),('general_forum_topic_hidden','Hidden'),('general_forum_topic_unhidden','Open')]:
        if kind in message:
            detail=message[kind]
            if not isinstance(detail,dict):raise ValueError('Invalid topic event')
            title=detail.get('name') or None;state=status;break
    from relay_core.timeline import provider_time
    timestamp=provider_time(payload,{'timestamp':message.get('date')})
    if timestamp is None:return
    remember(channel,chat_id,thread,title=title,state=state,timestamp=timestamp)


def action(operation, arguments, result, channel):
    if not operation.startswith('topics.'):return
    response=result.get('result') if isinstance(result,dict) else None
    if not response:return
    thread=1 if operation.startswith('topics.general.') else arguments.get('message_thread_id')
    if operation=='topics.create':thread=response.get('message_thread_id') if isinstance(response,dict) else None
    if thread is None:return
    suffix=operation.split('.')[-1]
    state={'create':'Open','close':'Closed','reopen':'Open','hide':'Hidden','unhide':'Open','delete':'Deleted'}.get(suffix)
    title=arguments.get('name') if suffix in ('create','edit') else None
    remember(channel,arguments['chat_id'],thread,title=title,state=state)


@frappe.whitelist(methods=['GET'])
def directory(channel, chat_id, after=None):
    document_name(channel)
    require_access(manage=True)
    doc=frappe.get_doc('Relay Channel',channel);doc.check_permission('read')
    if doc.channel!='Telegram' or not doc.enabled or doc.account!=connection_value('relay_hub_account'):frappe.throw('Unavailable Telegram channel',frappe.PermissionError)
    try:chat=int(chat_id);integer(chat)
    except (ValueError,TypeError):frappe.throw('Invalid group')
    if chat>=0:frappe.throw('Select a group')
    key=hashlib.sha256(f'{channel}:{chat}'.encode()).hexdigest()
    contact=frappe.db.get_value('Relay Contact Endpoint',{'endpoint_key':key,'verified':1},'relay_contact')
    if not contact:frappe.throw('Verify this group endpoint first',frappe.PermissionError)
    readable_contact(contact)
    filters={'channel':channel,'chat_id':str(chat),'state':['!=','Deleted']}
    if after:
        if not isinstance(after,str) or len(after)>140:frappe.throw('Invalid topic cursor')
        filters['name']=['>',after]
    rows=frappe.get_all('Relay Telegram Topic',filters=filters,fields=['name','thread_id','title','state'],order_by='name asc',limit_page_length=31)
    return {'items':rows[:30],'next':rows[29].name if len(rows)>30 else None}
