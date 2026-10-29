"""Authenticated typed replies anchored to a readable, verified conversation.

The browser chooses content, never a provider recipient, group or topic. A
durable per-user request key prevents resending after ambiguous HTTP failures.
"""
from contextvars import ContextVar

import base64
import binascii
import hashlib
import json
import re
import frappe
from relay_core.business_access import document_name
from relay_core import ai_features
from relay_core.settings import value as connection_value
from relay_core import channels, timeline, whatsapp
from relay_core.api import validate_reference
from relay_core.automation.provenance import context_of, integer, conversation_key
from relay_core.automation.service import internal_save, outgoing_run
from relay_core.hub import HubError
from relay_core.test_mode import TestModeBlocked
from relay_core.hub_channels import hub_arguments, is_current
from relay_core.message_types import contacts, location, normalize, preview, text, telegram_vcard
from relay_core.message_updates import provider_key
from relay_core.permissions import require_access, readable_contact


outgoing_flow = ContextVar('relay_outgoing_flow', default=None)


class DeliverySuppressed(ValueError):
    """The intent remains auditable, but must never be newly admitted to Hub."""


def automatic_delivery(payload):
    return bool(any(payload.get(key) for key in
        ('automation_run', 'flow_run', 'business_event', 'notification', 'routing'))
        or str(payload.get('email_values', {}).get('auto_submitted', 0)) == '1')


def delivery_episodes(source, context):
    """Lock Relay ownership only; callers retain these locks through admission.

    A standalone email has no thread yet, so any held thread in this business
    blocks it. Anchored replies and Telegram topics retain their exact scope.
    """
    company = frappe.db.get_value('Relay Channel', source.channel, 'company')
    if not company:
        return []  # Legacy channels cannot admit new AI episodes.
    from relay_core.tickets import _lock_episode_routing
    conversation = source.get('conversation_key') or conversation_key(source.channel, source.sender_endpoint, context)
    _lock_episode_routing(source, conversation)
    filters = dict(company=company)
    if source.get('business_name'):
        filters.update(business_doctype=source.business_doctype, business_name=source.business_name)
    if source.get('name') or source.get('conversation_key') or context.get('provider') != 'Email':
        filters['conversation_key'] = conversation
    else:
        conversations = frappe.qb.get_query('Relay Business Routing', filters=dict(channel=source.channel,
            relay_contact=source.relay_contact, endpoint=source.sender_endpoint),
            fields=['conversation_key'], limit=101, for_update=True).run(pluck=True)
        if len(conversations) > 100:
            raise DeliverySuppressed('Too many email threads to authorize delivery')
        filters['conversation_key'] = ['in', conversations or [conversation]]
    names = frappe.qb.get_query('Relay Ticket', filters=filters,
        or_filters=[['active_scope_key', 'is', 'set'],
                    ['source_hub_event', 'is', 'set']], fields=['name'],
        order_by='name', limit=101, for_update=True).run(pluck=True)
    if len(names) > 100:
        raise DeliverySuppressed('Too many active episodes to authorize delivery')
    if source.get('ticket') and source.ticket not in names:
        names.append(source.ticket)
    rows = [frappe.get_doc('Relay Ticket', name, for_update=True) for name in sorted(names)]
    return [row for row in rows if row.active_scope_key or row.name == source.get('ticket')
            or row.ai_disabled and row.get('ownership_actor')
                and row.get('source_hub_event') and not row.get('business_name')]


def delivery_snapshot(payload, source, context):
    if source.get('ticket'):
        payload['ticket'] = source.ticket
    if payload.get('business_event'):
        event = frappe.get_doc('Relay Business Event Delivery', payload['business_event'])
        snapshot = object_value(event.payload)
        if 'delivery_episodes' in snapshot:
            payload['delivery_episodes'] = snapshot['delivery_episodes']
            if len(snapshot['delivery_episodes']) == 1 and context.get('provider') != 'Email':
                payload['ticket'] = snapshot['delivery_episodes'][0][0]
        return
    if automatic_delivery(payload):
        payload['delivery_episodes'] = [[row.name, int(row.generation or 0)]
                                      for row in delivery_episodes(source, context)]


def delivery_fence(action, source, context):
    payload = object_value(action.payload)
    # Lifecycle notices are not AI work. Keep their automatic provenance for
    # retry/ownership checks, but staff takeover must not suppress the notice.
    if payload.get('business_event') and not (payload.get('automation_run') or payload.get('flow_run')):
        return
    if not automatic_delivery(payload):
        return
    if payload.get('handoff_notice'):
        from relay_core.ai.handoff import authorize_notice
        authorize_notice(action, source)
        return
    rows = delivery_episodes(source, context)
    current = [[row.name, int(row.generation or 0)] for row in rows]
    expected = payload.get('delivery_episodes')
    # Fixed email rules may still have an inbound queue marker but no action yet.
    # Resume admits new messages only, never old pending replies.
    from frappe.utils import get_datetime
    stale_source = source.get('creation') and any(row.get('ownership_at')
        and get_datetime(source.creation) <= get_datetime(row.ownership_at) for row in rows)
    if (stale_source or any(row.ai_disabled or not row.active_scope_key for row in rows)
            or expected is not None and expected != current
            or expected is None and any(row.generation for row in rows)):
        raise DeliverySuppressed('Automatic delivery stopped by episode ownership')


def suppress_delivery(action):
    # Accepted/uncertain deliveries remain transport-owned; never pretend to cancel.
    frappe.db.get_value('Relay Message Action', action.name, 'name', for_update=True)
    action.reload()
    if action.status == 'Dispatching':
        action.status = 'Rejected'
        action.result = json.dumps({'suppressed': True, 'reason': 'Episode ownership changed'})
        internal_save(action)
    frappe.db.commit()
    return action_result(action)


def object_value(value):
    if isinstance(value, str): value = json.loads(value)
    if not isinstance(value, dict): raise ValueError('Expected an object')
    return value


def readable_message(name):
    """A message and its channel that the user may read, whether or not the channel can send now."""
    require_access()
    validate_reference(name, 'MSG')
    source = frappe.get_doc('Relay Message', name); source.check_permission('read')
    readable_contact(source.relay_contact)
    channel = frappe.get_doc('Relay Channel', source.channel); channel.check_permission('read')
    return source, channel


def readable_source(name):
    source, channel = readable_message(name)
    if not is_current(channel, connection_value('relay_hub_account')):
        frappe.throw('Conversation channel is disabled or belongs to another account', frappe.PermissionError)
    require_binding(source)
    return source, channel, context_of(source)


def require_binding(source):
    key = hashlib.sha256((source.channel + ':' + (source.sender_endpoint or '')).encode()).hexdigest()
    if frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': key, 'verified': 1}, 'relay_contact') != source.relay_contact:
        frappe.throw('Conversation binding is missing or revoked', frappe.PermissionError)


