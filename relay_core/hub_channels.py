"""Find the Relay Channel behind a Hub channel key, and name it on Hub calls."""
from contextvars import ContextVar
import frappe

applying_receipt = ContextVar('relay_applying_receipt', default=False)


def is_current(channel, account: str) -> bool:
    """True when the channel can send now for the site's Hub account. A receipt for an earlier send is
    applied to the message of that send even after its channel was switched off or moved."""
    return applying_receipt.get() or bool(channel.enabled and channel.account == account)


def event_channel(account: str, medium: str, hub_channel: str | None = None, receipts: bool = False) -> str | None:
    """The enabled Relay Channel that received a Hub event, or None.

    An event without a key comes from a single-channel Hub and goes to the only channel of its type.
    A key Core does not know yet goes only to an only channel that has no key, and queues a channel sync,
    so the event stays Uncategorized until the sync adds the channel and recovery projects it.
    `receipts` also matches a switched-off channel: statuses belong to the channel that sent."""
    filters = {'account': account, 'channel': medium, **({} if receipts else {'enabled': 1})}
    if hub_channel:
        name = frappe.db.get_value('Relay Channel', dict(filters, hub_channel=hub_channel), 'name')
        if name:
            return name
        filters['hub_channel'] = ['is', 'not set']
    names = frappe.get_all('Relay Channel', filters=filters, pluck='name', limit_page_length=2)
    if len(names) == 1:
        return names[0]
    if hub_channel:
        from relay_core.channel_sync import queue_sync
        queue_sync()
    return None


def hub_arguments(channel, arguments: dict) -> dict:
    """Hub tool arguments that name the sending channel when the site has more than one of its type.

    A Hub picks the only channel of a type itself, and a Hub from before multi-channel rejects the
    argument, so the key goes only where there is a choice. `channel` is a Relay Channel name or row."""
    if isinstance(channel, str):
        channel = frappe.db.get_value('Relay Channel', channel, ['channel', 'account', 'hub_channel'], as_dict=True)
    if not channel or not getattr(channel, 'hub_channel', None) or frappe.db.count(
            'Relay Channel', {'channel': channel.channel, 'account': channel.account}) < 2:
        return arguments
    return dict(arguments, channel=channel.hub_channel)


TEAM_DEFAULTS = {'WhatsApp': 'default_whatsapp_channel', 'Telegram': 'default_telegram_channel',
                 'Email': 'default_email_channel'}


def choose(medium: str, names: list[str] | None = None, contact: str | None = None,
           requested: str | None = None) -> str:
    """The channel a new conversation or API send goes out from.

    Staff pick > the contact's latest incoming channel > the default of the contact's team >
    the site default > the only channel. `names` limits the choice, such as to channels with the
    contact's verified endpoint; it defaults to every enabled channel of the type."""
    from relay_core.settings import value as connection_value
    rows = frappe.get_all('Relay Channel', fields=['name', 'is_default'], order_by='creation asc', filters={
        'channel': medium, 'account': connection_value('relay_hub_account'), 'enabled': 1,
        **({'name': ['in', names]} if names is not None else {})})
    enabled = [row.name for row in rows]
    if requested:
        if requested not in enabled:
            frappe.throw(f'Choose an enabled {medium} channel that can reach this contact')
        return requested
    for name in (latest_incoming(contact, enabled), team_default(contact, medium),
                 next((row.name for row in rows if row.is_default), None)):
        if name in enabled:
            return name
    if len(enabled) == 1:
        return enabled[0]
    frappe.throw(f'Choose the {medium} channel to send from' if enabled else f'Configure an enabled {medium} channel')


def latest_incoming(contact, names):
    if not contact or not names:
        return None
    return frappe.db.get_value('Relay Message', {'relay_contact': contact, 'direction': 'Incoming',
                                                 'channel': ['in', names]}, 'channel', order_by='creation desc')


def team_default(contact, medium):
    team = contact and frappe.db.get_value('Relay Conversation Assignment', {'relay_contact': contact}, 'team')
    return frappe.db.get_value('Relay Team', team, TEAM_DEFAULTS[medium]) if team else None
