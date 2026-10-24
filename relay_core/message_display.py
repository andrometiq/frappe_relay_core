"""Safe display metadata derived only from the permission-checked channel."""
import json
from email.utils import getaddresses


def mailbox_addresses(channel):
    values = [channel.get('mailbox_address') or '', channel.get('mailbox_aliases') or '']
    return sorted({address.casefold() for _, address in getaddresses([value.replace('\n', ',') for value in values])
                   if '@' in address})


def decorate_messages(rows, channels):
    for row in rows:
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