def prepare_choices(source, channel, context, data):
    from relay_core.flows.contracts import choice_options
    if channel.channel != 'WhatsApp' or context.get('provider') != 'WhatsApp':
        raise ValueError('Interactive choices require WhatsApp')
    if set(data) - {'body', 'choices', 'button'}:
        raise ValueError('Invalid interactive choices')
    body = text(data.get('body'), 1024, required=True)
    choices = choice_options(data.get('choices'))
    if len(choices) > 10:
        raise ValueError('Interactive choices support at most 10 options')
    buttons = len(choices) <= 3
    if any(len(row['label']) > (20 if buttons else 24) for row in choices):
        raise ValueError('Interactive choice labels are too long')
    if buttons:
        action = {'buttons': [{'type': 'reply', 'reply': {'id': row['value'], 'title': row['label']}} for row in choices]}
    else:
        action = {'button': text(data.get('button') or 'Choose', 20, required=True),
                  'sections': [{'rows': [{'id': row['value'], 'title': row['label']} for row in choices]}]}
    interactive = {'type': 'button' if buttons else 'list', 'body': {'text': body}, 'action': action}
    arguments = {'operation': 'messages.interactive', 'to': source.sender_endpoint, 'interactive': interactive,
                 'reply_to': text(context.get('message_id') or source.provider_id or '', 300)}
    return 'whatsapp.execute', arguments, {'kind': 'text', 'text': body, 'choices': choices}


def _prepare(source, channel, context, kind, data):
    if kind=='choices':
        return prepare_choices(source, channel, context, data)
    if kind=='flow':
        if channel.channel!='WhatsApp' or context.get('provider')!='WhatsApp' or context.get('group_id'):raise ValueError('Forms require a private WhatsApp conversation')
        if set(data)-{'id','body','cta','screen','token','initial_data'}:raise ValueError('Invalid form arguments')
        identifier=text(data.get('id'),30,required=True)
        if not identifier.isascii() or not identifier.isdigit():raise ValueError('Invalid form ID')
        body=text(data.get('body'),1024,required=True);cta=text(data.get('cta'),20,required=True)
        screen=text(data.get('screen'),200,required=True);token=text(data.get('token'),200,required=True)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',screen) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',token):raise ValueError('Invalid form screen or token')
        initial=data.get('initial_data') or {}
        if not isinstance(initial,dict) or len(json.dumps(initial).encode())>12000:raise ValueError('Form initial values must be an object up to 12000 bytes')
        args={'operation':'messages.flow','to':source.sender_endpoint,'id':identifier,'body':body,'flow_cta':cta,'flow_screen':screen,'flow_token':token,'flow_data':initial,
              'reply_to':text(context.get('message_id') or source.provider_id or '',300)}
        return 'whatsapp.execute',args,{'kind':'text','text':body,'form_name':cta,'flow':dict(data)}
    if kind in ('photo','video','audio','voice','document'):
        from relay_core.attachments import file_content
        if channel.channel not in ('Telegram','WhatsApp') or set(data)-{'attachment','caption'}:
            raise ValueError('Attachment sending requires a supported channel and private attachment')
        file,raw=file_content(data.get('attachment'),source)
        caption=text(data.get('caption',''),1024)
        content={'kind':kind,'caption':caption,'attachment':file.name,'attachment_source':source.name,'media':{'file_name':file.file_name,'file_size':len(raw)}}
        if channel.channel=='WhatsApp':
            import mimetypes
            group=context.get('group_id')
            if context.get('provider')!='WhatsApp' or group and group!=source.sender_endpoint:
                raise ValueError('WhatsApp conversation provenance is required')
            if kind in ('audio','voice') and caption:raise ValueError('WhatsApp audio does not support captions')
            media_type='image' if kind=='photo' else 'audio' if kind=='voice' else kind
            mime=mimetypes.guess_type(file.file_name)[0] or 'application/octet-stream'
            if mime not in channels.channel('WhatsApp').features['media'][kind]:raise ValueError('Choose a supported WhatsApp attachment format')
            args={'operation':'messages.media','to':source.sender_endpoint,
                  'reply_to':text(context.get('message_id') or source.provider_id or '',300),
                  'media_type':media_type,'content_base64':base64.b64encode(raw).decode(),
                  'mime_type':mime}
            if caption:args['caption']=caption
            if kind=='document':args['filename']=file.file_name
            return 'whatsapp.execute',args,content
        if context.get('provider')!='Telegram' or str(context.get('chat_id'))!=source.sender_endpoint:
            raise ValueError('Telegram conversation provenance is required')
        args={'operation':kind,'chat_id':integer(context['chat_id']),
              'reply_to':integer(context.get('message_id'),positive=True),
              'filename':file.file_name,'content_base64':base64.b64encode(raw).decode(),
              'caption':caption}
        if context.get('message_thread_id'):args['message_thread_id']=integer(context['message_thread_id'],positive=True)
        return 'telegram.message',args,content
    if kind not in ('text', 'sticker', 'reaction', 'location', 'contact'):
        raise ValueError('Unsupported message type')
    allowed = {'text': {'text'}, 'sticker': {'file_id', 'sticker_message'}, 'reaction': {'emoji'},
               'location': {'latitude', 'longitude', 'name', 'address'}, 'contact': {'contacts'}}[kind]
    if set(data) - allowed: raise ValueError('Unexpected message arguments')
    group = context.get('group_id')
    if channel.channel not in ('Telegram', 'WhatsApp'):
        raise ValueError('This channel does not support these message controls')
    if kind == 'text': content = {'kind': kind, 'text': text(data.get('text'), 4096, required=True)}
    elif kind == 'sticker':
        original = source
        if data.get('sticker_message'):
            original, original_channel, _ = readable_source(data['sticker_message'])
            if original_channel.name != channel.name or original.relay_contact != source.relay_contact:
                raise ValueError('Sticker source must belong to this contact and channel')
        original_data = object_value(original.message_data or {})
        # Outgoing copies retain their known incoming source for safe reuse.
        if original.direction == 'Outgoing' and original_data.get('sticker_source'):
            original, original_channel, _ = readable_source(original_data['sticker_source'])
            if original_channel.name != channel.name or original.relay_contact != source.relay_contact:
                raise ValueError('Sticker source is not permitted')
            original_data = object_value(original.message_data or {})
        media = original_data.get('media') or {}
        file_id = media.get('file_id' if channel.channel == 'Telegram' else 'id')
        if original.direction != 'Incoming' or original.message_type != 'sticker' or not isinstance(file_id, str) or not file_id:
            raise ValueError('Select a readable incoming sticker from this contact and channel')
        if data.get('file_id') and data['file_id'] != file_id:
            raise ValueError('Sticker file reference does not match its source message')
        content = {'kind': kind, 'media': media, 'sticker_source': original.name}
    elif kind == 'location': content = {'kind': kind, 'location': location(data)}
    elif kind == 'contact': content = {'kind': kind, 'contacts': contacts(data.get('contacts'))}
    else: content = {'kind': kind, 'emoji': text(data.get('emoji', ''), 100)}
    if channel.channel == 'Telegram':
        if context.get('provider') != 'Telegram' or str(context.get('chat_id')) != source.sender_endpoint:
            raise ValueError('Telegram conversation provenance is required')
        args = {'operation': kind, 'chat_id': integer(context['chat_id'])}
        target = integer(context.get('message_id'), positive=True)
        if kind == 'reaction':
            args.update(message_id=target, reaction=[{'type': 'emoji', 'emoji': content['emoji']}] if content['emoji'] else [])
        else:
            args['reply_to'] = target
            if context.get('message_thread_id'): args['message_thread_id'] = integer(context['message_thread_id'], positive=True)
            if kind == 'text': args['text'] = content['text']
            elif kind == 'sticker': args['sticker'] = content['media']['file_id']
            elif kind == 'location': args.update({k: content['location'][k] for k in ('latitude', 'longitude')})
            elif kind == 'contact':
                if len(content['contacts']) != 1: raise ValueError('Telegram sends one contact card at a time')
                card = content['contacts'][0]; phones = card.get('phones') or []
                if not phones or not phones[0].get('phone'): raise ValueError('Telegram contact card requires a phone number')
                first = card['name'].get('first_name') or card['name']['formatted_name']; last = card['name'].get('last_name', '')
                if not re.fullmatch(r'[+0-9 ()-]{1,32}', phones[0]['phone']) or any(len(name) > 64 or any(ord(c) < 32 for c in name) for name in (first, last)):
                    raise ValueError('Invalid Telegram contact phone or name')
                args.update(phone_number=phones[0]['phone'], first_name=first, last_name=last, vcard=telegram_vcard(card))
        return 'telegram.message', args, content
    if context.get('provider') != 'WhatsApp' or group and group != source.sender_endpoint:
        raise ValueError('WhatsApp conversation provenance is required')
    target = text(context.get('message_id') or source.provider_id or '', 300)
    if kind == 'reaction' and not target:
        raise ValueError('This message has no WhatsApp message ID to react to')
    args = {'operation': 'messages.send', 'to': source.sender_endpoint, 'reply_to': target}
    if kind == 'text': args['body'] = content['text']
    elif kind == 'sticker': args.update(operation='messages.media', media_type='sticker', media_id=content['media']['id'])
    elif kind == 'reaction': args.update(operation='messages.react', emoji=content['emoji'])
    elif kind == 'location': args.update(operation='messages.location', location=content['location'])
    elif kind == 'contact': args.update(operation='messages.contacts', contacts=content['contacts'])
    return 'whatsapp.execute', args, content


