"""Channel registry: the one place that maps a channel name to its features."""
from relay_core.channels.contract import Channel
from relay_core.channels.email import Email
from relay_core.channels.telegram import Telegram
from relay_core.channels.whatsapp import WhatsApp

CHANNELS = {item.name: item() for item in (WhatsApp, Telegram, Email)}


def channel(name: str) -> Channel:
    if name not in CHANNELS:
        raise ValueError(f'Unknown channel: {name}')
    return CHANNELS[name]


def enabled() -> list[Channel]:
    """The always-on channels, plus Telegram and Email once the Hub links an enabled bot or mailbox to this site."""
    from relay_core.settings import ENABLED_CHANNELS
    on = set(ENABLED_CHANNELS) | linked()
    return [item for name, item in CHANNELS.items() if name in on]


def linked() -> set[str]:
    import frappe
    from relay_core.settings import value
    return set(frappe.get_all('Relay Channel', pluck='channel', distinct=True, filters={
        'enabled': 1, 'account': value('relay_hub_account') or '', 'channel': ['in', list(CHANNELS)]}))
