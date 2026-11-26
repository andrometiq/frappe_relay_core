"""Safe display metadata derived only from the permission-checked channel."""
import json
import re
from email.utils import getaddresses


def mailbox_addresses(channel):
    values = [channel.get('mailbox_address') or '', channel.get('mailbox_aliases') or '']
    return sorted({address.casefold() for _, address in getaddresses([value.replace('\n', ',') for value in values])
                   if '@' in address})


def business_choice_label(message):
    """Historical routing tokens are transport metadata, never conversation text."""
    data = message.get('message_data') or {}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            data = {}
    text = data.get('text') if isinstance(data, dict) else None
    if any(re.fullmatch(r'relay-business:[a-f0-9]{32}', str(value or '').strip())
           for value in (text, message.get('content'))):
        return 'Chose: ' + message['business_doctype'] if message.get('business_doctype') else 'Business choice received'


def decorate_messages(rows, channels):
    for row in rows:
        label = business_choice_label(row)
        if label:
            row['content'] = label
            row['message_data'] = {'kind': 'text', 'text': label}
        channel = channels[row['channel']]
        row['channel_title'] = channel.get('title') or channel.get('channel') or 'Channel'
        if channel.get('channel') != 'Email':
            continue
        context = row.get('provider_context') or {}
        if isinstance(context, str):
            try:
                context = json.loads(context)
            except (ValueError, TypeError):
                context = {}
        context = dict(context) if isinstance(context, dict) else {}
        # Overwrite any inbound claim; neither From/To nor Reply-To proves ownership.
        context['mailbox_addresses'] = mailbox_addresses(channel)
        row['provider_context'] = context
    return rows


def add_senders(rows):
    """Name who sent each outgoing row as `sender`: {'user', 'name', 'image'} for a person, or {'automated': 1, 'name': 'Automation'}.
    Rows must already be permission-checked; this adds only the sender's display card."""
    outgoing = [row['name'] for row in rows if row.get('direction') == 'Outgoing' and row.get('name')]
    if not outgoing:
        return rows
    found = senders(outgoing)
    from relay_core.user_profiles import user_cards
    cards = {card['user']: card for card in user_cards(sorted({user for user in found.values() if user}))}
    for row in rows:
        if row.get('name') not in found:
            continue
        user = found[row['name']]
        card = cards.get(user) or {}
        row['sender'] = {'user': user, 'name': card.get('name') or user, 'image': card.get('image') or ''} if user \
            else {'automated': 1, 'name': 'Automation'}
    return rows


def senders(outgoing):
    """{message name: user who sent it, or None for Automation} of outgoing messages.

    The send action's owner is the person who pressed Send, unless the action is an automatic delivery (automation, flow,
    business event, routing, ticket notice, automatic email) or an AI handoff notice. A message without an action is an
    old-app import by its author, or else the system's own (Hub campaign imports, business prompts): Automation."""
    import frappe
    from relay_core.messaging import automatic_delivery
    # A sent message keeps its send action's request key as source_key; that key is the action's unique index.
    stored = {row.name: row for row in frappe.get_all('Relay Message', filters={'name': ['in', outgoing]}, fields=['name', 'source_key', 'legacy_author'])}
    keys = [row.source_key for row in stored.values() if row.source_key]
    actions = {row.request_key: row for row in frappe.get_all('Relay Message Action', filters={'request_key': ['in', keys]},
                                                              fields=['request_key', 'owner', 'payload'])} if keys else {}
    found = {}
    for name in outgoing:
        message = stored.get(name) or {}
        action = actions.get(message.get('source_key'))
        payload = action_payload(action.payload) if action else {}
        user = action.owner if action else message.get('legacy_author')
        automatic = automatic_delivery(payload) or payload.get('handoff_notice')
        found[name] = None if automatic or user in (None, '', 'Guest') else user
    return found


def action_payload(value):
    if isinstance(value, dict):
        return value
    try:
        payload = json.loads(value or '{}')
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}
