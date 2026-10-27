"""Undo of one relay-import-whatsapp-core run, in short transactions that can be resumed.

Every change the import made is listed on its Relay Legacy Import markers (source_metadata.created).
Undo reverses exactly these changes, newest marker first, and keeps whatever live messages use.
"""
import time
from collections import Counter

import frappe

from relay_core import legacy
from relay_core import legacy_bundle as bundles
from relay_core.legacy_database import ACTIVITY, OPT_OUT, REACTION, RETRIES, refresh_activity, remove_unused_copies

CHUNK = 1000
PENDING = 'pending_files'


def undo(site_label: str, chunk: int = CHUNK) -> dict:
    removed = Counter()
    # An interrupted undo first finishes the file deletions it had committed.
    remove_pending_copies(site_label, removed)
    while transaction(lambda: remove_messages(site_label, chunk, removed), removed):
        remove_pending_copies(site_label, removed)
    for job in frappe.get_all('Relay Legacy Import', filters={'source_site': site_label},
                              fields=['name', 'relay_contact', 'source_metadata'], order_by='name desc'):
        transaction(lambda: remove_marker(job, removed), removed)
    from relay_core.queue_counts import invalidate
    invalidate()
    return dict(removed)


def transaction(work, removed: Counter):
    """Run and commit one step. A deadlock or lock timeout with live traffic rolls the step back
    (and its counts) and runs it again, up to RETRIES times."""
    for attempt in range(1, RETRIES + 1):
        counts = Counter(removed)
        try:
            result = work()
            frappe.db.commit()
            return result
        except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
            frappe.db.rollback()
            removed.clear()
            removed.update(counts)
            if attempt == RETRIES:
                raise
            time.sleep(attempt)


def remove_marker(job, removed: Counter) -> None:
    revert(job.relay_contact, legacy.object_value(job.source_metadata).get('created', {}), removed)
    frappe.db.delete('Relay Legacy Import', job.name)


def remove_messages(site_label: str, chunk: int, removed: Counter) -> bool:
    """Delete one chunk of imported messages, their Files and read receipts. The File URLs are recorded
    as pending in the same transaction (see remove_pending_copies). False when nothing is left."""
    messages = frappe.db.sql_list("""SELECT name FROM `tabRelay Message` WHERE legacy_source IS NOT NULL
        AND JSON_UNQUOTE(JSON_EXTRACT(legacy_data, '$.source_site')) = %s LIMIT %s""", (site_label, chunk))
    if not messages:
        return False
    files = {'attached_to_doctype': 'Relay Message', 'attached_to_name': ['in', messages]}
    urls = set(frappe.get_all('File', filters=files, pluck='file_url')) - {None}
    if urls:
        marker, metadata = pending_marker(site_label)
        save_pending(marker, metadata, sorted(urls | set(metadata.get(PENDING, []))))
    frappe.db.delete('File', files)
    # Users' read receipts of imported messages go with them.
    frappe.db.delete('Relay Message Read', {'message': ['in', messages]})
    frappe.db.delete('Relay Message', {'name': ['in', messages]})
    removed['messages'] += len(messages)
    return True


def pending_marker(site_label: str) -> tuple:
    """The oldest marker of the import, the last one undo deletes, holds the file deletions still to do."""
    row = frappe.db.get_value('Relay Legacy Import', {'source_site': site_label}, ['name', 'source_metadata'],
                              as_dict=True, order_by='name asc')
    if not row:
        frappe.throw(f'Imported messages of {site_label} have no Relay Legacy Import marker')
    return row.name, legacy.object_value(row.source_metadata)


def save_pending(marker: str, metadata: dict, urls: list) -> None:
    metadata = dict(metadata, **{PENDING: urls}) if urls else {key: value for key, value in metadata.items() if key != PENDING}
    frappe.db.set_value('Relay Legacy Import', marker, 'source_metadata', bundles.canonical(metadata), update_modified=False)


def remove_pending_copies(site_label: str, removed: Counter) -> None:
    """Delete the copied bytes of committed File deletions, then clear the record. Bytes go only after
    the commit, so a rolled-back step never loses a file still in use; a repeat deletes nothing twice."""
    if not frappe.db.exists('Relay Legacy Import', {'source_site': site_label}):
        return
    _, metadata = pending_marker(site_label)
    if not metadata.get(PENDING):
        return
    removed['media_files'] += remove_unused_copies(set(metadata[PENDING]))
    transaction(lambda: save_pending(*pending_marker(site_label), []), removed)


