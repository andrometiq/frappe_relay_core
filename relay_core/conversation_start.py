"""Start a private conversation through an existing verified contact endpoint."""
import hashlib
import json
import re
import frappe
from relay_core.permissions import require_access, readable_contact
from relay_core.settings import value as connection_value
from relay_core import messaging, whatsapp, service_window
from relay_core.automation.service import internal_save
from relay_core.message_types import text


def business_contact(contact, business_doctype, business_name):
    """Resolve one permission-checked Frappe Contact linked to the business."""
    require_access()
    from relay_core.business_inbox import check_type
    check_type(business_doctype)
    business=frappe.get_doc(business_doctype,business_name);business.check_permission('read')
    person=frappe.get_doc('Contact',contact);person.check_permission('read')
    if not any(link.link_doctype==business_doctype and link.link_name==business_name for link in person.links):
        frappe.throw('Contact is not linked to this business',frappe.PermissionError)
    return person


def business_channels(contact, business_doctype, business_name):
    person = business_contact(contact, business_doctype, business_name)
    relay = frappe.db.get_value('Relay Contact', {'contact': person.name}, 'name')
    if not relay:
        return []
    rows = options(relay, business_doctype, business_name)
    return [dict(row, endpoint=row['value'], value=frappe.db.get_value(
        'Relay Contact Endpoint', row['value'], 'channel')) for row in rows]


@frappe.whitelist(methods=['GET'])
def business_options(contact, business_doctype, business_name):
    return business_channels(contact,business_doctype,business_name)


def ensure_business_binding(contact, channel_name, business_doctype, business_name, endpoint=None):
    choices = [row for row in business_channels(contact, business_doctype, business_name)
               if row['value'] == channel_name and (endpoint is None or row['endpoint'] == endpoint)]
    if len(choices) != 1:
        frappe.throw('Choose one verified endpoint for this business', frappe.PermissionError)
    binding = frappe.get_doc('Relay Contact Endpoint', choices[0]['endpoint'])
    return binding.relay_contact, binding.name


@frappe.whitelist(methods=['POST'])
def send_business(contact, channel, kind, data, request_key, business_doctype, business_name, endpoint=None):
    relay, endpoint = ensure_business_binding(contact, channel, business_doctype, business_name, endpoint)
    return send(relay, endpoint, kind, data, request_key, business_doctype, business_name)


def target(contact, endpoint, business_doctype=None, business_name=None):
    require_access();readable_contact(contact)
    binding=frappe.get_doc('Relay Contact Endpoint',endpoint)
    if binding.relay_contact!=contact or not binding.verified:
        frappe.throw('Choose a verified endpoint for this contact',frappe.PermissionError)
    channel=frappe.get_doc('Relay Channel',binding.channel);channel.check_permission('read')
    if not channel.enabled or channel.account!=connection_value('relay_hub_account') or channel.channel not in ('WhatsApp','Telegram','Email'):
        frappe.throw('The channel is unavailable',frappe.PermissionError)
    if channel.channel != 'Email' and (not re.fullmatch(r'[0-9]{1,16}',binding.endpoint or '') or int(binding.endpoint)<=0):
        frappe.throw('Use Groups to start a group conversation')
    context={'provider':channel.channel}
    if channel.channel == 'Telegram':
        context.update(chat_id=int(binding.endpoint),chat_type='private')
    source=frappe._dict(name=None,relay_contact=contact,channel=channel.name,sender_endpoint=binding.endpoint)
    from relay_core.business_access import choose_business
    source.business_doctype,source.business_name=choose_business(contact,business_doctype,business_name)
    return source,channel,context


@frappe.whitelist(methods=['GET'])
def options(contact, business_doctype=None, business_name=None):
    require_access();readable_contact(contact)
    rows=frappe.get_all('Relay Contact Endpoint',filters={'relay_contact':contact,'verified':1},fields=['name'],limit_page_length=50)
    result=[]
    for row in rows:
        try:source,channel,context=target(contact,row.name,business_doctype,business_name)
        except (frappe.PermissionError,frappe.ValidationError):continue
        result.append({'value':row.name,'label':channel.channel+' · '+source.sender_endpoint,'provider':channel.channel,
                       'window':service_window.status(contact,channel.name,source.sender_endpoint) if channel.channel=='WhatsApp' else {'open':True}})
    return result


