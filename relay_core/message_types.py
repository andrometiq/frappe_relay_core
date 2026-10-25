"""Bounded provider-neutral message data. No HTML or provider URLs are emitted."""
import json
import math
import re


def telegram_vcard(card):
    """Encode portable contact details without permitting vCard line injection."""
    def escape(value):
        return str(value or '').replace('\\', '\\\\').replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')

    def typed(prefix, record):
        kind = record.get('type')
        if kind and not re.fullmatch(r'[A-Za-z0-9_-]{1,30}', kind):
            raise ValueError('Invalid contact detail type')
        return prefix + (';TYPE=' + kind if kind else '')

    name = card['name']
    lines = ['BEGIN:VCARD', 'VERSION:3.0', 'FN:' + escape(name['formatted_name']),
        'N:' + ';'.join(escape(name.get(key)) for key in ('last_name', 'first_name', 'middle_name', 'prefix', 'suffix'))]
    for phone in card.get('phones', []):
        if phone.get('phone'): lines.append(typed('TEL', phone) + ':' + escape(phone['phone']))
        if phone.get('wa_id'): lines.append('X-WA-ID:' + escape(phone['wa_id']))
    for email in card.get('emails', []): lines.append(typed('EMAIL', email) + ':' + escape(email.get('email')))
    for address in card.get('addresses', []):
        lines.append(typed('ADR', address) + ':;;' + ';'.join(escape(address.get(key)) for key in ('street', 'city', 'state', 'zip', 'country')))
        if address.get('country_code'): lines.append('X-COUNTRY-CODE:' + escape(address['country_code']))
    for url in card.get('urls', []): lines.append(typed('URL', url) + ':' + escape(url.get('url')))
    org = card.get('org', {})
    if org: lines.append('ORG:' + escape(org.get('company')) + ';' + escape(org.get('department')))
    if org.get('title'): lines.append('TITLE:' + escape(org['title']))
    if card.get('birthday'): lines.append('BDAY:' + escape(card['birthday']))
    value = '\r\n'.join(lines + ['END:VCARD']) + '\r\n'
    if len(value.encode()) > 2048: raise ValueError('Telegram contact details exceed the 2048-byte vCard limit')
    return value

KINDS = {'text', 'image', 'photo', 'video', 'audio', 'voice', 'document', 'animation',
         'video_note', 'sticker', 'location', 'contact', 'contacts', 'poll', 'order', 'system', 'unsupported'}
# Meta's unsupported.type values, named for staff.
UNSUPPORTED_LABELS = {'poll_creation': 'Poll', 'poll_update': 'Poll vote', 'edit': 'Edited', 'gif': 'GIF',
    'group_invite': 'Group invite', 'hsm': 'Template', 'keep_in_chat': 'Keep-in-chat', 'link_preview': 'Link preview',
    'media_placeholder': 'View-once or unavailable media', 'pin': 'Pinned', 'product': 'Product', 'list': 'List',
    'button': 'Button', 'errors': 'Error', 'image': 'Image', 'interactive': 'Interactive', 'location': 'Location',
    'order': 'Order', 'reaction': 'Reaction', 'view_once': 'View-once'}
SYSTEM_PREVIEWS = {'user_changed_number': 'Customer changed their WhatsApp number',
    'user_changed_user_id': 'Customer WhatsApp identity changed',
    'customer_identity_changed': 'Customer WhatsApp identity changed',
    'request_welcome': 'Customer opened the chat'}


def text(value, maximum=12000, *, required=False):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value:
        raise ValueError('Invalid message text')
    if required and not value.strip():
        raise ValueError('Message text is required')
    return value


def location(value):
    if not isinstance(value, dict):
        raise ValueError('Location must be an object')
    result = {}
    for name, maximum in [('latitude', 90), ('longitude', 180)]:
        coordinate = value.get(name)
        if type(coordinate) not in (int, float) or not math.isfinite(coordinate) or abs(coordinate) > maximum:
            raise ValueError('Invalid location coordinates')
        result[name] = coordinate
    for name in ('name', 'address'):
        if name in value:
            result[name] = text(value[name], 1000)
    return result


def fields(value, keys, maximum=1000):
    """Bounded string subset of a provider object; other values are dropped."""
    if not isinstance(value, dict):
        raise ValueError('Invalid message detail')
    return {key: text(value[key], maximum) for key in keys if isinstance(value.get(key), str)}


def order(value):
    items = value.get('product_items', []) if isinstance(value, dict) else None
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError('Invalid order items')
    result = fields(value, ('catalog_id', 'text'))
    result['items'] = []
    for item in items:
        row = fields(item, ('product_retailer_id', 'currency'), 300)
        for key in ('quantity', 'item_price'):
            number = item.get(key)
            if number is not None:
                if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number < 2**52:
                    raise ValueError('Invalid order quantity or price')
                row[key] = number
        result['items'].append(row)
    return result