def prepare(source, channel, context, kind, data, quote=True):
    if channel.channel == 'WhatsApp' and context.get('group_id'):
        raise ValueError('WhatsApp group sending is unavailable in v1')
    tool, arguments, content = _prepare(source, channel, context, kind, data)
    # Without a provider message ID (some imported history) the reply goes without a quote.
    if (not quote or not arguments.get('reply_to')) and kind != 'reaction':
        arguments.pop('reply_to', None)
    return tool, arguments, content


@frappe.whitelist(methods=['POST'])
def send(message, kind, data, request_key, quote=1, channels=None, via=None):
    """`channels` names more Relay Channels of the same person; all copies share one send_group.

    Extra copies never quote: the quoted message exists only on the source channel. `via` picks the
    sending channel: empty keeps the source's channel, `auto` uses the reply channel at send time,
    and a channel name is the staff's own pick.
    """
    original = message
    message, quote = reply_source(message, kind, request_key, via, quote)
    if message != original and kind in MEDIA_SENDS:
        data = rebind_attachment(data, original, message)
    group = request_hash(request_key)[:32]
    sources = channel_sources(message, kind, channels, request_key)
    if not sources:
        return send_one(message, kind, data, request_key, quote)
    results = [send_one(message, kind, data, request_key, quote, group)]
    for key, name in sources:
        results.append(send_one(name, kind, data, key, 0, group))
    return dict(results[0], send_group=group, sends=results)


def channel_sources(message, kind, names, request_key):
    """(request key, source message) for each extra enabled channel of the same person.

    The key comes from the channel, and a retry reuses the source of its first try, so a newer
    incoming message on that channel cannot make the same request send twice.
    """
    names = frappe.parse_json(names) if isinstance(names, str) else names or []
    if (not isinstance(names, list) or len(names) > 3 or not all(isinstance(name, str) for name in names)
            or len(set(names)) != len(names)):
        raise ValueError('Choose up to 3 different channels')
    if not names:
        return []
    source = readable_source(message)[0]
    names = [name for name in names if name != source.channel]
    if names and kind not in ('text', 'location', 'contact'):
        raise ValueError('Only text, location and contact messages can go to several channels')
    enabled = {item.name for item in channels.enabled()}
    sources = []
    for name in names:
        validate_reference(name, 'CH')
        if frappe.db.get_value('Relay Channel', name, 'channel') not in enabled:
            raise ValueError('This channel is switched off')
        key = hashlib.sha256((request_key + ':' + name).encode()).hexdigest()[:40]
        newest = (frappe.db.get_value('Relay Message Action', {'request_key': request_hash(key)}, 'source_message')
            or (timeline.newest({'relay_contact': source.relay_contact, 'channel': name}) or {}).get('name'))
        if not newest:
            raise ValueError('This person has no conversation on the chosen channel')
        sources.append((key, newest))
    return sources


SWITCHABLE = ('text', 'location', 'contact')  # Kinds that do not point at one message on the source channel.
MEDIA_SENDS = ('photo', 'video', 'audio', 'voice', 'document')


def reply_source(message, kind, request_key, via, quote):
    """(source message, quote) on the sending channel; a retry keeps the source of its first try.

    Another channel gets the person's newest message there as its source and never quotes."""
    if not via:
        return message, quote
    source = readable_source(message)[0]
    first = frappe.db.get_value('Relay Message Action', {'request_key': request_hash(request_key)}, 'source_message')
    if first:
        return first, quote if first == message else 0
    target = reply_channel(source.relay_contact)['channel'] if via == 'auto' else via
    if target == source.channel:
        return message, quote
    if kind not in SWITCHABLE + MEDIA_SENDS:
        raise ValueError('Only text, media, location and contact messages can go from another channel')
    validate_reference(target, 'CH')
    newest = (timeline.newest({'relay_contact': source.relay_contact, 'channel': target}) or {}).get('name')
    if not newest:
        raise ValueError('This person has no conversation on the chosen channel')
    return newest, 0


