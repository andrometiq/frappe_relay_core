"""WhatsApp Business app numbers (coexistence): copied chats, phone contacts and messages sent from the phone.

Copied chats keep `legacy_source`, so no AI, flow, ticket or unread count runs on them."""
import json

import frappe
from relay_core.automation.provenance import conversation_key
from relay_core.message_types import normalize, preview
from relay_core.message_updates import provider_key
from relay_core.timeline import provider_time

FIELDS = ('history', 'smb_app_state_sync', 'smb_message_echoes')
HISTORY_SOURCE = 'WhatsApp Business app'
HISTORY_DECLINED = 2593109
STATUSES = {'READ': 'Read', 'PLAYED': 'Read', 'DELIVERED': 'Delivered', 'SENT': 'Sent', 'ERROR': 'Failed',
            'FAILED': 'Failed'}
MAX_MESSAGES = 5000


def changes(payload):
    """(field, value) of each coexistence change in a WhatsApp webhook payload."""
    for entry in payload.get('entry') or []:
        for change in (entry.get('changes') or []) if isinstance(entry, dict) else []:
            if isinstance(change, dict) and change.get('field') in FIELDS and isinstance(change.get('value'), dict):
                yield change['field'], change['value']


def project_changes(payload, channel):
    """Import every coexistence change; True when the payload had one."""
    found = False
    for field, value in changes(payload):
        found = True
        {'history': history, 'smb_app_state_sync': contacts, 'smb_message_echoes': echoes}[field](channel, value)
    return found


def number(value):
    digits = ''.join(char for char in str(value or '') if char.isdigit())
    return digits if 6 <= len(digits) <= 20 else ''


def business_number(value):
    return number((value.get('metadata') or {}).get('display_phone_number'))


def contact_for(channel, customer, name=None):
    """The same contact rules as a first incoming message."""
    from relay_core.contact_lifecycle import endpoint_key, sibling_contact, whatsapp_contact
    contact = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': endpoint_key(channel, customer),
                                                              'verified': 1}, 'relay_contact')
    return contact or sibling_contact(channel, customer) or whatsapp_contact(channel, customer, name)


def insert(channel, customer, message, direction, status, historical):
    """One Relay Message per WhatsApp message id; a repeat or an unknown person inserts nothing."""
    if not isinstance(message, dict) or not isinstance(message.get('id'), str) or not 1 <= len(message['id']) <= 300:
        return False
    key = provider_key(channel, customer, message['id'])
    if not customer or frappe.db.exists('Relay Message', {'provider_message_key': key}):
        return False
    contact = contact_for(channel, customer)
    if not contact:
        return False
    kind = message.get('type') if isinstance(message.get('type'), str) else 'unsupported'
    detail = message.get(kind) if isinstance(message.get(kind), dict) else {}
    data = normalize(kind, detail, provider='WhatsApp', body=detail.get('body') if kind == 'text' else detail.get('caption', ''))
    data['source'] = 'business_app'
    context = {'provider': 'WhatsApp', 'participant_id': customer, 'message_id': message['id'], 'source': 'business_app',
               **({'historical': True} if historical else {})}
    frappe.get_doc({'doctype': 'Relay Message', 'relay_contact': contact, 'channel': channel, 'direction': direction,
                    'status': status, 'sent_at': provider_time({}, message), 'content': preview(data),
                    'sender_endpoint': customer, 'provider_id': message['id'],
                    'message_type': data['kind'] if data.get('kind') in ('system', 'unsupported') else kind,
                    'provider_context': json.dumps(context, sort_keys=True),
                    'message_data': json.dumps(data, ensure_ascii=False), 'provider_message_key': key,
                    'conversation_key': conversation_key(channel, customer, context),
                    'legacy_source': HISTORY_SOURCE if historical else None}).insert(ignore_permissions=True)
    return True


def history(channel, value):
    """Copied chats, in phases; progress and a decline go to the signup row."""
    business = business_number(value)
    imported, progress, declined = 0, None, False
    for item in value.get('history') or []:
        if not isinstance(item, dict):
            continue
        if any(isinstance(error, dict) and error.get('code') == HISTORY_DECLINED for error in item.get('errors') or []):
            declined = True
            continue
        meta = item.get('metadata') if isinstance(item.get('metadata'), dict) else {}
        if type(meta.get('progress')) is int and 0 <= meta['progress'] <= 100:
            progress = max(progress or 0, meta['progress'])
        for thread in item.get('threads') or []:
            customer = number(thread.get('id')) if isinstance(thread, dict) else ''
            messages = (thread.get('messages') or [])[:MAX_MESSAGES] if customer else []
            for message in filter(lambda row: isinstance(row, dict), messages):
                imported += copied(channel, customer, business, message)
    if declined:
        update(channel, history_status='Declined')
    elif progress is not None:
        update(channel, history_progress=progress, history_status='Done' if progress >= 100 else 'Importing')
    return imported


def copied(channel, customer, business, message):
    outgoing = number(message.get('from')) == business
    context = message.get('history_context') if isinstance(message.get('history_context'), dict) else {}
    status = STATUSES.get(context.get('status')) or ('Sent' if outgoing else 'Delivered')
    return insert(channel, customer, message, 'Outgoing' if outgoing else 'Incoming', status, historical=True)


def contacts(channel, value):
    """Phone contacts the business app shares; a removed contact keeps its Relay contact and messages."""
    added = 0
    for row in value.get('state_sync') or []:
        if not isinstance(row, dict) or row.get('type') != 'contact' or row.get('action') != 'add':
            continue
        person = row.get('contact') if isinstance(row.get('contact'), dict) else {}
        customer = number(person.get('phone_number'))
        name = person.get('full_name') or person.get('first_name')
        if customer and contact_for(channel, customer, name if isinstance(name, str) else None):
            added += 1
    update(channel, contacts_status='Done')
    return added


def echoes(channel, value):
    """Messages the business sent from the phone app show as sent messages in the chat."""
    sent = 0
    for message in value.get('message_echoes') or []:
        if isinstance(message, dict):
            sent += insert(channel, number(message.get('to')), message, 'Outgoing', 'Sent', historical=False)
    return sent


def update(channel, **changes):
    """The newest signup of this channel's number; a finished copy never goes back."""
    hub_channel = frappe.db.get_value('Relay Channel', channel, 'hub_channel')
    row = frappe.db.get_value('Relay WhatsApp Signup', {'hub_channel': hub_channel},
                              ['name', 'history_status', 'history_progress'], as_dict=True, order_by='creation desc') \
        if hub_channel else None
    if not row:
        return
    if row.history_status in ('Done', 'Declined'):
        changes.pop('history_status', None)
    if 'history_progress' in changes:
        changes['history_progress'] = max(changes['history_progress'], row.history_progress or 0)
    frappe.db.set_value('Relay WhatsApp Signup', row.name, changes)
    from relay_core.onboarding.signup import publish
    publish(row.name)
