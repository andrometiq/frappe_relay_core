"""Durable Telegram group delivery using the shared action recovery journal."""
import hashlib
import json
import re
import frappe
from relay_core import messaging, whatsapp
from relay_core.settings import value as connection_value
from relay_core.permissions import readable_contact
from relay_core.automation.service import internal_save


def target(doc):
    intent=messaging.object_value(doc.payload)['group']
    channel=frappe.get_doc('Relay Channel',doc.target_channel)
    channel.check_permission('read');readable_contact(doc.start_contact)
    chat_id=intent['chat_id']
    key=hashlib.sha256((channel.name+':'+str(chat_id)).encode()).hexdigest()
    contact=frappe.db.get_value('Relay Contact Endpoint',{'endpoint_key':key,'verified':1},'relay_contact')
    if (not channel.enabled or channel.channel!='Telegram' or channel.account!=connection_value('relay_hub_account')
            or contact!=doc.start_contact):
        frappe.throw('Telegram destination is no longer available',frappe.PermissionError)
    context={'provider':'Telegram','chat_id':chat_id,'chat_type':'supergroup' if chat_id < 0 else 'private'}
    if intent.get('message_thread_id'):context['message_thread_id']=intent['message_thread_id']
    source=frappe._dict(name=None,relay_contact=contact,channel=channel.name,sender_endpoint=str(chat_id))
    payload=messaging.object_value(doc.payload)
    business=payload.get('business')
    if business:
        source.business_doctype,source.business_name=business
        if all(business):
            from relay_core.ticket_notifications import recipient_business
            recipient_business(contact,channel.name,str(chat_id),*business,notification=payload.get('notification'),snapshot=True)
    if intent.get('reply_to'):
        from relay_core.message_updates import provider_key
        from relay_core.automation.provenance import conversation_key
        name=frappe.db.get_value('Relay Message',{'provider_message_key':provider_key(channel.name,str(chat_id),intent['reply_to']),
            'conversation_key':conversation_key(channel.name,str(chat_id),context)},'name')
        if not name:raise ValueError('Reply target is outside this Telegram topic')
        quoted=frappe.get_doc('Relay Message',name);quoted.check_permission('read')
        if business and business != [quoted.business_doctype,quoted.business_name]:
            raise ValueError('Reply target belongs to another business')
    return source,channel,context


def send_group(contact,channel,chat_id,text,reply_to,thread,request_key,business_doctype=None,business_name=None):
    if not isinstance(request_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',request_key):
        raise ValueError('A stable request key is required')
    intent={'chat_id':chat_id,'text':text,'reply_to':reply_to,'message_thread_id':thread}
    if business_doctype or business_name:
        intent.update(business_doctype=business_doctype,business_name=business_name)
    digest=hashlib.sha256(json.dumps([channel,contact,intent],sort_keys=True).encode()).hexdigest()
    key=hashlib.sha256((frappe.session.user+':'+request_key).encode()).hexdigest()
    existing=frappe.db.get_value('Relay Message Action',{'request_key':key},['name','payload_hash'],as_dict=True)
    if existing:
        if existing.payload_hash!=digest:raise ValueError('Request key already belongs to different content')
        return messaging.reconcile(existing.name)
    content={'kind':'text','text':text}
    args={'operation':'text',**{key:value for key,value in intent.items() if not key.startswith('business_')}}
    from relay_core.ticket_notifications import outgoing_notification
    payload={'group':intent,'tool':'telegram.message','arguments':args,'content':content,
        'notification':outgoing_notification.get()}
    action=frappe.get_doc({'doctype':'Relay Message Action','request_key':key,'payload_hash':digest,
        'operation':'text','start_contact':contact,'target_channel':channel,'preview':text[:300],
        'payload':json.dumps(payload),'status':'Dispatching'})
    source,channel_doc,context=target(action)
    from relay_core.ticket_notifications import recipient_business
    payload['business']=list(recipient_business(contact,channel,str(chat_id),business_doctype,business_name,
        notification=payload.get('notification')))
    action.payload=json.dumps(payload)
    internal_save(action,new=True);frappe.db.commit()
    try:
        source,channel_doc,context=messaging.admission_scope(action)
    except (frappe.PermissionError,frappe.DoesNotExistError):
        action.status='Rejected';internal_save(action);frappe.db.commit();raise
    try:
        result=whatsapp.client().call_tool('telegram.message',dict(args,request_key=key))
    except Exception as exc:
        return messaging.record_submission_error(action, exc)
    return messaging.finish(action,source,channel_doc,context,content,result)


@frappe.whitelist(methods=['GET'])
def pending(endpoint, before=None):
    """Restore only the caller's actions for a currently verified group."""
    from relay_core.permissions import require_access
    require_access();messaging.validate_reference(endpoint,'CE')
    if before:messaging.validate_reference(before,'MA')
    binding=frappe.get_doc('Relay Contact Endpoint',endpoint)
    if not binding.verified or not re.fullmatch(r'-[0-9]{1,16}',binding.endpoint or ''):
        frappe.throw('Select a verified Telegram group',frappe.PermissionError)
    chat_id=int(binding.endpoint)
    target(frappe._dict(start_contact=binding.relay_contact,target_channel=binding.channel,
        payload={'group':{'chat_id':chat_id}}))
    filters={'owner':frappe.session.user,'start_contact':binding.relay_contact,'target_channel':binding.channel,
        'status':['in',['Dispatching','Queued','Uncertain','Rejected']]}
    if before:filters['name']=['<',before]
    rows=frappe.get_all('Relay Message Action',filters=filters,
        fields=['name','owner','source_message','status','payload','result','creation'],order_by='name desc',limit_page_length=51)
    # A retried failure remains in the audit journal, but the pending panel
    # follows its child action. Resolve at most one page in one indexed query.
    retry_keys={row.name:hashlib.sha256((frappe.session.user+':'+messaging.retry_key(row.name)).encode()).hexdigest()
        for row in rows[:50] if row.status=='Rejected'}
    retried=set(frappe.get_all('Relay Message Action',filters={'owner':frappe.session.user,
        'request_key':['in',list(retry_keys.values())]},pluck='request_key',limit_page_length=50)) if retry_keys else set()
    items=[]
    from relay_core.business_access import action_permission
    for row in rows[:50]:
        if not action_permission(row):continue
        if retry_keys.get(row.name) in retried:continue
        intent=messaging.object_value(row.payload).get('group')
        if not isinstance(intent,dict) or intent.get('chat_id')!=chat_id:continue
        items.append({'action':row.name,'status':row.status,'args':intent,'error':messaging.action_error(row),'creation':row.creation})
    return {'items':items,'next':rows[49].name if len(rows)>50 else None}
