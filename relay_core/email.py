"""Email submissions require verified endpoints and readable business contacts."""
import hashlib
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


def verify_recipient(address, channels):
    for channel in channels:
        key = hashlib.sha256((channel.name + ':' + address).encode()).hexdigest()
        contact = frappe.db.get_value('Relay Contact Endpoint',
            {'endpoint_key': key, 'verified': 1}, 'relay_contact')
        if contact:
            frappe.get_doc('Relay Channel', channel.name).check_permission('read')
            readable_contact(contact)
            return
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
    """Persist the attempt before provider I/O; replay only reads its outcome."""
    import json
    import uuid
    values=dict(to=to,subject=subject,body=body,cc=cc,bcc=bcc,message=message,
        html=html,attachment_ids=attachment_ids,forward=forward,auto_submitted=auto_submitted)
    if not message:
        return _send(**values,request_key=request_key)
    from relay_core import messaging
    from relay_core.automation.service import internal_save
    from relay_core.hub import HubError
    source,channel,_=messaging.readable_source(message)
    if channel.channel!='Email':raise ValueError('Choose an email conversation')
    request_key=request_key or uuid.uuid4().hex
    if not isinstance(request_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',request_key):
        raise ValueError('A stable request key is required')
    encoded=json.dumps(values,sort_keys=True,separators=(',',':'))
    if len(encoded.encode())>1024*1024:raise ValueError('Email request exceeds 1 MiB')
    digest=hashlib.sha256(encoded.encode()).hexdigest()
    key=hashlib.sha256(('email:'+frappe.session.user+':'+request_key).encode()).hexdigest()
    with frappe.cache.lock('relay-email-attempt:'+key,timeout=120,blocking_timeout=3):
        existing=frappe.db.get_value('Relay Message Action',{'request_key':key},'name')
        if existing:
            action=frappe.get_doc('Relay Message Action',existing);action.check_permission('read')
            if action.payload_hash!=digest:raise ValueError('Request key was already used for different content')
            return reconcile_action(action)
        action=frappe.get_doc({'doctype':'Relay Message Action','request_key':key,
            'source_message':source.name,'operation':'email','target_channel':channel.name,
            'preview':str(body or '')[:300],'payload_hash':digest,
            'payload':json.dumps({'email_request':request_key,'email_values':values}),'status':'Dispatching'})
        internal_save(action,new=True);frappe.db.commit()
        dispatched=False
        def dispatching():
            nonlocal dispatched
            dispatched=True
        try:
            result=_send(**values,request_key=request_key,_dispatch=dispatching,_hub_request_key=action.request_key)
        except Exception as exc:
            frappe.db.get_value('Relay Message Action',action.name,'name',for_update=True)
            action.reload()
            if action.status=='Submitted' or messaging.object_value(action.result or {}).get('_relay_status_id'):
                return {'action':action.name,'status':action.status,'message':action.outbound_message}
            rejected=(not dispatched and isinstance(exc,(ValueError,frappe.ValidationError,frappe.PermissionError))) or (isinstance(exc,HubError) and exc.metadata.get('error',{}).get('outcome_unknown') is False)
            action.status='Rejected' if rejected else 'Uncertain'
            internal_save(action);frappe.db.commit()
            return {'action':action.name,'status':action.status,'message':None}
        frappe.db.get_value('Relay Message Action',action.name,'name',for_update=True)
        action.reload();action.outbound_message=result.get('message')
        action.status='Submitted' if action.outbound_message else 'Uncertain'
        internal_save(action);frappe.db.commit()
        return dict(result,action=action.name,status=action.status)


def reconcile_action(action):
    """Recover a local receipt only; an unknown provider outcome must not resend."""
    import json
    from relay_core.automation.service import internal_save
    payload=json.loads(action.payload) if isinstance(action.payload,str) else action.payload
    request=payload['email_request']
    receipt=send_status(action.source_message,request)
    if receipt.get('message'):
        action.reload();action.outbound_message=receipt['message'];action.status='Submitted'
        internal_save(action);frappe.db.commit()
    elif action.status=='Dispatching' and frappe.utils.time_diff_in_seconds(frappe.utils.now_datetime(),action.modified)>120:
        action.status='Uncertain';internal_save(action);frappe.db.commit()
    result={'action':action.name,'status':action.status,'message':action.outbound_message}
    if receipt.get('message'):result['message_id']=frappe.db.get_value('Relay Message',receipt['message'],'provider_id')
    return result


def _send(to, subject, body, cc=None, bcc=None, request_key=None, message=None, html=None, attachment_ids=None, forward=0, auto_submitted=0, _dispatch=None, _hub_request_key=None, _receipt=None, _commit=True):
    require_access()
    to, cc, bcc = recipients(to, required=True), recipients(cc), recipients(bcc)
    if len(to) + len(cc) + len(bcc) > 50:
        raise ValueError('At most 50 recipients are allowed')
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 998 or any(c in subject for c in '\r\n'):
        raise ValueError('Provide a single-line email subject')
    if not isinstance(body, str) or not body.strip() or len(body) > 100000:
        raise ValueError('Provide an email body of at most 100000 characters')
    channels = frappe.get_list('Relay Channel', filters={'channel': 'Email', 'enabled': 1,
        'account': connection_value('relay_hub_account')}, fields=['name'], page_length=100)
    for address in set(to + cc + bcc):
        verify_recipient(address, channels)
    if message and not request_key:
        import uuid
        request_key=uuid.uuid4().hex
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
    if _dispatch:_dispatch()
    result=dict(_receipt) if _receipt is not None else whatsapp.client().call_tool('email.send', {'to': to, 'cc': cc, 'bcc': bcc,
        'subject': subject, 'body': body, **({'request_key':_hub_request_key or request_key} if request_key else {}),**extra})
    if message and isinstance(result.get('message_id'),str) and re.fullmatch(r'<[^<>\s@]{1,120}@[^<>\s@]{1,120}>',result['message_id']):
        import json
        from relay_core.automation.provenance import conversation_key
        from relay_core.message_updates import provider_key
        history_key=hashlib.sha256(('relay-email-history:'+channel.account+':'+request_key).encode()).hexdigest()
        with frappe.cache.lock('relay-email-history-'+history_key,timeout=10,blocking_timeout=3):
            existing=frappe.db.get_value('Relay Message',{'source_key':history_key},'name')
            if not existing:
                # Recheck access after the external operation before projecting its receipt.
                messaging.readable_source(message)
                outgoing=frappe.get_doc({'doctype':'Relay Message','relay_contact':source.relay_contact,'channel':source.channel,
                    'direction':'Outgoing','status':'Sent','content':body,'message_type':'text','sender_endpoint':source.sender_endpoint,
                    'provider_id':result['message_id'],'source_key':history_key,
                    'conversation_key':conversation_key(source.channel,source.sender_endpoint,context),
                    'provider_message_key':provider_key(source.channel,source.sender_endpoint,result['message_id']),
                    'provider_context':json.dumps({'provider':'Email','message_id':result['message_id'],'subject':subject,'references':extra.get('references',[])}),
                    'message_data':json.dumps({'kind':'text','text':body,'email':{'subject':subject,'html':html or '',
                        'to':to,'cc':cc,'attachments':[{'filename':item['filename'],'content_type':item['content_type']} for item in extra.get('attachments',[])],
                        'local_attachments':attachment_ids,'attachment_source':source.name}})}).insert(ignore_permissions=True)
                existing=outgoing.name
                if _commit:frappe.db.commit()
            result=dict(result,message=existing)
    return result


@frappe.whitelist(methods=['GET'])
def mailbox_status():
    require_access(manage=True)
    return whatsapp.client().call_tool('email.mailbox',{})


@frappe.whitelist(methods=['GET'])
def send_status(message, request_key):
    """Read the persisted receipt without repeating an outbound provider call."""
    from relay_core.messaging import readable_source
    source, channel, _ = readable_source(message)
    if channel.channel != 'Email' or not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,140}', request_key):
        raise ValueError('Invalid email request')
    key=hashlib.sha256(('relay-email-history:'+channel.account+':'+request_key).encode()).hexdigest()
    name=frappe.db.get_value('Relay Message', {'source_key':key,
        'relay_contact':source.relay_contact,'channel':source.channel}, 'name')
    if not name:return {'status':'Unconfirmed'}
    doc=frappe.get_doc('Relay Message',name);doc.check_permission('read')
    return {'status':doc.status,'message':doc.name}
