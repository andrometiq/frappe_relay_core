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
