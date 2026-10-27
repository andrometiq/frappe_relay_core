"""Find the Relay Channel behind a Hub channel key."""
import frappe


def event_channel(account: str, medium: str, hub_channel: str | None = None) -> str | None:
    """The enabled Relay Channel that received a Hub event, or None.

    An event without a key comes from a single-channel Hub and goes to the only channel of its type.
    A key Core does not know yet goes only to an only channel that has no key, and queues a channel sync,
    so the event stays Uncategorized until the sync adds the channel and recovery projects it."""
    filters = {'account': account, 'channel': medium, 'enabled': 1}
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
