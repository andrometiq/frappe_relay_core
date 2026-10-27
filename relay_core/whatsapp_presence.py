"""Blue ticks and the typing indicator that one-to-one WhatsApp customers see.

Meta ties the typing indicator to a read receipt for an inbound message, so
both go through the Hub's direct `messages.read` operation.
"""
import frappe
from relay_core.automation.provenance import context_of
from relay_core.settings import value as connection_value

RECEIPT_DAYS = 30  # Meta refuses read receipts for older messages.
READ_LEASE_SECONDS = 5
TYPING_LEASE_SECONDS = 4


def is_enabled(field):
    # The cached document applies field defaults on sites that never saved settings.
    return bool(frappe.get_cached_doc('Relay Settings').get(field))


def newest_incoming(contact, names=None, channel=None):
    """Newest recent one-to-one WhatsApp message from the contact, or None."""
    channels = [channel] if channel else frappe.get_all('Relay Channel',
        filters={'channel': 'WhatsApp', 'account': connection_value('relay_hub_account')}, pluck='name')
    if not channels:
        return None
    filters = {'relay_contact': contact, 'channel': ['in', channels], 'direction': 'Incoming', 'provider_id': ['is', 'set'],
               'legacy_source': ['is', 'not set'],
               'creation': ['>', frappe.utils.add_days(frappe.utils.now_datetime(), -RECEIPT_DAYS)]}
    if names is not None:
        filters['name'] = ['in', names]
    rows = frappe.get_all('Relay Message', filters=filters, fields=['name', 'provider_id', 'provider_context', 'channel'],
                          order_by='creation desc, name desc', limit_page_length=20)
    for row in rows:
        context = context_of(row)
        if context.get('provider') == 'WhatsApp' and not context.get('group_id'):
            return row
    return None


def queue(message, lease, seconds, typing=False):
    """Queue one receipt unless another tab or agent already claimed it."""
    if not frappe.cache.set(frappe.cache.make_key(lease), '1', nx=True, ex=seconds):
        return False
    frappe.enqueue('relay_core.whatsapp_presence.send', queue='short', job_id='relay-whatsapp-read:' + message.name + (':typing' if typing else ''),
                   deduplicate=True, message_id=message.provider_id, typing=typing, channel=message.channel)
    return True


def mark_read(contact, names):
    """Send blue ticks for the newest WhatsApp message an operator just read."""
    if not is_enabled('send_whatsapp_read_receipts'):
        return False
    message = newest_incoming(contact, names)
    if not message:
        return False
    return queue(message, 'relay-whatsapp-read:' + contact + ':' + message.name, READ_LEASE_SECONDS)


def direct_channel(channel, context):
    """The channel name when a source message is a one-to-one WhatsApp chat."""
    if channel.channel == 'WhatsApp' and context.get('provider') == 'WhatsApp' and not context.get('group_id'):
        return channel.name
    return None


def typing(contact, channel):
    """Show the customer that an operator is typing; this also sends blue ticks."""
    if not is_enabled('send_whatsapp_typing'):
        return False
    message = newest_incoming(contact, channel=channel)
    if not message:
        return False
    return queue(message, 'relay-whatsapp-typing:' + contact, TYPING_LEASE_SECONDS, typing=True)


def send(message_id, typing=False, channel=None):
    """Meta takes a read receipt only from the number that received the message."""
    from relay_core import whatsapp
    from relay_core.hub import HubError
    from relay_core.hub_channels import hub_arguments
    arguments = {'operation': 'messages.read', 'message_id': message_id}
    if typing:
        arguments['typing'] = True
    try:
        whatsapp.client().execute(hub_arguments(channel, arguments) if channel else arguments)
    except HubError:
        pass  # Ephemeral feedback: an expired or unknown message must not retry or alert.
