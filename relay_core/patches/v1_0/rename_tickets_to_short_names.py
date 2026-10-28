import hashlib
import json
import re

import frappe
from frappe.model.naming import make_autoname

OLD_PREFIX = 'RELAY-TKT-'
SERIES = 'TKT-'
DIGITS = 5
OLD_NAME = re.compile(r'RELAY-TKT-\d+')
QUOTED_OLD_NAME = re.compile(r'"(RELAY-TKT-\d+)"')
TICKET_REFERENCE = re.compile(r'("ticket"\s*:\s*)"(RELAY-TKT-\d+)"')
EPISODE_REFERENCES = re.compile(r'"delivery_episodes"\s*:\s*\[(?:\s*\[[^\[\]]*\]\s*,?)*\s*\]')
RENAME_COMMENT = re.compile(r'renamed from <strong>(RELAY-TKT-\d+)</strong> to <strong>(TKT-\d+)</strong>')


def execute():
    """Rename RELAY-TKT-0000000001 style tickets to TKT-00001 in creation order and continue the series after them."""
    if not frappe.db.table_exists('Relay Ticket'):
        return
    old_names = frappe.get_all('Relay Ticket', filters={'name': ['like', OLD_PREFIX + '%']},
                               order_by='creation asc, name asc', pluck='name')
    if not old_names:
        return
    mapping = {}
    for old in old_names:
        mapping[old] = next_short_name()
        # One search rebuild at the end instead of a queued job per ticket.
        frappe.rename_doc('Relay Ticket', old, mapping[old], force=True, merge=False, rebuild_search=False)
    repair_derived(mapping)
    frappe.enqueue('frappe.utils.global_search.rebuild_for_doctype', doctype='Relay Ticket')


def next_short_name() -> str:
    """Take the next number from the Frappe series, so new tickets continue after the renamed ones."""
    return make_autoname(SERIES + '.' + '#' * DIGITS, 'Relay Ticket')


def repair_derived(mapping: dict) -> None:
    """Rewrite the keys, hashes and stored JSON that hold ticket names; rename_doc updates only Link fields.

    Safe to run again. Notification event keys and sent message text keep the old names: they are
    provider idempotency keys and history."""
    if not mapping:
        return
    repair_subscriptions(mapping)
    rewrite_json('Relay Automation Run', 'search_plan', mapping)
    rewrite_json('Relay Message Action', 'payload', mapping)
    repair_flow_actions(mapping)
    repair_event_deliveries(mapping)
    repair_pending_notifications(mapping)
    repair_notification_logs(mapping)


def recovered_mapping() -> dict:
    """Old to new names from the comments that rename_doc wrote, for a site that ran the first version of this patch."""
    rows = frappe.get_all('Comment', filters={'reference_doctype': 'Relay Ticket', 'comment_type': 'Edit',
                                              'content': ['like', 'renamed from %' + OLD_PREFIX + '%']}, pluck='content')
    return dict(match.groups() for match in map(RENAME_COMMENT.search, rows) if match)


def repair_renamed_site() -> int:
    """One-off repair of a site that renamed its tickets before repair_derived existed. Return the ticket count."""
    mapping = recovered_mapping()
    missing = [new for new in mapping.values() if not frappe.db.exists('Relay Ticket', new)]
    if missing:
        raise ValueError(f'Renamed tickets are missing: {missing[:5]}')
    repair_derived(mapping)
    frappe.db.commit()
    return len(mapping)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def renamed_json(text: str, mapping: dict) -> str:
    """Rename only the "ticket" and "delivery_episodes" references and keep the rest of the text as stored.

    Message content and transport arguments stay unchanged: a resumed send must repeat what the provider accepted."""
    def rename(match):
        return json.dumps(mapping.get(match[1], match[1]))
    text = TICKET_REFERENCE.sub(lambda match: match[1] + json.dumps(mapping.get(match[2], match[2])), text)
    return EPISODE_REFERENCES.sub(lambda match: QUOTED_OLD_NAME.sub(rename, match[0]), text)


def stored_rows(doctype: str, field: str, extra=()) -> list:
    if not frappe.db.table_exists(doctype):
        return []
    return frappe.get_all(doctype, filters={field: ['like', '%' + OLD_PREFIX + '%']}, fields=['name', field, *extra])


