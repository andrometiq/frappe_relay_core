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
    from relay_core.settings import ENABLED_CHANNELS
    return [channel(name) for name in ENABLED_CHANNELS]
