"""Frappe boundary for the account-scoped Hub adapter."""
import re
import frappe
from relay_core.settings import value as connection_value
from relay_core.hub import HubClient, HubError
from relay_core.permissions import require_access, require_business_assignment

READ = {'account.profile','account.metadata','capabilities','templates.list'}
MANAGE = {'templates.media_upload','templates.delete','templates.create','templates.update'}


def configured_business_type(doctype):
    db = getattr(frappe, 'db', None)
    if db is None:  # isolated API contract tests do not provide a database boundary
        return True
    return bool(db.exists('Relay Contact Type', {'business_doctype': doctype, 'enabled': 1}))

SEND = {'messages.media','messages.send','messages.react','messages.location','messages.contacts','templates.send'}


def client():
    # Site config overrides the local development env file. Credentials remain server-side.
    url = connection_value('relay_hub_url')
    token = connection_value('relay_hub_token')
    if url and token:
        return HubClient(url, token)
    raise HubError("Configure relay_hub_url and relay_hub_token for this Frappe site")


@frappe.whitelist(methods=['GET', 'POST'])
def business_contacts(doctype, name, after=None):
    require_access()
    if not isinstance(doctype,str) or not isinstance(name,str) or not doctype or not name or len(doctype)>140 or len(name)>140:
        frappe.throw('Business record is required')
    frappe.get_doc(doctype, name).check_permission('read')
    if not configured_business_type(doctype):
        frappe.throw('Configure this business DocType under Relay Contact Type first')
    filters=[['Dynamic Link','link_doctype','=',doctype],['Dynamic Link','link_name','=',name]]
    if after is not None:
        if not isinstance(after,str) or len(after)>140:frappe.throw('Invalid contact cursor')
        filters.append(['Contact','name','>',after])
    rows=frappe.get_list('Contact',filters=filters,fields=['name','full_name','mobile_no','email_id'],order_by='name asc',page_length=51,distinct=True)
    return {'contacts':rows[:50], 'has_more':len(rows)>50}