def prepared(contact, endpoint, kind, data, business_doctype=None, business_name=None):
    source,channel,context=target(contact,endpoint,business_doctype,business_name)
    data=messaging.object_value(data)
    if kind=='whatsapp' and channel.channel=='WhatsApp':
        if set(data) != {'operation', 'arguments'} or data['operation'] not in whatsapp.SEND:
            raise ValueError('Invalid WhatsApp message')
        person = frappe.db.get_value('Relay Contact', contact, 'contact')
        args = whatsapp.prepare(data['operation'], data['arguments'], person,
                                source.business_doctype, source.business_name)
        if args['to'] != source.sender_endpoint:
            raise ValueError('Conversation destination changed')
        if data['operation'] != 'templates.send':
            service_window.require_open(contact, channel.name, source.sender_endpoint)
        content = whatsapp_content(args)
        if args.get('reply_to'):
            from relay_core.message_updates import provider_key
            reference = frappe.db.get_value('Relay Message', {'provider_message_key': provider_key(channel.name, source.sender_endpoint, args['reply_to'])}, 'name')
            if not reference: raise ValueError('Reply target is not in this conversation')
            quoted = frappe.get_doc('Relay Message', reference); quoted.check_permission('read')
            if (quoted.business_doctype, quoted.business_name) != (source.business_doctype, source.business_name):
                raise ValueError('Reply target belongs to another business')
            if content['kind'] == 'reaction': source = quoted
        elif content['kind'] == 'reaction':
            raise ValueError('A reaction requires a reply target')
        tool = 'whatsapp.execute'
    elif kind=='text' and channel.channel in ('WhatsApp','Telegram'):
        if set(data)!={'text'}:raise ValueError('Unexpected message fields')
        content={'kind':'text','text':text(data.get('text'),4096,required=True)}
        if channel.channel=='WhatsApp':
            service_window.require_open(contact,channel.name,source.sender_endpoint)
            tool='whatsapp.execute';args={'operation':'messages.send','to':source.sender_endpoint,'body':content['text']}
        else:
            tool='telegram.message';args={'operation':'text','chat_id':int(source.sender_endpoint),'text':content['text']}
    elif kind=='template' and channel.channel=='WhatsApp':
        if set(data)-{'name','language','components'} or not re.fullmatch(r'[a-z0-9_]{1,512}',data.get('name','')) or not re.fullmatch(r'[A-Za-z_]{2,20}',data.get('language','')):
            raise ValueError('Choose a valid template')
        if not isinstance(data.get('components',[]),list) or len(json.dumps(data))>32000:raise ValueError('Invalid template parameters')
        tool='whatsapp.execute';args={'operation':'templates.send','to':source.sender_endpoint,**data}
        content={'kind':'text','text':'Template: '+data['name'],'template':data}
    else:raise ValueError('Unsupported starting message')
    return source,channel,context,tool,args,content


