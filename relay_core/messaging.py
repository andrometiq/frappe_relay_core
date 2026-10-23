"""Authenticated typed replies anchored to a readable, verified conversation.

The browser chooses content, never a provider recipient, group or topic. A
durable per-user request key prevents resending after ambiguous HTTP failures.
"""
import base64
import binascii
import hashlib
import json
import re
import frappe
from relay_core.settings import value as connection_value
from relay_core import whatsapp
from relay_core.api import validate_reference
from relay_core.automation.provenance import context_of, integer, conversation_key
from relay_core.automation.service import internal_save, outgoing_run
from relay_core.hub import HubError
from relay_core.message_types import contacts, location, normalize, preview, text, telegram_vcard
from relay_core.message_updates import provider_key
from relay_core.permissions import require_access, readable_contact


def object_value(value):
    if isinstance(value, str): value = json.loads(value)
    if not isinstance(value, dict): raise ValueError('Expected an object')
    return value


def readable_source(name):
    require_access()
    validate_reference(name, 'MSG')
    source = frappe.get_doc('Relay Message', name); source.check_permission('read')
    readable_contact(source.relay_contact)
    channel = frappe.get_doc('Relay Channel', source.channel); channel.check_permission('read')
    if not channel.enabled or channel.account != connection_value('relay_hub_account'):
        frappe.throw('Conversation channel is disabled or belongs to another account', frappe.PermissionError)
    key = hashlib.sha256((source.channel + ':' + (source.sender_endpoint or '')).encode()).hexdigest()
    if frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': key, 'verified': 1}, 'relay_contact') != source.relay_contact:
        frappe.throw('Conversation binding is missing or revoked', frappe.PermissionError)
    return source, channel, context_of(source)