def rewrite_json(doctype: str, field: str, mapping: dict) -> None:
    """Search plans (check_search compares the ticket), action payloads (ticket, delivery_episodes)."""
    for row in stored_rows(doctype, field):
        value = renamed_json(row[field], mapping)
        if value != row[field]:
            frappe.db.set_value(doctype, row.name, field, value, update_modified=False)


def repair_subscriptions(mapping: dict) -> None:
    """subscription_key is sha256('ticket:user') as in ticket_notifications.digest. A duplicate made after the
    rename already holds the new key, so the stale row is disabled to stop double notifications."""
    if not frappe.db.table_exists('Relay Ticket Subscription'):
        return
    rows = frappe.get_all('Relay Ticket Subscription', filters={'ticket': ['in', list(mapping.values())]},
                          fields=['name', 'ticket', 'user', 'subscription_key', 'enabled'])
    keys = {row.subscription_key for row in rows}
    for row in rows:
        key = sha256(row.ticket + ':' + row.user)
        if row.subscription_key == key:
            continue
        if key in keys:
            if row.enabled:
                frappe.db.set_value('Relay Ticket Subscription', row.name, 'enabled', 0, update_modified=False)
            continue
        frappe.db.set_value('Relay Ticket Subscription', row.name, 'subscription_key', key, update_modified=False)
        keys.add(key)


def repair_flow_actions(mapping: dict) -> None:
    """scope_fingerprint is sha256 of scope_snapshot (flows.actions._hash) and approval evidence repeats it.
    A fingerprint that did not match its snapshot stays as it is."""
    for row in stored_rows('Relay Flow Action', 'scope_snapshot', ('scope_fingerprint', 'approval_evidence')):
        snapshot = renamed_json(row.scope_snapshot, mapping)
        if snapshot == row.scope_snapshot:
            continue
        values = {'scope_snapshot': snapshot}
        if row.scope_fingerprint == sha256(row.scope_snapshot):
            values['scope_fingerprint'] = sha256(snapshot)
            if row.approval_evidence:
                values['approval_evidence'] = row.approval_evidence.replace(row.scope_fingerprint, values['scope_fingerprint'])
        frappe.db.set_value('Relay Flow Action', row.name, values, update_modified=False)


def delivery_hash(payload: str) -> str:
    """The content hash that business_events.delivery_scope checks before it sends."""
    return sha256(json.dumps(json.loads(payload), sort_keys=True))


def repair_event_deliveries(mapping: dict) -> None:
    """Delivery payloads keep ticket names in delivery_episodes; the content hash follows the payload."""
    for row in stored_rows('Relay Business Event Delivery', 'payload', ('payload_hash',)):
        payload = renamed_json(row.payload, mapping)
        if payload == row.payload:
            continue
        values = {'payload': payload}
        if row.payload_hash == delivery_hash(row.payload):
            values['payload_hash'] = delivery_hash(payload)
        frappe.db.set_value('Relay Business Event Delivery', row.name, values, update_modified=False)


def repair_pending_notifications(mapping: dict) -> None:
    """Unsent notification text names the ticket and links to it."""
    if not frappe.db.table_exists('Relay Ticket Notification'):
        return
    for row in frappe.get_all('Relay Ticket Notification', fields=['name', 'body'],
                              filters={'status': 'Pending', 'body': ['like', '%' + OLD_PREFIX + '%']}):
        body = OLD_NAME.sub(lambda match: mapping.get(match[0], match[0]), row.body)
        if body != row.body:
            frappe.db.set_value('Relay Ticket Notification', row.name, 'body', body, update_modified=False)


def repair_notification_logs(mapping: dict) -> None:
    """Notification Log.document_name is a Data field, so rename_doc leaves the bell links on the old name."""
    for row in frappe.get_all('Notification Log', fields=['name', 'document_name'],
                              filters={'document_type': 'Relay Ticket', 'document_name': ['like', OLD_PREFIX + '%']}):
        if row.document_name in mapping:
            frappe.db.set_value('Notification Log', row.name, 'document_name', mapping[row.document_name],
                                update_modified=False)