@frappe.whitelist(methods=['POST'])
def send(contact, endpoint, kind, data, request_key, business_doctype=None, business_name=None):
    if not isinstance(request_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',request_key):raise ValueError('A stable request key is required')
    key=hashlib.sha256((frappe.session.user+':'+request_key).encode()).hexdigest()
    with frappe.cache.lock('relay-start:'+key,timeout=120,blocking_timeout=3):
        return send_locked(contact,endpoint,kind,data,request_key,business_doctype,business_name)


def send_locked(contact, endpoint, kind, data, request_key, business_doctype, business_name):
    # Repeated attempts look up the original action even if its 24-hour window has elapsed.
    source,channel,context=target(contact,endpoint,business_doctype,business_name)
    data=messaging.object_value(data)
    key=hashlib.sha256((frappe.session.user+':'+request_key).encode()).hexdigest()
    email_key=hashlib.sha256(('email:'+frappe.session.user+':'+request_key).encode()).hexdigest()
    other_key=key if channel.channel == 'Email' else email_key
    if frappe.db.get_value('Relay Message Action',{'request_key':other_key},'name',for_update=True):
        raise ValueError('Request key already belongs to another channel')
    if channel.channel == 'Email':
        if kind != 'email' or set(data) - {'subject','body','html'}:
            raise ValueError('Provide an email subject and body')
        from relay_core.email import send as send_email
        return send_email([source.sender_endpoint], data.get('subject'), data.get('body'),
            html=data.get('html'), request_key=request_key, channel_name=channel.name,
            business_doctype=source.business_doctype, business_name=source.business_name)
    intent={'contact':contact,'endpoint':endpoint,'destination':source.sender_endpoint,'channel':channel.name,'kind':kind,'data':data,'business_doctype':source.get('business_doctype'),'business_name':source.get('business_name')}
    digest=hashlib.sha256(json.dumps(intent,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    existing=frappe.db.get_value('Relay Message Action',{'request_key':key},['name','payload_hash'],as_dict=True,for_update=True)
    if existing:
        if existing.payload_hash!=digest:raise ValueError('Request key already belongs to different content')
        return messaging.reconcile(existing.name)
    source,channel,context,tool,args,content=prepared(contact,endpoint,kind,data,business_doctype,business_name)
    payload={'tool':tool,'arguments':args,'content':content,'start':intent}
    from relay_core.business_events import outgoing_event
    if outgoing_event.get(): payload['business_event'] = outgoing_event.get()
    action=frappe.get_doc({'doctype':'Relay Message Action','request_key':key,'operation':content['kind'] if kind=='whatsapp' else kind,'payload':json.dumps(payload),
                          'payload_hash':digest,'status':'Dispatching','start_contact':contact,'target_channel':channel.name,'preview':messaging.preview(content)[:300]})
    internal_save(action,new=True);frappe.db.commit()
    try:
        _,_,_,fresh_tool,fresh_args,_=prepared(contact,endpoint,kind,data,business_doctype,business_name)
        if fresh_tool!=tool or fresh_args!=args:raise ValueError('Conversation changed before sending')
        messaging.automation_scope(action, source)
    except (frappe.PermissionError,frappe.ValidationError,ValueError):
        action.status='Rejected';internal_save(action);frappe.db.commit()
        return {'action':action.name,'status':'Rejected','message':None}
    try:result=whatsapp.client().call_tool(tool,dict(args,request_key=key))
    except Exception as exc:
        return messaging.record_submission_error(action, exc)
    return messaging.finish(action,source,channel,context,content,result)


def action_target(doc):
    payload=messaging.object_value(doc.payload)
    if payload.get('routing'):
        from relay_core.business_routing_prompt import target as prompt_target
        return prompt_target(doc)
    if payload.get('group'):
        from relay_core.telegram_delivery import target as group_target
        return group_target(doc)
    intent=payload.get('start') or {}
    if intent.get('contact')!=doc.start_contact:raise ValueError('Invalid conversation action')
    source,channel,context=target(doc.start_contact,intent.get('endpoint'),intent.get('business_doctype'),intent.get('business_name'))
    if source.sender_endpoint!=intent.get('destination') or channel.name!=intent.get('channel'):
        frappe.throw('Conversation endpoint changed',frappe.PermissionError)
    if doc.operation == 'reaction':
        from relay_core.message_updates import provider_key
        source.name = frappe.db.get_value('Relay Message', {'provider_message_key':provider_key(channel.name, source.sender_endpoint, payload['arguments'].get('reply_to'))}, 'name')
        if not source.name: raise ValueError('Reaction target is unavailable')
        source = frappe.get_doc('Relay Message', source.name); source.check_permission('read')
    return source,channel,context


def whatsapp_content(args):
    operation = args['operation']
    if operation == 'messages.send':
        return {'kind': 'text', 'text': text(args.get('body'), 4096, required=True)}
    if operation == 'templates.send':
        return {'kind': 'text', 'text': 'Template: ' + text(args.get('name'), 512, required=True),
                'template': {key: args[key] for key in ('name', 'language', 'components') if key in args}}
    if operation == 'messages.react':
        return {'kind': 'reaction', 'emoji': text(args.get('emoji', ''), 100)}
    if operation == 'messages.location':
        return {'kind': 'location', 'location': messaging.location(args.get('location') or {})}
    if operation == 'messages.contacts':
        return {'kind': 'contact', 'contacts': messaging.contacts(args.get('contacts'))}
    kind = {'image': 'photo'}.get(args.get('media_type'), args.get('media_type'))
    if kind not in ('photo', 'video', 'audio', 'document', 'sticker'):
        raise ValueError('Unsupported media type')
    return {'kind': kind, 'caption': text(args.get('caption', ''), 1024),
            'media': {'id': args.get('media_id'), 'url': args.get('media_url'), 'file_name': args.get('filename')}}