def rebind_attachment(data, original, target):
    """The send data with its attachment copied onto the source message of the sending channel.

    The composer uploads to the message it shows; a retry reuses the copy made on the first try."""
    from frappe.utils.file_manager import save_file
    from relay_core.attachments import file_content
    data = object_value(data)
    file, raw = file_content(data.get('attachment'), readable_source(original)[0])
    copy = frappe.db.get_value('File', {'attached_to_doctype': 'Relay Message', 'attached_to_name': target, 'is_private': 1,
                                        'file_name': file.file_name, 'content_hash': file.content_hash}, 'name')
    if not copy:
        copy = save_file(file.file_name, raw, 'Relay Message', target, is_private=1).name
    return dict(data, attachment=copy)


@frappe.whitelist(methods=['GET'])
def reply_channel(contact):
    """Where a reply to this person goes out now, for the composer's "via" label.

    The channel of the person's newest incoming message, else the team or site default of that type."""
    from relay_core.hub_channels import choose, latest_incoming
    readable_contact(contact)
    endpoints = frappe.get_all('Relay Contact Endpoint', filters={'relay_contact': contact, 'verified': 1},
                               pluck='channel', limit_page_length=50)
    rows = frappe.get_all('Relay Channel', fields=['name', 'channel'], filters={
        'name': ['in', endpoints], 'enabled': 1, 'account': connection_value('relay_hub_account')}) if endpoints else []
    name = latest_incoming(contact, [row.name for row in rows])
    if not name and rows:
        medium = rows[0].channel
        name = choose(medium, [row.name for row in rows if row.channel == medium], contact)
    if not name:
        return {'channel': None}
    doc = frappe.get_doc('Relay Channel', name)
    doc.check_permission('read')
    return {'channel': doc.name, 'provider': doc.channel, 'label': doc.label or doc.title, 'address': doc.address}


@frappe.whitelist(methods=['GET'])
def send_numbers(contact):
    """The site's WhatsApp numbers for the composer's "Send via" picker on a site with several numbers.

    Each number says whether the person has a chat there and its reply window. The default is the number of
    the person's newest incoming WhatsApp message, else the team or site default, the same as a reply."""
    from relay_core.hub_channels import choose, latest_incoming, site_numbers
    from relay_core.service_window import status
    require_access()
    readable_contact(contact)
    numbers = site_numbers('WhatsApp')
    names = [row['name'] for row in numbers]
    items = []
    for row in numbers:
        has_chat = bool(frappe.db.exists('Relay Message', {'relay_contact': contact, 'channel': row['name']}))
        window = status(contact, row['name']) if has_chat else {'open': False, 'expires_at': None, 'remaining_seconds': 0}
        items.append({'channel': row['name'], 'label': row['label'], 'address': row['address'], 'has_chat': has_chat, 'window': window})
    default = latest_incoming(contact, names)
    if not default and names:
        try:
            default = choose('WhatsApp', names, contact)
        except frappe.ValidationError:
            default = None
    return {'default': default, 'items': items}

def request_hash(request_key):
    if not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', request_key):
        raise ValueError('A stable request key is required')
    return hashlib.sha256((frappe.session.user + ':' + request_key).encode()).hexdigest()