def revert(contact: str, created: dict, removed: Counter) -> None:
    """Reverse what one conversation import changed. Imported messages are already gone."""
    restore_reactions(created.get('reactions', {}), created.get('reactions_after', {}), removed)
    restore_opt_out(created.get('opt_out', {}), removed)
    for link in created.get('links', []):
        remove_link(link, removed)
    assignment = created.get('assignment')
    if assignment and not has_live_messages(contact, frappe.db.get_value('Relay Conversation Assignment', assignment, 'creation')):
        frappe.db.delete('Relay Conversation Assignment', assignment)
        removed['Relay Conversation Assignment'] += 1
    if created.get('endpoint'):
        remove_endpoint(created['endpoint'], removed)
    if created.get('relay_contact'):
        remove_contact(created, removed)
    elif frappe.db.exists('Relay Contact', contact):
        restore_activity(contact, created.get('activity'))


def has_live_messages(contact: str, since=None, **filters) -> bool:
    """A message, newer than `since` when given, still uses this contact. This import's messages are
    deleted first, so what is left is live (or from another import)."""
    filters = dict(filters, relay_contact=contact)
    if since:
        filters['creation'] = ['>', since]
    return bool(frappe.db.exists('Relay Message', filters))


def remove_link(name: str, removed: Counter) -> None:
    """Delete a Customer link the import added, unless a live chat of its Contact has used it since
    (a message newer than the link) or the Contact was changed after the import."""
    link = frappe.db.get_value('Dynamic Link', name, ['parent', 'creation'], as_dict=True)
    if not link:
        return
    changed = frappe.db.get_value('Contact', link.parent, 'modified')
    used = frappe.db.sql("""SELECT 1 FROM `tabRelay Message` m JOIN `tabRelay Contact` r ON r.name = m.relay_contact
        WHERE r.contact = %s AND m.creation > %s LIMIT 1""", (link.parent, link.creation))
    if used or (changed and frappe.utils.get_datetime(changed) > frappe.utils.get_datetime(link.creation)):
        removed['customer_links_kept_in_use'] += 1
        return
    frappe.db.delete('Dynamic Link', name)
    removed['customer_links'] += 1


def remove_endpoint(name: str, removed: Counter) -> None:
    endpoint = frappe.db.get_value('Relay Contact Endpoint', name, ['relay_contact', 'channel', 'endpoint'], as_dict=True)
    if not endpoint:
        return
    if has_live_messages(endpoint.relay_contact, channel=endpoint.channel, sender_endpoint=endpoint.endpoint):
        removed['endpoints_kept_with_new_messages'] += 1
        return
    frappe.db.delete('Relay Contact Endpoint', name)
    removed['Relay Contact Endpoint'] += 1


def remove_contact(created: dict, removed: Counter) -> None:
    """Delete the Relay Contact (and Contact) the import made, unless live messages or other endpoints use it."""
    contact = created['relay_contact']
    if has_live_messages(contact) or frappe.db.exists('Relay Contact Endpoint', {'relay_contact': contact}):
        removed['contacts_kept_with_new_messages'] += 1
        restore_activity(contact, None)
        return
    frappe.db.delete('Relay Contact', contact)
    removed['Relay Contact'] += 1
    for doctype in ('Relay Conversation Assignment', 'Relay Conversation State'):
        frappe.db.delete(doctype, {'relay_contact': contact})
    person = created.get('contact')
    if person and not frappe.db.exists('Relay Contact', {'contact': person}):
        frappe.db.delete('Contact', person)
        frappe.db.delete('Contact Phone', {'parenttype': 'Contact', 'parent': person})
        frappe.db.delete('Dynamic Link', {'parenttype': 'Contact', 'parent': person})
        removed['Contact'] += 1


def restore_activity(contact: str, activity: dict | None) -> None:
    """Put back the directory activity from before the import, then let newer live messages move it."""
    values = {field: (activity or {}).get(field) for field in ACTIVITY}
    if values['last_message'] and not frappe.db.exists('Relay Message', values['last_message']):
        values = dict.fromkeys(ACTIVITY)
    frappe.db.set_value('Relay Contact', contact, values, update_modified=False)
    if has_live_messages(contact):
        refresh_activity(contact)


def restore_opt_out(changes: dict, removed: Counter) -> None:
    """Put back an existing endpoint's opt-out choice, unless it changed again after the import."""
    for name, change in changes.items():
        current = frappe.db.get_value('Relay Contact Endpoint', name, OPT_OUT, as_dict=True)
        if current and all(str(current[field]) == str(change['after'][field]) for field in OPT_OUT):
            frappe.db.set_value('Relay Contact Endpoint', name, change['before'], update_modified=False)
            removed['opt_out_restored'] += 1


def restore_reactions(saved: dict, after: dict, removed: Counter) -> None:
    """Put back a live message's reactions and update history, unless they changed again after the import."""
    for name, values in saved.items():
        current = frappe.db.get_value('Relay Message', name, REACTION, as_dict=True)
        if not current:
            continue
        if name in after and all(str(current[field]) == str(after[name][field]) for field in REACTION):
            frappe.db.set_value('Relay Message', name, values, update_modified=False)
            removed['reactions_restored'] += 1
        else:
            removed['reactions_kept_changed'] += 1