def _prepare(source, channel, context, kind, data):
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
              'reply_to':text(context.get('message_id') or source.provider_id,300,required=True)}
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
            allowed_mimes={'image':{'image/jpeg','image/png'},'video':{'video/mp4'},
                'audio':{'audio/mpeg','audio/mp4','audio/ogg','audio/aac'},
                'document':{'application/pdf','text/plain','application/msword','application/vnd.ms-excel','application/vnd.ms-powerpoint',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/vnd.openxmlformats-officedocument.presentationml.presentation'}}
            if mime not in allowed_mimes.get(media_type,set()):raise ValueError('Choose a supported WhatsApp attachment format')
            args={'operation':'messages.media','to':source.sender_endpoint,
                  'reply_to':text(context.get('message_id') or source.provider_id,300,required=True),
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
    target = text(context.get('message_id') or source.provider_id, 300, required=True)
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
    if not quote and kind != 'reaction':
        arguments.pop('reply_to', None)
    return tool, arguments, content


@frappe.whitelist(methods=['POST'])
def send(message, kind, data, request_key, quote=1):
    source, channel, context = readable_source(message)
    data = object_value(data)
    if quote not in (True, False, 0, 1, "0", "1"):
        raise ValueError("Invalid quoted reply option")
    quote = quote in (True, 1, "1")
    if not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', request_key):
        raise ValueError('A stable request key is required')
    tool, arguments, content = prepare(source, channel, context, kind, data, quote)
    encoded = json.dumps({'tool': tool, 'arguments': arguments, 'source': source.name, 'content': content,
        'business': [source.get('business_doctype'),source.get('business_name')], 'automation_run':outgoing_run.get()}, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(json.dumps({'tool':tool,'arguments':arguments,'source':source.name}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    key = hashlib.sha256((frappe.session.user + ':' + request_key).encode()).hexdigest()
    existing = frappe.db.get_value('Relay Message Action', {'request_key': key}, ['name', 'payload_hash', 'status', 'outbound_message'], as_dict=True, for_update=True)
    if existing:
        if existing.payload_hash != digest: raise ValueError('Request key was already used for different content')
        return reconcile(existing.name)
    require_reply_window(source,channel,context)
    action = frappe.get_doc({'doctype': 'Relay Message Action', 'request_key': key, 'source_message': source.name,
        'operation': kind, 'preview':preview(content)[:300], 'target_channel':channel.name, 'payload': encoded, 'payload_hash': digest, 'status': 'Dispatching'})
    internal_save(action, new=True); frappe.db.commit()
    try:
        fresh_source, fresh_channel, fresh_context = readable_source(message)
        require_reply_window(fresh_source,fresh_channel,fresh_context)
        fresh_tool, fresh_arguments, _ = prepare(fresh_source, fresh_channel, fresh_context, kind, data, quote)
        if fresh_tool != tool or fresh_arguments != arguments:
            raise ValueError('Conversation changed before sending')
        if outgoing_run.get():
            run = frappe.get_doc('Relay Automation Run', outgoing_run.get())
            if not frappe.conf.get('relay_automation_enabled'):
                raise ValueError('Automation is disabled')
            if run.get('skill'):
                from relay_core.ai.service import delivery_scope
                delivery_scope(run, frappe.get_doc('Relay AI Skill', run.skill), fresh_source)
    except (ValueError, frappe.ValidationError, frappe.PermissionError, frappe.DoesNotExistError):
        action.reload(); action.status = 'Rejected'; internal_save(action); frappe.db.commit()
        return {'action': action.name, 'status': action.status, 'message': None}
    try:
        # Do not infer destinations from a model or from caller-supplied data.
        result = whatsapp.client().call_tool(tool, dict(arguments, request_key=key))
    except Exception as exc:
        return record_submission_error(action, exc)
    return finish(action, source, channel, context, content, result)


def record_submission_error(action, exc):
    # A pushed receipt may win the race with a timed-out submission response.
    frappe.db.get_value('Relay Message Action', action.name, 'name', for_update=True)
    action.reload()
    if action.status == 'Submitted' or object_value(action.result or {}).get('_relay_status_id'):
        return {'action':action.name,'status':action.status,'message':action.outbound_message}
    action.status = 'Rejected' if isinstance(exc, HubError) and exc.metadata.get('error', {}).get('outcome_unknown') is False else 'Uncertain'
    action.result = json.dumps(getattr(exc, 'metadata', {}) or {})
    internal_save(action); frappe.db.commit()
    return {'action':action.name,'status':action.status,'message':None,'error':action_error(action)}


def finish(action, source, channel, context, content, result, *, commit=True):
    frappe.db.get_value('Relay Message Action', action.name, 'name', for_update=True)
    action.reload()
    if action.status == 'Submitted':
        return {'action': action.name, 'status': action.status, 'message': action.outbound_message}
    delivery = result.get('delivery')
    if isinstance(delivery, dict):
        state = delivery.get('state')
        action.status = {'queued':'Queued','submitting':'Queued','dispatching':'Queued','rejected':'Rejected','cancelled':'Rejected'}.get(state,'Uncertain')
        action.result = json.dumps(result); internal_save(action)
        if commit: frappe.db.commit()
        return {'action': action.name, 'status': action.status, 'message': None}
    provider_id = result.get('message_id') if channel.channel == 'Telegram' else next((row.get('id') for row in result.get('messages', []) if isinstance(row, dict)), None)
    if action.operation != 'reaction' and (not isinstance(provider_id, (str, int)) or isinstance(provider_id, bool) or not str(provider_id)):
        action.reload(); action.status = 'Uncertain'; action.result = json.dumps(result); internal_save(action)
        if commit: frappe.db.commit()
        return {'action': action.name, 'status': action.status, 'message': None}
    if action.operation == 'reaction' and channel.channel == 'Telegram':
        arguments = object_value(action.payload).get('arguments', {})
        if (result.get('operation') != 'reaction' or result.get('result') is not True
                or result.get('chat_id') != arguments.get('chat_id')
                or result.get('message_id') != arguments.get('message_id')):
            action.status = 'Uncertain'; action.result = json.dumps(result); internal_save(action)
            if commit: frappe.db.commit()
            return {'action': action.name, 'status': action.status, 'message': None}
    if action.operation == 'reaction':
        frappe.db.get_value('Relay Message', source.name, 'name', for_update=True); source.reload()
        state = object_value(source.reactions or {})
        state['bot'] = [{'type': 'emoji', 'emoji': content['emoji']}] if content['emoji'] else []
        frappe.db.set_value('Relay Message', source.name, 'reactions', json.dumps(state, ensure_ascii=False))
        from relay_core.realtime import changed
        changed(source)
    elif action.operation != 'business_prompt':
        stored = object_value(action.payload)
        business = stored.get('business') or [source.get('business_doctype'), source.get('business_name')]
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
            'conversation_key': conversation_key(source.channel, source.sender_endpoint, context),
            'provider_message_key': provider_key(source.channel, source.sender_endpoint, provider_id) if provider_id else None}).insert(ignore_permissions=True)
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
    result = whatsapp.client().media(channel.channel, file_id)
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
def pending_messages(contact, before=None):
    """Restore the caller's durable, unresolved sends without re-submitting them."""
    require_access()
    validate_reference(contact, 'CON')
    readable_contact(contact)
    if before:
        validate_reference(before, 'MA')
    from pypika import Order
    action = frappe.qb.DocType('Relay Message Action')
    message = frappe.qb.DocType('Relay Message')
    query = (frappe.qb.from_(action).left_join(message).on(action.source_message == message.name)
        .select(action.name, action.source_message, action.start_contact, action.status,
                action.preview, action.creation, action.target_channel)
        .where((action.owner == frappe.session.user)
               & action.status.isin(['Dispatching', 'Queued', 'Uncertain', 'Rejected'])
               & (action.operation != 'reaction')
               & ((message.relay_contact == contact) | (action.start_contact == contact))))
    if before:
        query = query.where(action.name < before)
    records = query.orderby(action.name, order=Order.desc).limit(51).run(as_dict=True)
    items = []
    for row in records[:50]:
        try:
            doc = frappe.get_doc('Relay Message Action', row.name)
            doc.check_permission('read')
            if row.start_contact:
                from relay_core.conversation_start import action_target
                source, channel, context = action_target(doc)
            else:
                source, channel, context = readable_source(row.source_message)
        except (frappe.PermissionError, frappe.DoesNotExistError):
            continue
        items.append({'name': 'pending:' + row.name, 'action': row.name,
            'contact': contact, 'scope': contact, 'channel': channel.name,
            'provider_context': {'provider': channel.channel}, 'direction': 'Outgoing',
            'content': row.preview or 'Outgoing message', 'creation': row.creation, 'error': action_error(doc),
            'status': {'Dispatching': 'Sending', 'Uncertain': 'Unconfirmed',
                       'Rejected': 'Failed'}.get(row.status, row.status), '_pending': True})
        if doc.operation=='email':
            items[-1].update(emailRequest=object_value(doc.payload).get('email_request'),emailSource=row.source_message)
    return {'items': items, 'next': records[49].name if len(records) > 50 else None}


def action_error(doc):
    """Expose a fixed, safe reason from durable authentication failure evidence."""
    result = object_value(doc.result or {})
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
        if doc.get('start_contact'):
            from relay_core.conversation_start import action_target
            action_target(doc)
        else:readable_source(doc.source_message)
        items.append({'action':name,'status':doc.status,'message':doc.outbound_message,'error':action_error(doc)})
    return {'items':items}


@frappe.whitelist(methods=['POST'])
def reconcile(action):
    doc = frappe.get_doc('Relay Message Action', action); doc.check_permission('read')
    if doc.get("start_contact"):
        from relay_core.conversation_start import action_target
        source, channel, context = action_target(doc)
    else:
        source, channel, context = readable_source(doc.source_message)
    if channel.channel == 'Email' and doc.operation == 'email':
        from relay_core.email import reconcile_action
        return reconcile_action(doc)
    if channel.channel not in ('WhatsApp','Telegram') or doc.status not in ('Dispatching','Queued','Uncertain'):
        return {'action': doc.name, 'status': doc.status, 'message': doc.outbound_message, **({'error': action_error(doc)} if action_error(doc) else {})}
    payload = object_value(doc.payload)
    # Older actions were sent directly and cannot be looked up in the Hub journal.
    if not isinstance(payload.get('content'), dict):
        return {'action': doc.name, 'status': doc.status, 'message': doc.outbound_message, **({'error': action_error(doc)} if action_error(doc) else {})}
    result = whatsapp.client().call_tool('channels.deliveries' if channel.channel=='Telegram' else 'whatsapp.deliveries', {'request_key': doc.request_key})
    rows = result.get('deliveries')
    if not isinstance(rows, list): raise ValueError('Invalid delivery lookup')
    if rows == [] and doc.status == 'Dispatching' and channel.channel == 'WhatsApp':
        # An authenticated, successful empty lookup proves Hub has no intent.
        # Timeouts, malformed replies and Uncertain actions never enter this path.
        if context.get('group_id'): raise ValueError('WhatsApp group sending is unavailable in v1')
        if payload.get('business') and payload['business'] != [source.get('business_doctype'),source.get('business_name')]:
            raise ValueError('Message business changed before recovery')
        if payload.get('automation_run'):
            from relay_core.automation.service import scope
            run = frappe.get_doc('Relay Automation Run', payload['automation_run'])
            if not frappe.conf.get('relay_automation_enabled'): raise ValueError('Automation is disabled')
            if run.get('skill'):
                from relay_core.ai.service import delivery_scope, Superseded
                skill = frappe.get_doc('Relay AI Skill', run.skill)
                try:
                    delivery_scope(run, skill, source)
                except Superseded:
                    raise
                except Exception:
                    from relay_core.ai.handoff import handoff
                    handoff(run, skill, 'Reply recovery authorization failed; review required')
                    frappe.db.commit()
                    raise
            else:
                scope(run, frappe.get_doc('Relay Automation Policy', run.policy))
        if payload.get('business_event'):
            from relay_core.business_events import delivery_scope as event_delivery_scope
            event_delivery_scope(frappe.get_doc('Relay Business Event Delivery', payload['business_event']))
        if payload.get('routing'):
            from relay_core.business_routing_prompt import prepared as prepare_prompt
            try:
                tool, arguments = prepare_prompt(doc)
            except ValueError:
                doc.status = 'Rejected'; internal_save(doc); frappe.db.commit()
                return {'action': doc.name, 'status': doc.status, 'message': None}
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
            receipt = whatsapp.client().call_tool(tool, dict(arguments, request_key=doc.request_key))
        except Exception as exc:
            return record_submission_error(doc, exc)
        return finish(doc, source, channel, context, payload['content'], receipt)
    if len(rows) != 1 or rows[0].get('key') != doc.request_key:
        raise ValueError('Delivery receipt is unavailable')
    row = rows[0]
    if channel.channel=='Telegram' and row.get('operation')!='telegram.message':raise ValueError('Delivery receipt belongs to another channel')
    receipt = row.get('result') if row.get('state') == 'submitted' else {'delivery': row}
    if not isinstance(receipt, dict): raise ValueError('Invalid delivery receipt')
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
    source,channel,context=readable_source(message)
    if channel.channel!='WhatsApp' or context.get('group_id'):return {'open':True}
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
        if retryable and row.operation=='email':
            retryable=isinstance(object_value(frappe.get_doc('Relay Message Action',row.name).payload).get('email_values'),dict)
        items.append({'name':row.name,'operation':row.operation,'status':row.status,'creation':row.creation,
                      'preview':(row.preview or '')[:300], 'message':row.outbound_message,
                      'can_retry':retryable, 'error':action_error(row)})
    return {'items':items,'before':rows[19].name if len(rows)>20 else None}


def retry_key(action):
    return 'retry-'+hashlib.sha256(action.encode()).hexdigest()


@frappe.whitelist(methods=['POST'])
def retry(action):
    require_access()
    doc=frappe.get_doc('Relay Message Action',action);doc.check_permission('read')
    if doc.operation == 'business_prompt':
        frappe.throw('Business prompts are sent once. Assign the business in manager triage.')
    if doc.owner!=frappe.session.user or doc.status!='Rejected':
        frappe.throw('Only the original sender can retry a confirmed rejected action',frappe.PermissionError)
    # One immutable retry identity per rejected action. If it too is rejected,
    # that child is a separate reviewed action with its own retry identity.
    key=retry_key(doc.name)
    payload=object_value(doc.payload)
    if payload.get('group'):
        from relay_core.telegram import send as group_send
        return group_send(**payload['group'],request_key=key)
    if doc.get('start_contact'):
        from relay_core.conversation_start import send as start_send, action_target
        action_target(doc)
        intent=payload['start']
        return start_send(intent['contact'],intent['endpoint'],intent['kind'],intent['data'],key,
                          intent.get('business_doctype'),intent.get('business_name'))
    readable_source(doc.source_message)
    if doc.operation=='email':
        from relay_core.email import send as email_send
        values=payload.get('email_values')
        if not isinstance(values,dict):raise ValueError('This older email cannot be retried; compose a new message')
        return email_send(**values,request_key=key)
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