def send_one(message, kind, data, request_key, quote=1, send_group=None):
    source, channel, context = readable_source(message)
    data = object_value(data)
    if quote not in (True, False, 0, 1, "0", "1"):
        raise ValueError("Invalid quoted reply option")
    quote = quote in (True, 1, "1")
    key = request_hash(request_key)
    tool, arguments, content = prepare(source, channel, context, kind, data, quote)
    payload = {'tool': tool, 'arguments': arguments, 'source': source.name, 'content': content,
        'business': [source.get('business_doctype'),source.get('business_name')], 'automation_run':outgoing_run.get(), 'flow_run': outgoing_flow.get()}
    from relay_core.ai.handoff import outgoing_notice
    if outgoing_notice.get(): payload['handoff_notice'] = True
    if send_group: payload['send_group'] = send_group
    delivery_snapshot(payload, source, context)
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(json.dumps({'tool':tool,'arguments':arguments,'source':source.name}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    existing = frappe.db.get_value('Relay Message Action', {'request_key': key}, ['name', 'payload_hash', 'status', 'outbound_message'], as_dict=True, for_update=True)
    if existing:
        if existing.payload_hash != digest: raise ValueError('Request key was already used for different content')
        return reconcile(existing.name)
    require_reply_window(source,channel,context)
    action = frappe.get_doc({'doctype': 'Relay Message Action', 'request_key': key, 'source_message': source.name,
        'operation': kind, 'preview':preview(content)[:300], 'target_channel':channel.name, 'payload': encoded, 'payload_hash': digest, 'status': 'Dispatching'})
    if not outgoing_run.get() and not outgoing_flow.get():
        from relay_core.tickets import manual_takeover
        manual_takeover(source)
        if source.get('ticket'):
            payload['ticket'] = source.ticket
            action.payload = json.dumps(payload)
    internal_save(action, new=True); frappe.db.commit()
    try:
        fresh_source, fresh_channel, fresh_context = readable_source(message)
        require_reply_window(fresh_source,fresh_channel,fresh_context)
        fresh_tool, fresh_arguments, _ = prepare(fresh_source, fresh_channel, fresh_context, kind, data, quote)
        if ([fresh_source.get('business_doctype'),fresh_source.get('business_name')]
                != [source.get('business_doctype'),source.get('business_name')]):
            raise ValueError('Message business changed before sending')
        if fresh_tool != tool or fresh_arguments != arguments:
            raise ValueError('Conversation changed before sending')
        delivery_fence(action, fresh_source, fresh_context)
        if outgoing_flow.get():
            automation_scope(action, fresh_source, recovery=False)
        if outgoing_run.get():
            automation_scope(action, fresh_source, recovery=False)
    except DeliverySuppressed:
        return suppress_delivery(action)
    except (ValueError, frappe.ValidationError, frappe.PermissionError, frappe.DoesNotExistError):
        action.reload(); action.status = 'Rejected'; internal_save(action); frappe.db.commit()
        return {'action': action.name, 'status': action.status, 'message': None}
    try:
        # Do not infer destinations from a model or from caller-supplied data.
        result = whatsapp.client().call_tool(tool, hub_arguments(channel, dict(arguments, request_key=key)))
    except Exception as exc:
        return record_submission_error(action, exc)
    return finish(action, source, channel, context, content, result)


def action_target(action):
    if action.operation == 'email':
        from relay_core.email import target
        return target(action)
    if action.get('start_contact'):
        from relay_core.conversation_start import action_target as start_target
        return start_target(action)
    return readable_source(action.source_message)


def action_result(action):
    result = {'action': action.name, 'status': action.status, 'message': action.outbound_message}
    error = action_error(action)
    if error: result['error'] = error
    return result


def receipt_status(receipt):
    delivery = receipt.get('delivery')
    state = delivery.get('state') if isinstance(delivery, dict) else receipt.get('state')
    if state in ('queued', 'submitting', 'dispatching'):
        return 'Queued'
    if state in ('rejected', 'cancelled'):
        return 'Rejected'
    if state == 'uncertain' or receipt.get('pending') is True:
        return 'Uncertain'
    return None


def stale_receipt(action, receipt, *, accepted=False):
    if action.status == 'Submitted': return True
    previous = object_value(action.result or {}).get('_relay_status_id', 0)
    incoming = receipt.get('_relay_status_id', 0)
    if incoming: return bool(previous and previous >= incoming)
    return bool(previous and not accepted)


def delivery_receipt(action, channel):
    tool = 'whatsapp.deliveries' if channel.channel == 'WhatsApp' else 'channels.deliveries'
    result = whatsapp.client().call_tool(tool, hub_arguments(channel, {'request_key': action.request_key}))
    rows = result.get('deliveries')
    if not isinstance(rows, list): raise ValueError('Invalid delivery lookup')
    if not rows: return None
    if len(rows) != 1 or rows[0].get('key') != action.request_key:
        raise ValueError('Delivery receipt is unavailable')
    row = rows[0]
    operation = {'Telegram': 'telegram.message', 'Email': 'email.send'}.get(channel.channel)
    if operation and row.get('operation') != operation:
        raise ValueError('Delivery receipt belongs to another channel')
    receipt = row.get('result') if row.get('state') == 'submitted' else {'delivery': row}
    if not isinstance(receipt, dict): raise ValueError('Invalid delivery receipt')
    return receipt


def admission_scope(action):
    from relay_core.ticket_notifications import authorize_action
    authorize_action(action)
    source, channel, context = action_target(action)
    payload = object_value(action.payload)
    business = payload.get('business') or []
    if any(business) and (not all(business) or business != [source.get('business_doctype'), source.get('business_name')]):
        raise ValueError('Message business changed before recovery')
    delivery_fence(action, source, context)
    automation_scope(action, source)
    return source, channel, context


def automation_scope(action, source, *, recovery=True):
    payload = object_value(action.payload)
    if payload.get('handoff_notice'):
        from relay_core.ai.handoff import authorize_notice
        authorize_notice(action, source)
        return
    if payload.get('flow_run'):
        from relay_core.flows.service import scope as flow_scope
        marker = payload['flow_run']
        run = frappe.get_doc('Relay Flow Run', marker['name'])
        if run.version != marker['version'] or int(run.generation or 0) != marker['generation']:
            raise ValueError('Flow provenance changed')
        actor = frappe.session.user
        try:
            flow_scope(run, source, handoff=marker.get('handoff', False))
        finally:
            frappe.set_user(actor)
    if payload.get('automation_run'):
        from relay_core.automation.service import scope
        run = frappe.get_doc('Relay Automation Run', payload['automation_run'])
        if run.get('stage') == 'Channel':
            from relay_core.automation.channel import delivery_scope as channel_scope
            channel_scope(run, source)
            return
        if not (frappe.conf.get('relay_automation_enabled') and ai_features.is_enabled()): raise ValueError('Automation is disabled')
        if run.get('skill'):
            from relay_core.ai.service import delivery_scope, Superseded
            skill = frappe.get_doc('Relay AI Skill', run.skill)
            try:
                delivery_scope(run, skill, source)
            except Superseded:
                raise
            except Exception:
                if not recovery or json.loads(run.decision or '{}').get('decline'):
                    raise
                from relay_core.ai.handoff import handoff
                handoff(run, skill, 'Reply recovery authorization failed; review required')
                frappe.db.commit()
                raise
        else:
            scope(run, frappe.get_doc('Relay Automation Policy', run.policy))
    if payload.get('business_event'):
        from relay_core.business_events import delivery_scope as event_delivery_scope
        event_delivery_scope(frappe.get_doc('Relay Business Event Delivery', payload['business_event']))


def record_submission_error(action, exc):
    # A pushed receipt may win the race with a timed-out submission response.
    frappe.db.get_value('Relay Message Action', action.name, 'name', for_update=True)
    action.reload()
    if action.status == 'Submitted' or object_value(action.result or {}).get('_relay_status_id'):
        return {'action':action.name,'status':action.status,'message':action.outbound_message}
    known_unsent = isinstance(exc, TestModeBlocked) or isinstance(exc, HubError) and exc.metadata.get('error', {}).get('outcome_unknown') is False
    action.status = 'Rejected' if known_unsent else 'Uncertain'
    action.result = json.dumps(getattr(exc, 'metadata', {}) or {})
    internal_save(action); frappe.db.commit()
    return {'action':action.name,'status':action.status,'message':None,'error':action_error(action)}


def finish(action, source, channel, context, content, result, *, commit=True):
    frappe.db.get_value('Relay Message Action', action.name, 'name', for_update=True)
    action.reload()
    status = receipt_status(result)
    provider_id = result.get('message_id') if channel.channel in ('Telegram', 'Email') else next((row.get('id') for row in result.get('messages', []) if isinstance(row, dict)), None)
    accepted = not status and isinstance(provider_id, (str, int)) and not isinstance(provider_id, bool) and bool(str(provider_id))
    if channel.channel == 'Email':
        from relay_core.automation.provenance import email_message_id
        accepted = accepted and bool(email_message_id(provider_id))
    if action.operation == 'reaction' and channel.channel == 'WhatsApp' and not status:
        accepted = accepted or result.get('success') is True or result.get('manually_reconciled') is True
    if action.operation == 'reaction' and channel.channel == 'Telegram':
        arguments = object_value(action.payload).get('arguments', {})
        accepted = (accepted and result.get('operation') == 'reaction' and result.get('result') is True
            and result.get('chat_id') == arguments.get('chat_id') and provider_id == arguments.get('message_id'))
    if stale_receipt(action, result, accepted=accepted):
        return action_result(action)
    if status or isinstance(result.get('delivery'), dict):
        action.status = status or 'Uncertain'
        action.result = json.dumps(result); internal_save(action)
        if commit: frappe.db.commit()
        return {'action': action.name, 'status': action.status, 'message': None}
    if not accepted and (action.operation != 'reaction' or channel.channel == 'Telegram'):
        action.status = 'Uncertain'; action.result = json.dumps(result); internal_save(action)
        if commit: frappe.db.commit()
        return action_result(action)
    if action.operation == 'reaction':
        frappe.db.get_value('Relay Message', source.name, 'name', for_update=True); source.reload()
        state = object_value(source.reactions or {})
        state['bot'] = [{'type': 'emoji', 'emoji': content['emoji']}] if content['emoji'] else []
        frappe.db.set_value('Relay Message', source.name, 'reactions', json.dumps(state, ensure_ascii=False))
        from relay_core.realtime import changed
        changed(source)
    elif action.operation != 'business_prompt':
        stored = object_value(action.payload)
        business = stored.get('business')
        if not any(business or []):
            from relay_core.business_access import reference
            business = reference(source) or [None, None]
        outgoing_context = dict(context)
        outgoing_context.pop('reply_to_message_id', None)
        reply_to = object_value(action.payload).get('arguments', {}).get('reply_to')
        if reply_to: outgoing_context['reply_to_message_id'] = reply_to
        if provider_id: outgoing_context['message_id'] = provider_id
        if channel.channel == 'WhatsApp':
            from relay_core.whatsapp_receipts import lock_endpoints
            lock_endpoints(source.channel, [source.sender_endpoint])
        outgoing = frappe.get_doc({'doctype': 'Relay Message', 'relay_contact': source.relay_contact,
            'channel': source.channel, 'direction': 'Outgoing', 'status': 'Sent', 'content': preview(content),
            'message_type': content['kind'], 'message_data': json.dumps(content, ensure_ascii=False),
            'sender_endpoint': source.sender_endpoint, 'provider_id': str(provider_id or ''),
            'provider_context': json.dumps(outgoing_context), 'source_key': action.request_key,
            'business_doctype':business[0], 'business_name':business[1],
            'ticket': stored.get('ticket') or source.get('ticket'), 'send_group': stored.get('send_group'),
            'conversation_key': conversation_key(source.channel, source.sender_endpoint, context),
            'provider_message_key': provider_key(source.channel, source.sender_endpoint, provider_id) if provider_id else None})
        from relay_core.ticket_notifications import insert_message
        insert_message(outgoing, action)
        if channel.channel == 'WhatsApp':
            from relay_core.whatsapp_receipts import apply_pending
            apply_pending(outgoing)
        action.outbound_message = outgoing.name
    action.status = 'Submitted'; action.result = json.dumps(result); internal_save(action)
    if commit: frappe.db.commit()
    return {'action': action.name, 'status': action.status, 'message': action.outbound_message}


@frappe.whitelist(methods=['GET'])
def sticker(message):
    if frappe.db.get_value('Relay Message',message,'legacy_source'):
        from relay_core.attachments import archived_attachment
        return archived_attachment(message)
    source, channel, _context = readable_source(message)
    data = object_value(source.message_data or {})
    if source.message_type != 'sticker' or data.get('kind') != 'sticker':
        raise ValueError('This message is not a sticker')
    if source.direction == 'Outgoing':
        original, original_channel, _ = readable_source(data.get('sticker_source'))
        if original.direction != 'Incoming' or original.message_type != 'sticker' or original_channel.name != channel.name or original.relay_contact != source.relay_contact:
            raise ValueError('Sticker source is not permitted')
        data = object_value(original.message_data or {})
    media = data.get('media') or {}; file_id = media.get('file_id') if channel.channel == 'Telegram' else media.get('id')
    if not isinstance(file_id, str) or not file_id: raise ValueError('Sticker file reference is missing')
    result = whatsapp.client().media(channel.channel, file_id, sticker=True, channel=hub_arguments(channel, {}).get('channel'))
    mime = result.get('content_type')
    if mime not in ('image/webp', 'video/webm', 'application/x-tgsticker'): raise ValueError('Unsupported sticker media type')
    try: raw = base64.b64decode(result.get('content_base64', ''), validate=True)
    except (ValueError, binascii.Error, TypeError): raise ValueError('Invalid sticker payload') from None
    if not 1 <= len(raw) <= 2 * 1024 * 1024: raise ValueError('Sticker exceeds media limit')
    valid = (mime == 'image/webp' and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP'
             or mime == 'video/webm' and raw[:4] == b'\x1aE\xdf\xa3'
             or mime == 'application/x-tgsticker' and raw[:2] == b'\x1f\x8b')
    if not valid: raise ValueError('Sticker media does not match its declared type')
    suffix = {'image/webp': 'webp', 'video/webm': 'webm', 'application/x-tgsticker': 'tgs'}[mime]
    from werkzeug.wrappers import Response
    return Response(raw, content_type=mime, headers={'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff', 'Content-Disposition': f'inline; filename="sticker.{suffix}"'})


@frappe.whitelist(methods=['GET'])
def pending_messages(contact=None, before=None, business_doctype=None, business_name=None):
    """Restore the caller's durable, unresolved sends without re-submitting them."""
    require_access()
    business = (business_doctype, business_name) if business_doctype or business_name else None
    if business:
        from relay_core.business_inbox import check_type
        check_type(business_doctype)
        if not isinstance(business_name, str) or not business_name or len(business_name) > 140:
            frappe.throw('Choose a business record')
        from relay_core.business_access import business_document
        business_document(business_doctype, business_name)
    if contact or not business:
        validate_reference(contact, 'CON')
        readable_contact(contact)
    if before:
        validate_reference(before, 'MA')
    from pypika import CustomFunction, Order
    extract = CustomFunction('JSON_EXTRACT', ['document', 'path'])
    action = frappe.qb.DocType('Relay Message Action')
    message = frappe.qb.DocType('Relay Message')
    query = (frappe.qb.from_(action).left_join(message).on(action.source_message == message.name)
        .select(action.name, action.source_message, action.start_contact, action.status,
                action.preview, action.creation, action.target_channel)
        .where((action.owner == frappe.session.user)
               & action.status.isin(['Dispatching', 'Queued', 'Uncertain', 'Rejected'])
               & (action.operation != 'reaction')
               & extract(action.result, '$.dismissed').isnull()))
    if contact:
        query = query.where((message.relay_contact == contact) | (action.start_contact == contact))
    if business:
        unquote = CustomFunction('JSON_UNQUOTE', ['value'])
        snapshot = ((unquote(extract(action.payload, '$.business[0]')) == business_doctype)
                    & (unquote(extract(action.payload, '$.business[1]')) == business_name))
        legacy = (message.business_doctype == business_doctype) & (message.business_name == business_name)
        query = query.where(snapshot | legacy)
    if before:
        query = query.where(action.name < before)
    records = query.orderby(action.name, order=Order.desc).limit(51).run(as_dict=True)
    items = []
    for row in records[:50]:
        try:
            doc = frappe.get_doc('Relay Message Action', row.name)
            doc.check_permission('read')
            source, channel, context = action_target(doc)
            if business and (source.get('business_doctype'), source.get('business_name')) != business:
                continue
        except (frappe.PermissionError, frappe.DoesNotExistError, ValueError):
            continue
        items.append({'name': 'pending:' + row.name, 'action': row.name,
            'contact': source.relay_contact, 'relay_contact': source.relay_contact,
            'frappe_contact': frappe.db.get_value('Relay Contact', source.relay_contact, 'contact'),
            'sender_endpoint': source.sender_endpoint,
            'scope': ':'.join(business) if business else contact, 'channel': channel.name,
            'provider_context': {'provider': channel.channel}, 'direction': 'Outgoing',
            'content': row.preview or 'Outgoing message', 'creation': row.creation, 'error': action_error(doc),
            'status': {'Dispatching': 'Sending', 'Uncertain': 'Unconfirmed',
                       'Rejected': 'Failed'}.get(row.status, row.status), '_pending': True,
            'send_group': object_value(doc.payload).get('send_group')})
        if doc.operation=='email':
            items[-1].update(emailRequest=object_value(doc.payload).get('email_request'),emailSource=row.source_message)
    return {'items': items, 'next': records[49].name if len(records) > 50 else None}


def action_error(doc):
    """Expose a fixed, safe reason from durable authentication failure evidence."""
    result = object_value(doc.result or {})
    if result.get('suppressed'):
        return 'Automatic delivery stopped because staff took over this episode.'
    error = result.get('error')
    if (doc.status == 'Rejected' and result.get('provider') == 'Hub'
            and isinstance(error, dict) and error.get('http_status') in (401, 403)
            and error.get('outcome_unknown') is False):
        return 'Hub rejected this attempt because its credential was not authorized. Verify the Hub connection in Relay Settings before retrying.'
    return None


@frappe.whitelist(methods=['GET'])
def action_snapshots(names):
    """Read local durable results in one batch; never contact Hub or dispatch."""
    require_access()
    names=frappe.parse_json(names) if isinstance(names,str) else names
    if not isinstance(names,list) or len(names)>50:frappe.throw('Refresh at most 50 actions')
    items=[]
    for name in dict.fromkeys(names):
        validate_reference(name,'MA')
        doc=frappe.get_doc('Relay Message Action',name);doc.check_permission('read')
        action_target(doc)
        items.append({'action':name,'status':doc.status,'message':doc.outbound_message,'error':action_error(doc)})
    return {'items':items}


@frappe.whitelist(methods=['POST'])
def reconcile(action):
    document_name(action)
    doc = frappe.get_doc('Relay Message Action', action); doc.check_permission('read')
    source, channel, context = action_target(doc)
    if channel.channel == 'Email' and doc.operation == 'email':
        from relay_core.email import reconcile_action
        return reconcile_action(doc)
    if channel.channel not in ('WhatsApp','Telegram','Email') or doc.status not in ('Dispatching','Queued','Uncertain'):
        return {'action': doc.name, 'status': doc.status, 'message': doc.outbound_message, **({'error': action_error(doc)} if action_error(doc) else {})}
    payload = object_value(doc.payload)
    # Older actions were sent directly and cannot be looked up in the Hub journal.
    if not isinstance(payload.get('content'), dict):
        return {'action': doc.name, 'status': doc.status, 'message': doc.outbound_message, **({'error': action_error(doc)} if action_error(doc) else {})}
    receipt = delivery_receipt(doc, channel)
    if receipt is None and doc.status == 'Dispatching':
        # Only a successful empty lookup proves admission can safely resume.
        try:
            source, channel, context = admission_scope(doc)
        except DeliverySuppressed:
            return suppress_delivery(doc)
        except (ValueError, frappe.PermissionError, frappe.DoesNotExistError):
            if not payload.get('flow_run'): raise
            doc.status = 'Rejected'; internal_save(doc); frappe.db.commit()
            return {'action': doc.name, 'status': doc.status, 'message': None}
        if channel.channel == 'WhatsApp' and context.get('group_id'): raise ValueError('WhatsApp group sending is unavailable in v1')
        if payload.get('routing'):
            from relay_core.business_routing_prompt import prepared as prepare_prompt
            try:
                tool, arguments = prepare_prompt(doc)
            except ValueError:
                doc.status = 'Rejected'; internal_save(doc); frappe.db.commit()
                return {'action': doc.name, 'status': doc.status, 'message': None}
        elif payload.get('group'):
            tool, arguments = payload['tool'], payload['arguments']
        elif doc.get('start_contact'):
            from relay_core.conversation_start import prepared
            intent = payload['start']
            _, _, _, tool, arguments, _ = prepared(intent['contact'], intent['endpoint'], intent['kind'],
                intent['data'], intent.get('business_doctype'), intent.get('business_name'))
        else:
            require_reply_window(source, channel, context)
            tool, arguments = payload['tool'], payload['arguments']
        if tool != payload['tool'] or arguments != payload['arguments']:
            raise ValueError('Conversation changed before recovery')
        try:
            delivery_fence(doc, source, context)
        except DeliverySuppressed:
            return suppress_delivery(doc)
        try:
            receipt = whatsapp.client().call_tool(tool, hub_arguments(channel, dict(arguments, request_key=doc.request_key)))
        except Exception as exc:
            return record_submission_error(doc, exc)
        return finish(doc, source, channel, context, payload['content'], receipt)
    if receipt is None: raise ValueError('Delivery receipt is unavailable')
    return finish(doc, source, channel, context, payload['content'], receipt)


def recovery_candidates():
    # Each state uses the (status, modified, name) index. Merge at most 90
    # candidates instead of sorting the entire unresolved journal in SQL.
    rows = []
    for state in ('Dispatching', 'Queued', 'Uncertain'):
        rows.extend(frappe.get_all('Relay Message Action', filters={'status':state},
            fields=['name','owner','modified'], order_by='modified asc, name asc', limit_page_length=30))
    return sorted(rows, key=lambda row:(row.modified,row.name))[:30]


def recover():
    original = frappe.session.user
    rows = recovery_candidates()
    for row in rows:
        try:
            if not frappe.db.get_value('User',row.owner,'enabled'): continue
            frappe.set_user(row.owner)
            reconcile(row.name)
        except Exception:
            frappe.db.rollback()
        finally:
            frappe.set_user(original)
            # Rotate pending/unavailable actions so a bounded recovery pass cannot starve later rows.
            frappe.db.set_value('Relay Message Action', row.name, 'modified', frappe.utils.now_datetime())
            frappe.db.commit()


def require_reply_window(source, channel, context):
    if channel.channel=='WhatsApp' and not context.get('group_id'):
        from relay_core.service_window import require_open
        require_open(source.relay_contact,channel.name,source.sender_endpoint)


@frappe.whitelist(methods=['GET'])
def reply_window(message):
    """A chat on a disabled channel reads as closed; permission failures still deny."""
    source, channel = readable_message(message)
    if not is_current(channel, connection_value('relay_hub_account')):
        return {'open': False, 'channel_disabled': True}
    require_binding(source)
    if channel.channel!='WhatsApp' or context_of(source).get('group_id'):return {'open':True}
    from relay_core.service_window import status
    return status(source.relay_contact,channel.name,source.sender_endpoint)


@frappe.whitelist(methods=['GET'])
def actions(contact, before=None):
    require_access();readable_contact(contact)
    if before and (not isinstance(before,str) or not re.fullmatch(r'RELAY-MA-[0-9]{10}',before)):
        raise ValueError('Invalid action cursor')
    action=frappe.qb.DocType('Relay Message Action');message=frappe.qb.DocType('Relay Message')
    sources=frappe.qb.from_(message).select(message.name).where(message.relay_contact==contact)
    query=frappe.qb.get_query('Relay Message Action',fields=['name','operation','status','creation','owner','preview','target_channel','outbound_message','source_message','start_contact','result'],ignore_permissions=False,order_by='name desc',limit=21)
    query=query.where((action.start_contact==contact)|action.source_message.isin(sources))
    if before:query=query.where(action.name<before)
    rows=query.run(as_dict=True)
    items=[]
    for row in rows[:20]:
        channel=row.target_channel or frappe.db.get_value('Relay Message',row.source_message or row.outbound_message,'channel')
        if not channel or not frappe.get_doc('Relay Channel',channel).has_permission('read'):continue
        retryable=row.status=='Rejected' and row.owner==frappe.session.user and row.operation!='business_prompt'
        if retryable:
            payload=object_value(frappe.get_doc('Relay Message Action',row.name).payload)
            retryable=not automatic_delivery(payload) and (row.operation!='email' or isinstance(payload.get('email_values'),dict))
        items.append({'name':row.name,'operation':row.operation,'status':row.status,'creation':row.creation,
                      'preview':(row.preview or '')[:300], 'message':row.outbound_message,
                      'can_retry':retryable, 'error':action_error(row)})
    return {'items':items,'before':rows[19].name if len(rows)>20 else None}


def retry_key(action):
    return 'retry-'+hashlib.sha256(action.encode()).hexdigest()


@frappe.whitelist(methods=['POST'])
def retry(action):
    document_name(action)
    require_access()
    doc=frappe.get_doc('Relay Message Action',action);doc.check_permission('read')
    if doc.operation == 'business_prompt':
        frappe.throw('Business prompts are sent once. Assign the business in manager triage.')
    if doc.owner!=frappe.session.user or doc.status!='Rejected':
        frappe.throw('Only the original sender can retry a confirmed rejected action',frappe.PermissionError)
    # One immutable retry identity per rejected action. If it too is rejected,
    # that child is a separate reviewed action with its own retry identity.
    payload=object_value(doc.payload)
    if automatic_delivery(payload):
        frappe.throw('Automated messages cannot be retried from the inbox',frappe.PermissionError)
    result=resend(doc,retry_key(doc.name),payload)
    # The retry stands for this message in the chat from now on, also when it is rejected again.
    hide_pending(doc.name)
    return result


def resend(doc,key,payload):
    if payload.get('group'):
        from relay_core.telegram import send as group_send
        return group_send(**payload['group'],request_key=key)
    if doc.operation == 'email':
        from relay_core.email import send as email_send
        values = payload.get('email_values')
        if not isinstance(values, dict): raise ValueError('This older email cannot be retried; compose a new message')
        return email_send(**values, request_key=key)
    if doc.get('start_contact'):
        from relay_core.conversation_start import send as start_send, action_target as start_target
        start_target(doc)
        intent=payload['start']
        return start_send(intent['contact'],intent['endpoint'],intent['kind'],intent['data'],key,
                          intent.get('business_doctype'),intent.get('business_name'))
    readable_source(doc.source_message)
    content=payload.get('content') or {};kind=doc.operation
    if kind=='text':data={'text':content.get('text')}
    elif kind=='reaction':data={'emoji':content.get('emoji','')}
    elif kind=='location':data=content.get('location')
    elif kind=='contact':data={'contacts':content.get('contacts')}
    elif kind=='sticker':data={'sticker_message':content.get('sticker_source') or doc.source_message}
    elif kind=='flow':data=content.get('flow',{})
    elif kind in ('photo','video','audio','voice','document'):data={'attachment':content.get('attachment'),'caption':content.get('caption','')}
    else:raise ValueError('This older action cannot be retried from the inbox')
    return send(doc.source_message,kind,data,key,quote=bool(payload.get('arguments',{}).get('reply_to')))


@frappe.whitelist(methods=['POST'])
def dismiss(action):
    """Delete a rejected send from the sender's chat. Message activity keeps the record."""
    document_name(action)
    require_access()
    doc=frappe.get_doc('Relay Message Action',action);doc.check_permission('read')
    if doc.owner!=frappe.session.user or doc.status!='Rejected':
        frappe.throw('Only the original sender can delete a message that was not sent',frappe.PermissionError)
    hide_pending(doc.name)
    return {'action':doc.name,'dismissed':1}


def hide_pending(action):
    doc=frappe.get_doc('Relay Message Action',action,for_update=True)
    doc.result=json.dumps(dict(object_value(doc.result or {}),dismissed=1))
    internal_save(doc)


@frappe.whitelist(methods=['GET'])
def canned_replies(message, query='', after=None):
    """Expose only published replies for the readable source's chat medium."""
    source, channel, context = readable_source(message)
    if channel.channel not in ('WhatsApp', 'Telegram'):
        return {'items': []}
    if not isinstance(query, str) or len(query) > 80 or any(ord(c) < 32 for c in query):
        frappe.throw('Invalid reply search')
    reply=frappe.qb.DocType('Relay Canned Reply')
    condition=(reply.published==1)&(reply.channel==channel.channel)
    if context.get('group_id'):
        condition=condition & (reply.reply_type=='Text')
    if query.strip():
        escaped=query.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        condition=condition & reply.title.like('%'+escaped+'%')
    if after:
        try:
            cursor=json.loads(after) if isinstance(after,str) else after
            if not isinstance(cursor,list) or len(cursor)!=2 or any(not isinstance(v,str) or not v or len(v)>140 for v in cursor):raise ValueError()
        except (ValueError,TypeError):frappe.throw('Invalid saved reply cursor')
        condition=condition & ((reply.title>cursor[0]) | ((reply.title==cursor[0]) & (reply.name>cursor[1])))
    rows=(frappe.qb.from_(reply).select(reply.name,reply.title,reply.language,reply.body,reply.reply_type,
        reply.latitude,reply.longitude,reply.contact_name,reply.phone,reply.action_key)
        .where(condition).orderby(reply.title,reply.name).limit(21).run(as_dict=True))
    from relay_core.flows.actions import definitions
    actions=definitions('relay_saved_reply_actions')
    for row in rows[:20]:
        action=actions.get(row.pop('action_key',None))
        row['action_label']=(action.get('label') or 'Run action') if action else None
    return {'items':rows[:20],'next':json.dumps([rows[19].title,rows[19].name]) if len(rows)>20 else None}
