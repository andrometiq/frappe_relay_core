"""Email submissions require verified endpoints and readable business contacts."""
import hashlib
import json
import re
import frappe
from relay_core.permissions import require_access, readable_contact
from relay_core.settings import value as connection_value
from relay_core import whatsapp


def recipients(values, *, required=False):
    if values is None:
        values = []
    if not isinstance(values, list) or len(values) > 50 or required and not values:
        raise ValueError('Provide between 1 and 50 recipient addresses')
    result = []
    for value in values:
        if not isinstance(value, str) or len(value) > 254 or not re.fullmatch(r'[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+', value):
            raise ValueError('Provide a plain email address without a display name')
        address = value.lower()
        if address not in result:
            result.append(address)
    return result


def recipient_lists(to, cc=None, bcc=None):
    values = recipients(to, required=True), recipients(cc), recipients(bcc)
    if sum(map(len, values)) > 50:
        raise ValueError('At most 50 recipients are allowed')
    return values


def verify_recipient(address, channels):
    for channel in channels:
        key = hashlib.sha256((channel.name + ':' + address).encode()).hexdigest()
        contact = frappe.db.get_value('Relay Contact Endpoint',
            {'endpoint_key': key, 'verified': 1}, 'relay_contact')
        if contact:
            frappe.get_doc('Relay Channel', channel.name).check_permission('read')
            readable_contact(contact)
            return contact
    frappe.throw('Every email recipient must have a verified business contact endpoint', frappe.PermissionError)


@frappe.whitelist(methods=['GET'])
def recipient_options(message, query=''):
    """Bounded contact suggestions; exact addresses may resolve other readable contacts."""
    from relay_core.messaging import readable_source
    source, channel, _ = readable_source(message)
    if channel.channel != 'Email':
        raise ValueError('Choose an email conversation')
    if not isinstance(query, str) or len(query) > 254:
        raise ValueError('Email search is too long')
    query = query.strip().lower()
    filters = {'channel': channel.name, 'verified': 1, 'relay_contact': source.relay_contact}
    if query:
        filters['endpoint'] = ['like', '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%']
    rows = frappe.get_all('Relay Contact Endpoint', filters=filters,
        fields=['endpoint', 'relay_contact'], order_by='endpoint asc', limit_page_length=30)
    # Forwarding/CC can target another verified business contact without exposing
    # an unrestricted directory. An exact address still requires contact access.
    if query and '@' in query and not any(row.endpoint == query for row in rows):
        key = hashlib.sha256((channel.name + ':' + query).encode()).hexdigest()
        contact = frappe.db.get_value('Relay Contact Endpoint',
            {'endpoint_key': key, 'verified': 1}, 'relay_contact')
        if contact:
            try:
                readable_contact(contact)
            except frappe.PermissionError:
                pass
            else:
                rows = [frappe._dict(endpoint=query), *rows][:30]
    return [{'value': row.endpoint, 'label': row.endpoint} for row in rows]


