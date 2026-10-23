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
from relay_core.hub import HubError


def business_contact(contact, business_doctype, business_name):
    """Resolve one permission-checked Frappe Contact linked to the business."""
    require_access()
    from relay_core.business_inbox import check_type
    check_type(business_doctype)
    business=frappe.get_doc(business_doctype,business_name);business.check_permission('read')
    person=frappe.get_doc('Contact',contact);person.check_permission('read')
    if not any(link.link_doctype==business_doctype and link.link_name==business_name for link in person.links):
        frappe.throw('Contact is not linked to this business',frappe.PermissionError)
    number=re.sub(r'[ +()\-]', '', person.mobile_no or person.phone or '')
    if not re.fullmatch(r'[0-9]{7,15}',number):
        frappe.throw('This contact needs a WhatsApp number with country code')
    return person,number


def business_channels(contact, business_doctype, business_name):
    person,number=business_contact(contact,business_doctype,business_name)
    account=connection_value('relay_hub_account')
    rows=frappe.get_all('Relay Channel',filters={'channel':'WhatsApp','enabled':1,'account':account},fields=['name'],limit_page_length=10)
    relay=frappe.db.get_value('Relay Contact',{'contact':person.name},'name')
    result=[]
    for row in rows:
        channel=frappe.get_doc('Relay Channel',row.name)
        try:channel.check_permission('read')
        except frappe.PermissionError:continue
        endpoint=frappe.db.get_value('Relay Contact Endpoint',{'channel':channel.name,'endpoint':number,'verified':1},'name') if relay else None
        window=service_window.status(relay,channel.name,number) if relay and endpoint else {'open':False,'expires_at':None}
        result.append({'value':channel.name,'label':'WhatsApp · '+number,'provider':'WhatsApp','window':window})
    return result


@frappe.whitelist(methods=['GET'])
def business_options(contact, business_doctype, business_name):
    return business_channels(contact,business_doctype,business_name)


def ensure_business_binding(contact, channel_name, business_doctype, business_name):
    person,number=business_contact(contact,business_doctype,business_name)
    allowed={row['value'] for row in business_channels(contact,business_doctype,business_name)}
    if channel_name not in allowed:frappe.throw('Choose an available WhatsApp channel',frappe.PermissionError)
    relay=frappe.db.get_value('Relay Contact',{'contact':person.name},'name')
    if not relay:
        relay=frappe.get_doc({'doctype':'Relay Contact','contact':person.name,
            'display_name':person.full_name or person.name}).insert(ignore_permissions=True).name
    key=hashlib.sha256((channel_name+':'+number).encode()).hexdigest()
    existing=frappe.db.get_value('Relay Contact Endpoint',{'endpoint_key':key},['name','relay_contact','verified'],as_dict=True)
    if existing:
        if existing.relay_contact!=relay:frappe.throw('This WhatsApp number belongs to another contact')
        if not existing.verified:frappe.throw('This WhatsApp destination was revoked and needs administrator review')
        return relay,existing.name
    previous=getattr(frappe.flags,'relay_business_contact_sync',False);frappe.flags.relay_business_contact_sync=True
    try:
        endpoint=frappe.get_doc({'doctype':'Relay Contact Endpoint','channel':channel_name,
            'endpoint':number,'relay_contact':relay,'verified':1}).insert(ignore_permissions=True)
    finally:frappe.flags.relay_business_contact_sync=previous
    return relay,endpoint.name


@frappe.whitelist(methods=['POST'])
def send_business(contact, channel, kind, data, request_key, business_doctype, business_name):
    relay,endpoint=ensure_business_binding(contact,channel,business_doctype,business_name)
    return send(relay,endpoint,kind,data,request_key,business_doctype,business_name)


def target(contact, endpoint, business_doctype=None, business_name=None):
    require_access();readable_contact(contact)
    binding=frappe.get_doc('Relay Contact Endpoint',endpoint)
    if binding.relay_contact!=contact or not binding.verified:
        frappe.throw('Choose a verified endpoint for this contact',frappe.PermissionError)
    channel=frappe.get_doc('Relay Channel',binding.channel);channel.check_permission('read')
    if not channel.enabled or channel.account!=connection_value('relay_hub_account') or channel.channel!='WhatsApp':
        frappe.throw('The channel is unavailable',frappe.PermissionError)
    if not re.fullmatch(r'[0-9]{1,16}',binding.endpoint or '') or int(binding.endpoint)<=0:
        frappe.throw('Use Groups to start a group conversation')
    context={'provider':'WhatsApp'}
    source=frappe._dict(name=None,relay_contact=contact,channel=channel.name,sender_endpoint=binding.endpoint)
    from relay_core.business_access import candidates
    links=candidates(contact)
    if business_doctype or business_name:
        if (business_doctype,business_name) not in links:frappe.throw('Contact is not linked to this business',frappe.PermissionError)
        frappe.get_doc(business_doctype,business_name).check_permission('read')
        source.business_doctype=business_doctype;source.business_name=business_name
    elif len(links)==1:
        source.business_doctype,source.business_name=links[0]
    else:frappe.throw('Choose the business record for this conversation')
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
    if kind=='whatsapp':
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
    elif kind=='text':
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
    # Repeated attempts look up the original action even if its 24-hour window has elapsed.
    source,channel,context=target(contact,endpoint,business_doctype,business_name)
    data=messaging.object_value(data)
    intent={'contact':contact,'endpoint':endpoint,'destination':source.sender_endpoint,'channel':channel.name,'kind':kind,'data':data,'business_doctype':source.get('business_doctype'),'business_name':source.get('business_name')}
    digest=hashlib.sha256(json.dumps(intent,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    key=hashlib.sha256((frappe.session.user+':'+request_key).encode()).hexdigest()
    existing=frappe.db.get_value('Relay Message Action',{'request_key':key},['name','payload_hash'],as_dict=True)
    if existing:
        if existing.payload_hash!=digest:raise ValueError('Request key already belongs to different content')
        return messaging.reconcile(existing.name)
    source,channel,context,tool,args,content=prepared(contact,endpoint,kind,data,business_doctype,business_name)
    payload={'tool':tool,'arguments':args,'content':content,'start':intent}
    action=frappe.get_doc({'doctype':'Relay Message Action','request_key':key,'operation':content['kind'] if kind=='whatsapp' else kind,'payload':json.dumps(payload),
                          'payload_hash':digest,'status':'Dispatching','start_contact':contact,'target_channel':channel.name,'preview':messaging.preview(content)[:300]})
    internal_save(action,new=True);frappe.db.commit()
    try:
        _,_,_,fresh_tool,fresh_args,_=prepared(contact,endpoint,kind,data,business_doctype,business_name)
        if fresh_tool!=tool or fresh_args!=args:raise ValueError('Conversation changed before sending')
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
