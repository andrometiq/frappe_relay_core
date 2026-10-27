"""Marketing opt-out and opt-in by keyword. A keyword message changes its number's opt-out and gets no automatic reply."""
import frappe

from relay_core.contact_lifecycle import endpoint_key

OPT_OUT = ('STOP', 'UNSUBSCRIBE')
OPT_IN = ('START',)
LONGEST = 40


def keywords(field: str, default: tuple[str, ...]) -> set[str]:
    """Keywords from Relay Settings, one per line; the defaults while the setting is empty."""
    text = frappe.db.get_single_value('Relay Settings', field) or ''
    words = {word.strip().casefold() for word in text.splitlines() if word.strip()}
    return words or {word.casefold() for word in default}


def choice(message) -> bool | None:
    """True for an opt-out keyword, False for an opt-in keyword, None for any other message."""
    if message.direction != 'Incoming':
        return None
    text = (message.content or '').strip().casefold()
    if not text or len(text) > LONGEST:
        return None
    if text in keywords('opt_out_keywords', OPT_OUT):
        return True
    if text in keywords('opt_in_keywords', OPT_IN):
        return False
    return None


def is_keyword(message) -> bool:
    return choice(message) is not None


def on_message(doc, method=None):
    if doc.get('legacy_source'):
        return  # apply_history sets imported keywords with their own time.
    opted_out = choice(doc)
    if opted_out is None or not doc.sender_endpoint:
        return
    endpoint = frappe.db.get_value('Relay Contact Endpoint',
                                   {'endpoint_key': endpoint_key(doc.channel, doc.sender_endpoint)}, 'name')
    if endpoint:
        frappe.db.set_value('Relay Contact Endpoint', endpoint, {
            'marketing_opt_out': int(opted_out), 'opt_out_changed_at': frappe.utils.now_datetime()})


def apply_history(channel: str, endpoint: str) -> None:
    """Give the number the choice of the newest keyword in its imported history, unless it changed later."""
    row = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': endpoint_key(channel, endpoint)},
                              ['name', 'opt_out_changed_at'], as_dict=True)
    if not row:
        return
    messages = frappe.get_all('Relay Message', filters={'channel': channel, 'sender_endpoint': endpoint, 'direction': 'Incoming',
                              'legacy_source': ['is', 'set']}, fields=['content', 'direction', 'sent_at', 'creation'],
                              limit_page_length=0)
    keyed = [(message.sent_at or message.creation, choice(message)) for message in messages]
    keyed = [item for item in keyed if item[1] is not None]
    if not keyed:
        return
    stamp, opted_out = max(keyed, key=lambda item: item[0])
    if row.opt_out_changed_at and row.opt_out_changed_at >= stamp:
        return
    frappe.db.set_value('Relay Contact Endpoint', row.name, {'marketing_opt_out': int(opted_out), 'opt_out_changed_at': stamp})