@frappe.whitelist(methods=['POST'])
def send(to, subject, body, cc=None, bcc=None, request_key=None, message=None, html=None, attachment_ids=None, forward=0, auto_submitted=0):
    """Journal every send before admission, including standalone notifications."""
    import uuid
    from relay_core import messaging
    from relay_core.automation.service import internal_save
    from relay_core.ticket_notifications import outgoing_notification
    recipient_lists(to, cc, bcc)
    values=dict(to=to,subject=subject,body=body,cc=cc,bcc=bcc,message=message,
        html=html,attachment_ids=attachment_ids,forward=forward,auto_submitted=auto_submitted)
    request_key=request_key or uuid.uuid4().hex
    if not isinstance(request_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',request_key):
        raise ValueError('A stable request key is required')
    encoded=json.dumps(values,sort_keys=True,separators=(',',':'))
    if len(encoded.encode())>1024*1024:raise ValueError('Email request exceeds 1 MiB')
    digest=hashlib.sha256(encoded.encode()).hexdigest()
    key=hashlib.sha256(('email:'+frappe.session.user+':'+request_key).encode()).hexdigest()
    with frappe.cache.lock('relay-email-attempt:'+key,timeout=120,blocking_timeout=3):
        notification=outgoing_notification.get()
        keys=[key,request_key] if notification and not message else [key]
        existing=frappe.db.get_value('Relay Message Action',{'request_key':['in',keys],'owner':frappe.session.user},'name')
        if existing:
            action=frappe.get_doc('Relay Message Action',existing);action.check_permission('read')
            if action.payload_hash!=digest:raise ValueError('Request key was already used for different content')
            return reconcile_action(action)
        source,channel,_=messaging.readable_source(message) if message else unanchored_target(to)
        if channel.channel!='Email':raise ValueError('Choose an email conversation')
        # Pre-journal notifications used the raw key. Adopt any durable intent
        # before a new hashed identity could admit the same notification again.
        legacy=None
        if notification and not message:
            legacy=messaging.delivery_receipt(frappe._dict(request_key=request_key),channel)
            if legacy is not None:key=request_key
        payload={'email_request':request_key,'email_values':values,
            'business':[source.get('business_doctype'),source.get('business_name')],
            'notification':notification}
        action=frappe.get_doc({'doctype':'Relay Message Action','request_key':key,
            'source_message':source.name,'start_contact':None if message else source.relay_contact,
            'operation':'email','target_channel':channel.name,
            'preview':str(body or '')[:300],'payload_hash':digest,
            'payload':json.dumps(payload),'status':'Dispatching'})
        internal_save(action,new=True);frappe.db.commit()
        if legacy is not None:return finish(action,legacy)
        return submit(action)


def unanchored_target(to, channel_name=None):
    require_access()
    addresses=recipients(to,required=True)
    filters={'channel':'Email','enabled':1,'account':connection_value('relay_hub_account')}
    if channel_name:filters['name']=channel_name
    channels=frappe.get_list('Relay Channel',filters=filters,fields=['name'],page_length=2)
    if len(channels)!=1:raise ValueError('Configure one enabled email channel for this account')
    channel=frappe.get_doc('Relay Channel',channels[0].name);channel.check_permission('read')
    contact=verify_recipient(addresses[0],channels)
    source=frappe._dict(name=None,relay_contact=contact,channel=channel.name,sender_endpoint=addresses[0])
    from relay_core.business_access import reference
    business=reference(source)
    if business:source.business_doctype,source.business_name=business
    return source,channel,{'provider':'Email'}


def target(action):
    from relay_core import messaging
    payload=messaging.object_value(action.payload)
    if action.source_message:
        source,channel,context=messaging.readable_source(action.source_message)
    else:
        source,channel,context=unanchored_target(payload['email_values']['to'],action.target_channel)
        if source.relay_contact!=action.start_contact:
            frappe.throw('Email destination binding changed',frappe.PermissionError)
    if channel.channel!='Email' or channel.name!=action.target_channel:
        frappe.throw('Email channel changed',frappe.PermissionError)
    values=payload['email_values']
    for address in set(recipients(values['to'],required=True)+recipients(values.get('cc'))+recipients(values.get('bcc'))):
        verify_recipient(address,[channel])
    return source,channel,context


def submit(action):
    from relay_core import messaging
    from relay_core.automation.service import internal_save
    payload=messaging.object_value(action.payload)
    try:
        messaging.admission_scope(action)
        arguments=prepare(**payload['email_values'],channel_name=action.target_channel)
        if payload.get('arguments') is not None and payload['arguments']!=arguments:
            raise ValueError('Email content changed before recovery')
        payload['arguments']=arguments
        action.payload=json.dumps(payload);internal_save(action);frappe.db.commit()
    except frappe.TimestampMismatchError:
        frappe.db.rollback()
        action.reload()
        return reconcile_action(action)
    except (ValueError,frappe.ValidationError,frappe.PermissionError,frappe.DoesNotExistError):
        return finish(action,{'delivery':{'state':'rejected'}})
    try:
        receipt=whatsapp.client().call_tool('email.send',dict(arguments,request_key=action.request_key))
    except Exception as exc:
        return messaging.record_submission_error(action,exc)
    return finish(action,receipt)


def reconcile_action(action):
    from relay_core import messaging
    from relay_core.automation.service import internal_save
    _,channel,_=target(action)
    if action.status in ('Submitted','Rejected'):return messaging.action_result(action)
    payload=messaging.object_value(action.payload)
    if action.source_message:
        local=send_status(action.source_message,payload['email_request'])
        if local.get('message'):
            frappe.db.get_value('Relay Message Action',action.name,'name',for_update=True)
            action.reload();action.outbound_message=local['message'];action.status='Submitted'
            internal_save(action);frappe.db.commit()
            return messaging.action_result(action)
    receipt=messaging.delivery_receipt(action,channel)
    if receipt is None:
        return submit(action) if action.status=='Dispatching' else messaging.action_result(action)
    return finish(action,receipt)


def finish(action,receipt,*,commit=True):
    from relay_core import messaging
    from relay_core.automation.service import internal_save
    frappe.db.get_value('Relay Message Action',action.name,'name',for_update=True)
    action.reload()
    status=messaging.receipt_status(receipt)
    identifier=receipt.get('message_id')
    valid=isinstance(identifier,str) and re.fullmatch(r'<[^<>\s@]{1,120}@[^<>\s@]{1,120}>',identifier)
    if messaging.stale_receipt(action,receipt,accepted=bool(valid and not status)):
        return messaging.action_result(action)
    if not status and valid:
        action.outbound_message=project(action,receipt)
        status='Submitted'
    action.status=status or 'Uncertain';action.result=json.dumps(receipt)
    internal_save(action)
    if commit:frappe.db.commit()
    return dict(messaging.action_result(action),**({'message_id':identifier} if valid else {}))


def prepare(to, subject, body, cc=None, bcc=None, message=None, html=None, attachment_ids=None, forward=0, auto_submitted=0, channel_name=None):
    require_access()
    to, cc, bcc = recipient_lists(to, cc, bcc)
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 998 or any(c in subject for c in '\r\n'):
        raise ValueError('Provide a single-line email subject')
    if not isinstance(body, str) or not body.strip() or len(body) > 100000:
        raise ValueError('Provide an email body of at most 100000 characters')
    channels = frappe.get_list('Relay Channel', filters={'channel': 'Email', 'enabled': 1,
        'account': connection_value('relay_hub_account'), **({'name':channel_name} if channel_name else {})}, fields=['name'], page_length=100)
    for address in set(to + cc + bcc):
        verify_recipient(address, channels)
    extra={}
    if str(auto_submitted) not in ('0','1'):raise ValueError('Invalid automatic reply flag')
    if str(auto_submitted)=='1':extra['auto_submitted']=True
    if html is not None:
        if not isinstance(html,str) or len(html.encode())>200000:raise ValueError('HTML body exceeds 200000 bytes')
        extra['html']=html
    if attachment_ids is None:attachment_ids=[]
    if not isinstance(attachment_ids,list) or len(attachment_ids)>8:raise ValueError('Choose at most eight attachments')
    if attachment_ids and not message:raise ValueError('Attachments require an accessible source conversation')
    if message:
        from relay_core import messaging, attachments
        source,channel,context=messaging.readable_source(message)
        if channel.channel!='Email':raise ValueError('Choose an email source message')
        if str(forward) not in ('0','1'):raise ValueError('Invalid forward flag')
        if str(forward)=='0':
            parent=context.get('message_id')
            if isinstance(parent,str) and re.fullmatch(r'<[^<>\s@]{1,120}@[^<>\s@]{1,120}>',parent):
                extra['in_reply_to']=parent
                refs=[ref for ref in context.get('references',[]) if isinstance(ref,str) and re.fullmatch(r'<[^<>\s@]{1,120}@[^<>\s@]{1,120}>',ref)]
                extra['references']=(refs+[parent])[-20:]
        files=[];total=0
        import base64,mimetypes
        for file_id in attachment_ids:
            file,raw=attachments.file_content(file_id,source);total+=len(raw)
            if total>attachments.MAX_BYTES:raise ValueError('Combined attachments exceed 4 MiB')
            files.append({'filename':file.file_name,'content_type':mimetypes.guess_type(file.file_name)[0] or 'application/octet-stream','content_base64':base64.b64encode(raw).decode()})
        if files:extra['attachments']=files
    return {'to':to,'cc':cc,'bcc':bcc,'subject':subject,'body':body,**extra}


def project(action,receipt):
    from relay_core import messaging
    from relay_core.automation.provenance import conversation_key
    from relay_core.message_updates import provider_key
    payload=messaging.object_value(action.payload)
    values=payload['email_values'];args=payload.get('arguments') or {}
    source,channel,context=target(action)
    history_key=action.request_key
    keys=history_keys(channel.account,payload['email_request']) if action.source_message else [history_key]
    existing=frappe.db.get_value('Relay Message',{'source_key':['in',keys],
        'owner':action.owner,'relay_contact':source.relay_contact,'channel':channel.name},'name')
    if existing:return existing
    business=payload.get('business') or [source.get('business_doctype'),source.get('business_name')]
    outgoing=frappe.get_doc({'doctype':'Relay Message','relay_contact':source.relay_contact,'channel':source.channel,
        'direction':'Outgoing','status':'Sent','content':values['body'],'message_type':'text','sender_endpoint':source.sender_endpoint,
        'provider_id':receipt['message_id'],'source_key':history_key,
        'business_doctype':business[0],'business_name':business[1],
        'conversation_key':conversation_key(source.channel,source.sender_endpoint,context),
        'provider_message_key':provider_key(source.channel,source.sender_endpoint,receipt['message_id']),
        'provider_context':json.dumps({'provider':'Email','message_id':receipt['message_id'],'subject':values['subject'],'references':args.get('references',[])}),
        'message_data':json.dumps({'kind':'text','text':values['body'],'email':{'subject':values['subject'],'html':values.get('html') or '',
            'to':recipients(values['to']),'cc':recipients(values.get('cc')),
            'attachments':[{'filename':item['filename'],'content_type':item['content_type']} for item in args.get('attachments',[])],
            'local_attachments':values.get('attachment_ids') or [],'attachment_source':source.name}})}).insert(ignore_permissions=True)
    return outgoing.name


@frappe.whitelist(methods=['GET'])
def mailbox_status():
    require_access(manage=True)
    return whatsapp.client().call_tool('email.mailbox',{})


def history_keys(account,request_key):
    current=hashlib.sha256(('email:'+frappe.session.user+':'+request_key).encode()).hexdigest()
    legacy=hashlib.sha256(('relay-email-history:'+account+':'+request_key).encode()).hexdigest()
    return [current,legacy]


@frappe.whitelist(methods=['GET'])
def send_status(message, request_key):
    """Read the persisted receipt without repeating an outbound provider call."""
    from relay_core.messaging import readable_source
    source, channel, _ = readable_source(message)
    if channel.channel != 'Email' or not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,140}', request_key):
        raise ValueError('Invalid email request')
    name=frappe.db.get_value('Relay Message', {'source_key':['in',history_keys(channel.account,request_key)],'owner':frappe.session.user,
        'relay_contact':source.relay_contact,'channel':source.channel}, 'name')
    if not name:return {'status':'Unconfirmed'}
    doc=frappe.get_doc('Relay Message',name);doc.check_permission('read')
    return {'status':doc.status,'message':doc.name}
