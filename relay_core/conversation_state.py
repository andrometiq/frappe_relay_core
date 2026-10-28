"""Writes of the per-user Relay Conversation State row for inbox calls that run on every scroll and chat switch.

They take no Redis lock, no shared naming series row and no document read-modify-write, so users never wait on each other.
"""
import datetime
import json
import frappe

STATE = 'Relay Conversation State'
SEEN_REFRESH = datetime.timedelta(seconds=15)


class StateWriteFailed(frappe.ValidationError):
    """The state write deadlocked twice and nothing was saved; the client retries on its next call."""


def fresh_write(write):
    """Run a state write on a new snapshot and retry it once after a deadlock. Raise StateWriteFailed after the retry.

    It commits the request transaction first, so use it only in state endpoints that have not written before it.
    The permission reads before it open a read view; with MariaDB snapshot isolation a locking write
    on a row that changed after that view fails with 1020, so the write starts a new transaction.
    """
    for attempt in (1, 2):
        frappe.db.commit()
        try:
            return write()
        except frappe.QueryDeadlockError as error:
            frappe.db.rollback()
            if attempt == 2:
                raise StateWriteFailed('Conversation state was not saved, please retry') from error


def ensure_state(contact: str) -> str:
    """The session user's state row for the contact. A new row gets a hash name, so no series counter is locked."""
    from relay_core.inbox import state_key
    key = state_key(contact)
    name = frappe.db.get_value(STATE, {'state_key': key}, 'name')
    if name:
        return name

    user, now = frappe.session.user, frappe.utils.now_datetime()
    frappe.db.bulk_insert(STATE, ['name', 'creation', 'modified', 'owner', 'modified_by', 'state_key', 'user', 'relay_contact'],
                          [(frappe.generate_hash(length=10), now, now, user, user, key, user, contact)], ignore_duplicates=True)
    # A locking read sees a row that a parallel request inserted after this snapshot.
    return frappe.db.get_value(STATE, {'state_key': key}, 'name', for_update=True)


def save_state(contact: str, values: dict) -> dict:
    """Write only the changed fields; last_read only moves forward. Return the changed fields."""
    name = ensure_state(contact)
    current = frappe.db.get_value(STATE, name, ['last_read', 'starred', 'folder', 'last_seen'], as_dict=True, for_update=True)
    if values.get('last_read') and (current.last_read or '') > values['last_read']:
        values = {field: value for field, value in values.items() if field != 'last_read'}
    changes = {field: value for field, value in values.items() if current.get(field) != value}

    now = frappe.utils.now_datetime()
    if changes or not current.last_seen or now - frappe.utils.get_datetime(current.last_seen) >= SEEN_REFRESH:
        frappe.db.set_value(STATE, name, dict(changes, last_seen=now), update_modified=bool(changes))
    if 'last_read' in changes:
        from relay_core.realtime import contact_changed
        contact_changed(contact, 'reads')
    frappe.db.commit()
    return changes


def save_chat_view(contact: str, channel: str, view: dict):
    """Keep the last position per channel view, at most 100 views; an unchanged position is not written."""
    name = ensure_state(contact)
    raw = frappe.db.get_value(STATE, name, 'chat_views', for_update=True)
    views = json.loads(raw) if isinstance(raw, str) else (raw or {})
    view_key = channel or 'combined'
    if views.get(view_key) == view and views.get('_active') == channel:
        return

    if view_key not in views and len(views) >= 100:
        views.pop(next(iter(views)))
    views['_active'] = channel
    views[view_key] = view
    frappe.db.set_value(STATE, name, 'chat_views', json.dumps(views), update_modified=False)
    frappe.db.commit()


def start_exact_reads(contact: str):
    """Mark the row as having exact read evidence; the old cursor becomes the baseline once."""
    name = ensure_state(contact)
    current = frappe.db.get_value(STATE, name, ['exact_reads', 'last_read'], as_dict=True, for_update=True)
    if not current.exact_reads:
        frappe.db.set_value(STATE, name, {'exact_reads': 1, 'read_baseline': current.last_read or ''}, update_modified=False)
