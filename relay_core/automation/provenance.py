"""Provider conversation provenance and immutable reply routing.

IDs here come from authenticated provider callbacks, never model output. A
verified endpoint maps the destination (group or private chat) to a business
Contact; the participant is deliberately kept separate from that destination.
"""
import hashlib
import json
import re


def integer(value, *, positive=False):
    if type(value) is not int or value == 0 or abs(value) >= 2**52 or positive and value < 0:
        raise ValueError('Invalid provider numeric identifier')
    return value


def telegram_message(payload):
    raw = payload.get('payload')
    if raw is None:
        return None  # Older normalized private-chat events remain readable.
    if not isinstance(raw, dict):
        raise ValueError('Invalid Telegram update')
    # Only a new user message is projected. Media keeps its own type so the
    # text-only automation policy cannot treat captions as approved text input.
    message = raw.get('message')
    if not isinstance(message, dict):
        return {}
    if any(key in message for key in ('new_chat_members', 'left_chat_member', 'new_chat_title',
            'new_chat_photo', 'delete_chat_photo', 'group_chat_created', 'supergroup_chat_created',
            'channel_chat_created', 'migrate_to_chat_id', 'migrate_from_chat_id', 'pinned_message',
            'forum_topic_created', 'forum_topic_edited', 'forum_topic_closed', 'forum_topic_reopened',
            'general_forum_topic_hidden', 'general_forum_topic_unhidden')):
        return {}
    kind = 'text' if isinstance(message.get('text'), str) else next((key for key in
        ('photo', 'document', 'video', 'animation', 'audio', 'voice', 'sticker', 'video_note', 'contact', 'location', 'poll')
        if key in message), None)
    if kind is None:
        return {}
    body = message['text'] if kind == 'text' else message.get('caption', '')
    if not isinstance(body, str):
        raise ValueError('Invalid Telegram text or caption')
    if any(key in raw for key in ('edited_message', 'message_reaction', 'message_reaction_count')):
        return {}
    sender = message.get('from') or {}
    if not isinstance(sender, dict) or sender.get('is_bot') and not message.get('sender_chat'):
        return {}
    chat = message.get('chat')
    if not isinstance(chat, dict) or chat.get('type') not in ('private', 'group', 'supergroup'):
        return {}
    chat_id = integer(chat.get('id'))
    if (chat['type'] == 'private') != (chat_id > 0):
        raise ValueError('Telegram chat type does not match destination identifier')
    message_id = integer(message.get('message_id'), positive=True)
    if str(chat_id) != payload.get('sender') or body != payload.get('body'):
        raise ValueError('Telegram normalized payload does not match provider update')
    if str(raw.get('update_id')) != payload.get('provider_id'):
        raise ValueError('Telegram update identity mismatch')
    context = {'provider': 'Telegram', 'chat_id': chat_id, 'chat_type': chat['type'],
               'message_id': message_id, 'update_id': raw['update_id'], 'message_type': kind}
    if kind != 'text':
        media = message.get(kind)
        if isinstance(media, list):
            media = media[-1] if media else {}
        if isinstance(media, dict):
            context['media'] = {key: value for key, value in media.items()
                if key in ('file_id', 'file_unique_id', 'mime_type', 'file_name', 'duration', 'width', 'height', 'file_size')
                and (isinstance(value, str) and len(value) <= 300 or type(value) is int and 0 <= value < 2**52)}
        if body:
            context['caption'] = body[:2000]
    if sender.get('id') is not None:
        context['participant_id'] = integer(sender['id'], positive=True)
    sender_chat = message.get('sender_chat')
    if sender_chat:
        context['sender_chat_id'] = integer(sender_chat.get('id'))
    if message.get('message_thread_id') is not None:
        context['message_thread_id'] = integer(message['message_thread_id'], positive=True)
    reply = message.get('reply_to_message')
    if reply:
        if not isinstance(reply, dict):
            raise ValueError('Invalid Telegram reply context')
        context['reply_to_message_id'] = integer(reply.get('message_id'), positive=True)
    return context


def context_of(message):
    value = message.get('provider_context') if hasattr(message, 'get') else getattr(message, 'provider_context', None)
    if value in (None, ''):
        return {}
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError('Invalid provider context')
    return value


def conversation_key(channel, destination, context):
    thread = context.get('email_thread_id') if context.get('provider') == 'Email' else context.get('message_thread_id', 0)
    if context.get('provider') == 'Email' and not thread:
        thread = context.get('message_id') or context.get('in_reply_to')
    return hashlib.sha256(json.dumps([channel, destination, thread], separators=(',', ':')).encode()).hexdigest()


def email_context(raw, subject, event_id):
    if not isinstance(raw, dict) or not isinstance(raw.get('authentication') or {}, dict):
        raise ValueError('Invalid email provenance')
    refs = raw.get('references') or []
    if not isinstance(refs, list) or len(refs) > 100:
        raise ValueError('Invalid email references')
    refs = [value for value in refs if email_message_id(value)][-20:]
    parent = email_message_id(raw.get('in_reply_to'))
    message = email_message_id(raw.get('message_id'))
    return {'provider': 'Email', 'subject': subject, 'message_id': message,
            'in_reply_to': parent, 'reply_to_message_id': parent, 'references': refs,
            'email_thread_id': next(iter(refs), None) or parent or message or event_id,
            'auto_submitted': bool(raw.get('auto_submitted')),
            'authentication': raw.get('authentication') or {}}


def email_message_id(value):
    return value if isinstance(value, str) and re.fullmatch(r'<[^<>\s@\x00-\x1f\x7f]{1,120}@[^<>\s@\x00-\x1f\x7f]{1,120}>', value) else None


def telegram_route(message, body):
    try:
        chat_id = int(message.sender_endpoint)
    except (TypeError, ValueError):
        raise ValueError('Telegram sender endpoint is invalid') from None
    integer(chat_id)
    context = context_of(message)
    result = {'chat_id': chat_id, 'text': body}
    if not context:
        if chat_id < 0:
            raise ValueError('Group provenance is required before automatic replies')
        return result
    if context.get('provider') != 'Telegram' or context.get('chat_id') != chat_id:
        raise ValueError('Telegram destination does not match its provider context')
    if context.get('chat_type') not in ('private', 'group', 'supergroup'):
        raise ValueError('Telegram chat type is not supported for automation')
    if (context['chat_type'] == 'private') != (chat_id > 0):
        raise ValueError('Telegram chat type does not match destination identifier')
    result['reply_to'] = integer(context.get('message_id'), positive=True)
    if context.get('message_thread_id') is not None:
        result['message_thread_id'] = integer(context['message_thread_id'], positive=True)
    return result


def whatsapp_group_route(message, body):
    context = context_of(message)
    group_id = context.get('group_id')
    if not group_id:
        return None
    if context.get('provider') != 'WhatsApp' or group_id != message.sender_endpoint:
        raise ValueError('WhatsApp group destination does not match provider context')
    return {'id': group_id, 'body': body, 'reply_to': message.provider_id}