def prepare(operation, arguments=None, contact=None, business_doctype=None, business_name=None):
    if not isinstance(operation,str) or operation not in READ | MANAGE | SEND:frappe.throw('Unsupported WhatsApp operation')
    require_access(manage=operation in MANAGE)
    if arguments is None:arguments={}
    if isinstance(arguments,str):arguments=frappe.parse_json(arguments)
    if not isinstance(arguments,dict):frappe.throw('Arguments must be an object')
    allowed={'request_key','id','name','language','category','parameter_format','message_send_ttl_seconds','body','subject','action','sdp','sdp_type','after','components','reply_to','emoji','media_type','media_id','media_url','caption','filename','description','participants','join_requests','expiration_days','join_approval_mode','photo_base64','location','contacts','content_base64','mime_type'}
    if set(arguments)-allowed:frappe.throw('Unsupported operation arguments')
    if {'content_base64','mime_type'}.intersection(arguments):
        if operation not in {'messages.media','templates.media_upload'}:frappe.throw('Uploaded bytes require a media upload operation')
        content = arguments.get('content_base64')
        if not isinstance(content,str) or not 1 <= len(content) <= ((4*1024*1024+2)//3)*4:frappe.throw('Attachment must be at most 4 MiB')
        if arguments.get('media_url') or arguments.get('media_id'):frappe.throw('Choose one media source')
    if 'request_key' in arguments:frappe.throw('Request keys are managed by the message submission endpoint')
    payload={**arguments,'operation':operation}
    if operation in {'messages.media','messages.send','messages.react','messages.location','messages.contacts','templates.send'}:
        if not isinstance(contact,str) or not contact:frappe.throw('Select one contact')
        if not isinstance(business_doctype,str) or not isinstance(business_name,str) or not business_doctype or not business_name:frappe.throw('Select a business record')
        frappe.get_doc(business_doctype,business_name).check_permission('read')
        if not configured_business_type(business_doctype):
            frappe.throw('Configure this business DocType under Relay Contact Type first')
        doc=frappe.get_doc('Contact',contact);doc.check_permission('read')
        require_business_assignment(contact)
        if not any(link.link_doctype==business_doctype and link.link_name==business_name for link in doc.links):frappe.throw('Contact is not linked to this business record')
        number=re.sub(r'[ +()\-]', '', doc.mobile_no or doc.phone or '')
        if not re.fullmatch(r'[0-9]{7,15}',number):frappe.throw('Contact needs a phone number with country code')
        payload['to']=number
    return payload


def checked_client():
    hub=client()
    capabilities=hub.execute({'operation':'capabilities'})
    if str(capabilities.get('site','')).rstrip('/') != frappe.utils.get_url().rstrip('/'):
        frappe.throw('Hub account belongs to another site')
    return hub,capabilities


@frappe.whitelist(methods=['POST'])
def deliveries(after='',cancel_id=None):
    # Account-wide delivery results are manager-only. Sending remains available
    # to users through permission-checked business records and contacts.
    require_access(manage=True)
    if not isinstance(after,str) or (after and not after.isdigit()):frappe.throw('Invalid cursor')
    if cancel_id is not None and (not isinstance(cancel_id,str) or not cancel_id.isdigit()):frappe.throw('Invalid delivery ID')
    try:
        hub,_=checked_client()
        return hub.call_tool('whatsapp.deliveries',{'after':after,'cancel_id':cancel_id or ''})
    except (HubError, ValueError):
        frappe.throw('Could not read or cancel deliveries')


@frappe.whitelist(methods=['POST'])
def execute(operation, arguments=None, contact=None, business_doctype=None, business_name=None, request_key=None):
    if operation in SEND:
        return send(dict(key=request_key, operation=operation, arguments=arguments, contact=contact,
                         business_doctype=business_doctype, business_name=business_name))
    payload=prepare(operation,arguments,contact,business_doctype,business_name)
    try:
        hub=client()
        capabilities=hub.execute({'operation':'capabilities'})
        site_url=frappe.utils.get_url().rstrip('/')
        if str(capabilities.get('site','')).rstrip('/') != site_url:
            frappe.throw('Hub account belongs to another site')
        result=capabilities if operation=='capabilities' else hub.execute(payload)
        if operation == 'templates.list':
            from relay_core.whatsapp_templates import overlay
            result = overlay(result)
        return result
    except (HubError, ValueError):
        frappe.throw('Hub could not complete this operation. Check account configuration, capability and provider status before retrying.')


@frappe.whitelist(methods=['POST'])
def conversation(contact, business_doctype, business_name, after=None, before=None):
    recipient=prepare('messages.send',{'body':'validate recipient'},contact,business_doctype,business_name)['to']
    if before is not None and after is not None:frappe.throw('Use one history cursor')
    for cursor in (before,after):
        if cursor is not None and (not isinstance(cursor,str) or not cursor.isdigit()):frappe.throw('Invalid cursor')
    relay = frappe.db.get_value('Relay Contact', {'contact': contact}, 'name')
    if not relay:
        return {'messages': [], 'first': None, 'next': after or '0', 'has_more': False}
    from relay_core.permissions import readable_contact
    from relay_core.business_access import candidates
    readable_contact(relay)
    channels = frappe.get_list('Relay Channel', filters={'channel': 'WhatsApp',
        'account': connection_value('relay_hub_account')}, pluck='name')
    # Apply both selected ownership and Frappe permissions before pagination.
    filters = {'relay_contact': relay, 'sender_endpoint': recipient, 'channel': ['in', channels]}
    from pypika import Criterion
    query = frappe.qb.get_query('Relay Message', fields=['name', 'provider_id', 'message_type',
        'sent_at', 'creation', 'content', 'provider_context'], filters=filters,
        ignore_permissions=False, order_by='name asc' if after else 'name desc', limit=51)
    table = frappe.qb.DocType('Relay Message')
    ownership = (table.business_doctype == business_doctype) & (table.business_name == business_name)
    if candidates(relay) == [(business_doctype, business_name)]:
        ownership |= Criterion.all([(field.isnull() | (field == '')) for field in
                                    (table.business_doctype, table.business_name)])
    query = query.where(ownership).where(table.legacy_triage.isnull() | (table.legacy_triage == 0))
    if before or after:
        anchor = 'RELAY-MSG-' + (before or after).zfill(10)
        query = query.where(table.name < anchor if before else table.name > anchor)
    rows = query.run(as_dict=True)
    page = rows[:50]
    if not after: page.reverse()
    from relay_core.automation.provenance import context_of
    messages = [{'id': row.provider_id or row.name, 'cursor': row.name.rsplit('-', 1)[-1],
                 'type': row.message_type, 'timestamp': row.sent_at or row.creation,
                 'text': row.content, 'reply_to': context_of(row).get('reply_to_message_id')}
                for row in page]
    return {'messages': messages, 'first': messages[0]['cursor'] if messages else None,
            'next': messages[-1]['cursor'] if messages else after or '0', 'has_more': len(rows) > 50}


@frappe.whitelist(methods=['POST'])
def send(message):
    """Submit one immutable intent through the Core action journal."""
    from relay_core.conversation_start import business_channels, send_business
    if isinstance(message, str): message = frappe.parse_json(message)
    fields = {'key', 'operation', 'arguments', 'contact', 'business_doctype', 'business_name'}
    if not isinstance(message, dict) or set(message) - fields:
        raise ValueError('Invalid message')
    if message.get('operation') not in SEND:
        raise ValueError('Unsupported WhatsApp send')
    key = message.get('key')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', key):
        raise ValueError('A stable request key is required')
    scope = {field: message.get(field) for field in ('contact', 'business_doctype', 'business_name')}
    destination = prepare(message['operation'], message.get('arguments'), **scope)['to']
    from relay_core.identity import normalize
    channels = [row for row in business_channels(**scope) if row['provider'] == 'WhatsApp'
                and normalize('WhatsApp', frappe.get_doc('Relay Contact Endpoint', row['endpoint']).endpoint) == destination]
    if len(channels) != 1:
        raise ValueError('Configure one available WhatsApp channel')
    return send_business(**scope, channel=channels[0]['value'], endpoint=channels[0]['endpoint'], kind='whatsapp',
                         data={'operation': message['operation'], 'arguments': message.get('arguments') or {}},
                         request_key=key)


@frappe.whitelist(methods=['GET'])
def connection():
    require_access()
    channels=frappe.get_list('Relay Channel',filters={'enabled':1,'channel':'WhatsApp','account':connection_value('relay_hub_account')},fields=['name'],page_length=1)
    return {'configured':bool(channels)}


@frappe.whitelist(methods=['GET'])
def metadata_status():
    """Read cached account health; never initiate a provider sync from the UI."""
    from datetime import datetime, timezone, timedelta
    require_access(manage=True)
    try:
        hub, _ = checked_client()
        result = hub.execute({'operation': 'account.metadata'})
    except (HubError, ValueError):
        frappe.throw('Could not read WhatsApp synchronization status')
    status = result.get('status')
    if status not in {'ready', 'failed', 'syncing', 'not_synced'}:
        frappe.throw('Invalid WhatsApp synchronization status')
    last_success = result.get('last_success')
    if status == 'ready':
        try:
            timestamp = datetime.fromisoformat(last_success.replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - timestamp > timedelta(hours=2):
                status = 'stale'
        except (AttributeError, TypeError, ValueError):
            status = 'stale'
    return {'status': status, 'last_attempt': result.get('last_attempt'),
            'last_success': last_success, 'template_count': len(result.get('templates') or []),
            'truncated': bool(result.get('truncated'))}
