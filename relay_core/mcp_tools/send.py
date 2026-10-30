"""Customer sends. Every tool here reaches a real person, so each one needs a request_key and is idempotent on it."""
from relay_core.mcp_tools.inbox import MESSAGE
from relay_core.mcp_tools.registry import CURSOR, FLAG, NAME_FIELD, READ, REQUEST_KEY, SEND, STRING, ToolError, obj, tool

CHANNEL = {'type': 'string', 'minLength': 1, 'maxLength': 140, 'description': 'Relay Channel name from channels_list.'}
NUMBER = {'type': 'string', 'pattern': '^\\+?[0-9]{8,16}$', 'description': 'Phone number with country code, digits only.'}
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 4096}
HTTPS = {'type': 'string', 'pattern': '^https://', 'maxLength': 2048}
EMAIL = {'type': 'string', 'pattern': '^[^@\\s]+@[^@\\s]+$', 'maxLength': 254}
OTHER_DATA = obj({'latitude': {'type': 'number'}, 'longitude': {'type': 'number'}, 'name': STRING, 'address': STRING,
                  'contacts': {'type': 'array', 'items': {'type': 'object'}, 'minItems': 1, 'maxItems': 5},
                  'emoji': {'type': 'string', 'maxLength': 100}, 'sticker_message': MESSAGE})
WINDOW_ERROR = '"Outside the 24-hour reply window": send chat_send_template instead'


@tool('chat_send_text', SEND, obj({'message': MESSAGE, 'text': TEXT, 'request_key': REQUEST_KEY, 'quote': FLAG,
                                   'via': {'type': 'string', 'maxLength': 140, 'description': 'auto, or a RELAY-CH id to send '
                                           'from another number of the same person.'}},
                                  ('message', 'text', 'request_key')), {
    'summary': 'Reply with text to the chat of one message (WhatsApp or Telegram). Recipient and channel come from that message.',
    'use_when': 'answering a customer within the 24-hour window, after the user agreed to the text.',
    'avoid_when': 'the window is closed or there is no message yet; use chat_send_template.',
    'returns': '{name: action, status, message: sent message id}. The same request_key returns the first result.',
    'errors': WINDOW_ERROR + '; "Request key already belongs to different content" when a key is reused for new text.'}, chat=True)
def chat_send_text(message, text, request_key, quote=1, via=None):
    from relay_core.messaging import send
    return send(message, 'text', {'text': text}, request_key, quote=quote, via=via)


@tool('chat_send_media', SEND, obj({'number': NUMBER, 'channel': CHANNEL, 'media_url': HTTPS,
                                    'media_type': {'type': 'string', 'enum': ['image', 'video', 'audio', 'document']},
                                    'caption': {'type': 'string', 'maxLength': 1024}, 'filename': {'type': 'string', 'maxLength': 240},
                                    'request_key': REQUEST_KEY}, ('number', 'channel', 'media_url', 'media_type', 'request_key')), {
    'summary': 'Send a WhatsApp image, video, audio or document from a public HTTPS link to one number.',
    'use_when': 'the user asks to send a file that is reachable by an HTTPS link, inside the 24-hour window.',
    'avoid_when': 'the window is closed; use chat_send_template with a media header.',
    'returns': '{status, message} of the send. The same request_key returns the first result.',
    'errors': WINDOW_ERROR + '; "media_type must be image, video, audio or document"; an unknown number needs a manager.'}, chat=True)
def chat_send_media(number, channel, media_url, media_type, request_key, caption=None, filename=None):
    from relay_core.messaging_api import send_media
    return send_media(number, media_url, media_type, caption=caption, filename=filename, key=request_key, channel=channel)


@tool('chat_send_other', SEND, obj({'message': MESSAGE, 'kind': {'type': 'string', 'enum': ['location', 'contact', 'sticker', 'reaction']},
                                    'data': OTHER_DATA, 'request_key': REQUEST_KEY}, ('message', 'kind', 'data', 'request_key')), {
    'summary': 'Reply with a location, contact card or sticker, or react to one message with an emoji (empty emoji removes it).',
    'use_when': 'the user asks for one of these message kinds.',
    'avoid_when': 'you send text or a file; use chat_send_text or chat_send_media.',
    'returns': '{name: action, status, message}.',
    'errors': '"Unexpected message arguments" when data has fields of another kind. data: location {latitude, longitude, name?, '
              'address?}; contact {contacts: [WhatsApp contact cards]}; sticker {sticker_message?}; reaction {emoji}.'}, chat=True)
def chat_send_other(message, kind, data, request_key):
    from relay_core.messaging import send
    return send(message, kind, data, request_key)


@tool('chat_send_template', SEND, obj({'number': NUMBER, 'channel': CHANNEL, 'template': NAME_FIELD, 'language': {'type': 'string', 'maxLength': 20},
                                       'params': {'type': ['object', 'array']}, 'header_media_url': HTTPS,
                                       'business_doctype': NAME_FIELD, 'business_name': NAME_FIELD, 'request_key': REQUEST_KEY},
                                      ('number', 'channel', 'template', 'language', 'request_key')), {
    'summary': 'Send an approved WhatsApp template to one phone number. It works outside the 24-hour window.',
    'use_when': 'starting a chat, or replying after the window closed, after the user agreed.',
    'avoid_when': 'the window is open and plain text is enough; use chat_send_text.',
    'returns': '{status, message} of the send. The same request_key returns the first result.',
    'errors': '"Template is not approved"; missing params (object of named values, or a list in template order); an unknown '
              'number needs a manager and a business record.'}, chat=True)