def meta_error(errors):
    """The first Meta error as code, title and details."""
    error = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
    result = {'code': error['code']} if type(error.get('code')) is int else {}
    result.update(fields(error, ('title',), 300))
    details = error.get('error_data', {}).get('details') if isinstance(error.get('error_data'), dict) else None
    if isinstance(details, str):
        result['details'] = text(details, 1000)
    return result


def unsupported(detail, errors):
    """Keep Meta's reason so staff can see why the content is missing."""
    kind = detail.get('type') or detail.get('raw_type') if isinstance(detail, dict) else None
    result = {'type': text(kind, 100)} if isinstance(kind, str) else {}
    result.update(meta_error(errors))
    if result.get('code') == 131060:
        result['reason'] = result.get('title') or 'This message is currently unavailable'
    elif isinstance(kind, str) and kind != 'unknown':
        label = UNSUPPORTED_LABELS.get(kind) or kind.replace('_', ' ').capitalize()
        result['reason'] = label + ' messages are not supported by WhatsApp Business'
    else:
        result['reason'] = 'This message type is not supported by WhatsApp Business'
    return result


def contacts(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 20:
        raise ValueError('Expected 1–20 contact cards')
    result = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError('Invalid contact card')
        name = value.get('name')
        if not isinstance(name, dict):
            raise ValueError('Contact name is required')
        row = {'name': {key: text(content, 300, required=key == 'formatted_name') for key, content in name.items()
            if key in ('formatted_name', 'first_name', 'last_name', 'middle_name', 'prefix', 'suffix')}}
        if not row['name'].get('formatted_name'):
            raise ValueError('Contact display name is required')
        for kind, keys in [('phones', ('phone', 'type', 'wa_id')), ('emails', ('email', 'type'))]:
            records = value.get(kind, [])
            if not isinstance(records, list) or len(records) > 20:
                raise ValueError('Too many contact details')
            row[kind] = []
            for record in records:
                if not isinstance(record, dict):
                    raise ValueError('Invalid contact detail')
                row[kind].append({key: text(content, 300) for key, content in record.items() if key in keys})
        for kind, keys in [('addresses', ('street', 'city', 'state', 'zip', 'country', 'country_code', 'type')), ('urls', ('url', 'type'))]:
            records = value.get(kind, [])
            if not isinstance(records, list) or len(records) > 20: raise ValueError('Too many contact details')
            row[kind] = []
            for record in records:
                if not isinstance(record, dict): raise ValueError('Invalid contact detail')
                row[kind].append({key: text(content, 1000) for key, content in record.items() if key in keys})
        if 'org' in value:
            if not isinstance(value['org'], dict): raise ValueError('Invalid contact organization')
            row['org'] = {key: text(content, 300) for key, content in value['org'].items() if key in ('company', 'department', 'title')}
        if 'birthday' in value: row['birthday'] = text(value['birthday'], 10)
        result.append(row)
    return result


def named_card(card):
    """WhatsApp omits the name of an unsaved contact; show its number instead."""
    if not isinstance(card, dict) or (isinstance(card.get('name'), dict) and card['name'].get('formatted_name')):
        return card
    phones = [phone.get('phone') or phone.get('wa_id') for phone in card.get('phones') or [] if isinstance(phone, dict)]
    name = dict(card.get('name') if isinstance(card.get('name'), dict) else {})
    name['formatted_name'] = next((phone for phone in phones if isinstance(phone, str) and phone.strip()), 'Contact')
    return dict(card, name=name)


def media(value):
    if isinstance(value, list):
        value = value[-1] if value else {}
    if not isinstance(value, dict):
        raise ValueError('Invalid media metadata')
    result = {}
    for key in ('id', 'file_id', 'file_unique_id', 'mime_type', 'filename', 'file_name', 'emoji'):
        if key in value:
            result[key] = text(value[key], 500)
    for key in ('width', 'height', 'duration', 'file_size'):
        if key in value:
            number = value[key]
            if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number < 2**52:
                raise ValueError('Invalid media dimensions')
            result[key] = number
    for key in ('is_animated', 'is_video', 'animated', 'voice'):
        if key in value:
            if type(value[key]) is not bool:
                raise ValueError('Invalid media animation flag')
            result[key] = value[key]
    return result


def normalize(kind, detail, *, provider, body='', errors=None):
    if kind=='button' and provider=='WhatsApp':
        if not isinstance(detail,dict):raise ValueError('Invalid template button reply')
        return {'kind':'text','text':text(detail.get('text') or 'Button selected',1000),
                'selection_id':text(detail.get('payload') or '',1000),'selection_type':'template_button'}
    if kind == 'interactive' and provider == 'WhatsApp':
        if not isinstance(detail, dict):raise ValueError('Invalid interactive reply')
        selected=detail.get('button_reply') or detail.get('list_reply')
        if isinstance(selected,dict):
            return {'kind':'text','text':text(selected.get('title') or selected.get('id') or 'Selection received',1000),
                    'selection_id':text(selected.get('id') or '',1000)}
        permission=detail.get('call_permission_reply')
        if isinstance(permission,dict):
            return {'kind':'text','text':'Call permission: '+text(permission.get('response') or 'Response received',100)}
        flow=detail.get('nfm_reply')
        if isinstance(flow,dict):
            raw=flow.get('response_json') or '{}'
            if not isinstance(raw,str) or len(raw)>12000:raise ValueError('Invalid form response')
            try:answers=json.loads(raw)
            except ValueError:raise ValueError('Invalid form response') from None
            if not isinstance(answers,dict) or len(answers)>60:raise ValueError('Invalid form fields')
            # Correlation tokens remain in the protected event, not the chat display.
            answers={text(key,200):value for key,value in answers.items() if key!='flow_token'}
            return {'kind':'text','text':text(flow.get('body') or 'Form submitted',1000),'form_response':answers}
        reply_type=detail.get('type') if isinstance(detail.get('type'),str) else 'interactive'
        return {'kind':'unsupported','unsupported':unsupported({'type':reply_type},errors)}
    if provider == 'WhatsApp' and kind == 'order':
        return {'kind': 'order', 'order': order(detail)}
    if provider == 'WhatsApp' and kind in ('system', 'request_welcome'):
        detail = {'type': 'request_welcome'} if kind == 'request_welcome' else detail
        return {'kind': 'system', 'system': fields(detail, ('type', 'body', 'wa_id', 'user_id', 'previous_user_id'))}
    if provider == 'WhatsApp' and kind not in KINDS - {'poll', 'order', 'system', 'unsupported'}:
        return {'kind': 'unsupported', 'unsupported': unsupported(detail if kind == 'unsupported' else {'type': kind}, errors)}
    if kind not in KINDS:
        kind = 'unsupported'
    result = {'kind': kind}
    if kind == 'text':
        result['text'] = text(body)
    elif kind == 'location':
        result['location'] = location(detail)
    elif kind in ('contact', 'contacts'):
        if provider == 'WhatsApp' and isinstance(detail, list):
            detail = [named_card(card) for card in detail]
        if provider == 'Telegram':
            if detail.get('vcard'):
                result['vcard'] = text(detail['vcard'], 2048)
            detail = {'name': {'formatted_name': ' '.join(str(detail.get(k, '')) for k in ('first_name', 'last_name')).strip(),
                               'first_name': detail.get('first_name', ''), 'last_name': detail.get('last_name', '')},
                      'phones': [{'phone': detail.get('phone_number', '')}]}
            detail = [detail]
        result['contacts'] = contacts(detail)
    elif kind not in ('unsupported', 'poll'):
        result['media'] = media(detail)
        if body:
            result['caption'] = text(body, 12000)
    return result


def referral(value):
    """Click-to-WhatsApp ad context without provider media URLs."""
    result = fields(value, ('source_type', 'source_id', 'headline', 'body', 'media_type', 'ctwa_clid'))
    welcome = value.get('welcome_message')
    if isinstance(welcome, dict) and isinstance(welcome.get('text'), str):
        result['welcome_message'] = text(welcome['text'], 1000)
    return result


def preview(value):
    if isinstance(value.get('form_response'),dict):
        return (value.get('text','Form submitted')+'\n'+json.dumps(value['form_response'],ensure_ascii=False))[:12000]
    if value.get('kind') == 'unsupported' and value.get('unsupported', {}).get('reason'):
        return value['unsupported']['reason']
    if value.get('kind') == 'system':
        system = value.get('system') or {}
        return system.get('body') or SYSTEM_PREVIEWS.get(system.get('type'), 'WhatsApp system update')
    if value.get('kind') == 'order':
        details = value.get('order') or {}; count = len(details.get('items') or [])
        label = 'Order: %d item%s' % (count, '' if count == 1 else 's')
        return label + (' · ' + details['text'] if details.get('text') else '')
    if value.get('kind') == 'revoked':
        return 'Message deleted by sender'
    if value.get('kind') == 'audio' and (value.get('media') or {}).get('voice') and not value.get('caption'):
        return 'Voice message'
    return value.get('text') or value.get('caption') or (
        (value.get('media') or {}).get('filename') or (value.get('media') or {}).get('file_name')
        if value['kind'] == 'document' else None) or {
        'contact': 'Contact card', 'contacts': 'Contact cards', 'location': 'Location',
        'sticker': 'Sticker', 'photo': 'Photo', 'image': 'Photo'}.get(value['kind'], value['kind'].replace('_', ' ').title())