def chat_send_template(number, channel, template, language, request_key, params=None, header_media_url=None,
                       business_doctype=None, business_name=None):
    from relay_core.messaging_api import send_template
    return send_template(number, template, language, params=params, header_media_url=header_media_url, key=request_key,
                         business_doctype=business_doctype, business_name=business_name, channel=channel)


@tool('chat_send_email', SEND, obj({'to': {'type': 'array', 'items': EMAIL, 'minItems': 1, 'maxItems': 20},
                                    'cc': {'type': 'array', 'items': EMAIL, 'maxItems': 20}, 'subject': {'type': 'string', 'minLength': 1, 'maxLength': 300},
                                    'body': {'type': 'string', 'minLength': 1, 'maxLength': 100000}, 'channel': CHANNEL,
                                    'message': MESSAGE, 'request_key': REQUEST_KEY}, ('to', 'subject', 'body', 'channel', 'request_key')), {
    'summary': 'Send an email from a Relay mailbox; give message to reply in that email thread.',
    'use_when': 'the user asks to email a customer.',
    'avoid_when': 'the customer is on WhatsApp or Telegram; use chat_send_text.',
    'returns': '{status, message} of the send.',
    'errors': '"Not permitted" for a mailbox the user cannot use; invalid address.'}, chat=True)
def chat_send_email(to, subject, body, channel, request_key, cc=None, message=None):
    from relay_core.email import send
    return send(to, subject, body, cc=cc, request_key=request_key, message=message, channel_name=channel)


@tool('chat_send_telegram', SEND, obj({'chat_id': {'type': 'integer'}, 'text': TEXT, 'channel': CHANNEL, 'reply_to': {'type': 'integer', 'minimum': 1},
                                       'message_thread_id': {'type': 'integer', 'minimum': 1}, 'request_key': REQUEST_KEY},
                                      ('chat_id', 'text', 'channel', 'request_key')), {
    'summary': 'Send text to a Telegram group or chat by its Telegram chat id, optionally into a topic.',
    'use_when': 'posting into a Telegram group that has no message to reply to.',
    'avoid_when': 'you reply to a Telegram message; use chat_send_text with that message.',
    'returns': '{accepted, message}.',
    'errors': '"This Telegram chat belongs to another bot"; "Not permitted" for an unknown group.'}, chat=True)
def chat_send_telegram(chat_id, text, channel, request_key, reply_to=0, message_thread_id=0):
    from relay_core.telegram import send
    return send(chat_id, text, reply_to=reply_to, message_thread_id=message_thread_id, request_key=request_key, channel=channel)


@tool('chat_start', SEND, obj({'contact': NAME_FIELD, 'channel': CHANNEL, 'business_doctype': NAME_FIELD, 'business_name': NAME_FIELD,
                               'kind': {'type': 'string', 'enum': ['text', 'template', 'email']},
                               'text': TEXT, 'template': obj({'name': NAME_FIELD, 'language': NAME_FIELD, 'components': {'type': 'array'}},
                                                             ('name', 'language')),
                               'email': obj({'subject': NAME_FIELD, 'body': TEXT}, ('subject', 'body')), 'request_key': REQUEST_KEY},
                              ('contact', 'channel', 'business_doctype', 'business_name', 'kind', 'request_key')), {
    'summary': 'Start a chat with a Frappe Contact linked to a business record, from a chosen channel.',
    'use_when': 'the person has no chat yet, or you write from the record, after the user agreed.',
    'avoid_when': 'a message exists to reply to; use chat_send_text or chat_send_template.',
    'returns': '{name: action, status, message}.',
    'errors': 'kind text needs text and an open window; kind template needs template {name, language, components?}; kind email '
              'needs email {subject, body}; "Choose one verified endpoint for this business".'}, chat=True)
def chat_start(contact, channel, business_doctype, business_name, kind, request_key, text=None, template=None, email=None):
    from relay_core.conversation_start import send_business
    if not {'text': text, 'template': template, 'email': email}[kind]:
        raise ToolError(f'kind {kind} needs the {kind} argument')
    if kind == 'template':
        return send_business(contact, channel, 'whatsapp', {'operation': 'templates.send', 'arguments': template}, request_key,
                             business_doctype, business_name)
    data = {'text': text} if kind == 'text' else email
    return send_business(contact, channel, kind, data, request_key, business_doctype, business_name)


@tool('send_status', READ, obj({'message': MESSAGE, 'batch': CURSOR}), {
    'summary': 'Read the delivery state of one sent message, or of a send batch.',
    'use_when': 'after a send, to see Submitted, Sent, Delivered, Read or Failed with the reason.',
    'avoid_when': 'you follow a campaign; use campaigns_read.',
    'returns': '{message, status, delivery_error, sent_at} or the batch item results.',
    'errors': 'give exactly one of message or batch; "Not found" for an unknown message.'})
def send_status(message=None, batch=None):
    if bool(message) == bool(batch):
        raise ToolError('Give exactly one of message or batch')
    if batch:
        from relay_core.messaging_api import send_status as batch_status
        return batch_status(batch)
    from relay_core.api import message_context
    context = message_context(message)
    row = next(item for item in context['items'] if item.get('name') == message)
    return {key: row.get(key) for key in ('name', 'status', 'delivery_error', 'sent_at', 'direction', 'channel')}


@tool('send_retry', SEND, obj({'message': MESSAGE}, ('message',)), {
    'summary': 'Send a rejected or undelivered message of yours again. A repeat call does not send twice.',
    'use_when': 'send_status shows Failed or Rejected and the user wants it sent again.',
    'avoid_when': 'the message was delivered, or someone else sent it.',
    'returns': 'the new send result.',
    'errors': '"Only the original sender can retry a rejected or undelivered message"; automated messages cannot be retried.'}, chat=True)
def send_retry(message):
    from relay_core.messaging import retry
    return retry(message=message)

