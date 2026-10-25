"""Coalesced Hub outcomes, reply links and throttled progress for bulk campaigns."""
import time
import frappe
from relay_core.settings import value as connection_value

RECIPIENT = 'Relay Campaign Recipient'
RANK = {'Pending': 0, 'Queued': 1, 'Uncertain': 1, 'Cancelled': 2, 'Sent': 3, 'Failed': 4, 'Delivered': 5, 'Read': 6}
STATUS = {'sent': 'Sent', 'delivered': 'Delivered', 'read': 'Read', 'failed': 'Failed'}
STATE = {'queued': 'Queued', 'submitting': 'Queued', 'submitted': 'Sent', 'rejected': 'Failed',
         'uncertain': 'Uncertain', 'cancelled': 'Cancelled'}
REACHABLE = "('Pending', 'Queued', 'Uncertain', 'Sent', 'Delivered', 'Read')"  # Rows a reply may answer once attempted.
PROGRESS_SECONDS = 3
REPLY_GATE = 'relay-bulk-reply-until'
DIRTY = 'relay-bulk-dirty'
PUBLISHED = 'relay-bulk-progress-at:'


def target(row):
    return STATUS[row['status']] if row['status'] else STATE[row['state']]


def lower(status):
    return tuple(name for name, rank in RANK.items() if rank < RANK[status])


def reason(error):
    if not error:
        return ''
    detail = ': '.join(part for part in (error.get('title'), error.get('message')) if part)
    return (f"Meta error {error['code']}" + (f': {detail}' if detail else '') if error.get('code') else detail)[:500]


def project_batch(event, rows):
    """Monotonic per-row apply; the status guard lives in SQL so replays and races cannot regress."""
    if event.account != connection_value('relay_hub_account'):
        raise ValueError('Bulk updates belong to another account')
    timeline = []
    for row in sorted(rows, key=lambda item: item['key']):
        status = target(row)
        error = row.get('error') or {}
        failed = status == 'Failed'
        timeline.append({'key': row['key'], 'status': status, 'message_id': row['message_id'], 'reason': reason(error)})
        frappe.db.sql(f'''UPDATE `tab{RECIPIENT}` SET status=%(status)s,
            provider_id=IF(%(message)s='', provider_id, %(message)s), delivery_id=%(delivery)s,
            error_code=IF(%(failed)s, %(code)s, error_code), reason=IF(%(failed)s, %(reason)s, reason), modified=NOW(6)
            WHERE request_key=%(key)s AND status IN %(lower)s''',
            dict(status=status, message=row['message_id'], delivery=str(row['id']), failed=failed,
                 code=error.get('code') or 0, reason=reason(error), key=row['key'], lower=lower(status)))
    names = frappe.get_all(RECIPIENT, filters={'request_key': ['in', [row['key'] for row in rows]]},
                           pluck='campaign', distinct=True, limit_page_length=0)
    from relay_core.bulk_timeline import apply
    apply(timeline)
    frappe.db.set_value('Relay Hub Event', event.name, 'projection_status', 'Projected')
    for name in names:
        changed(name)  # Also after cancel: rows Hub still sent keep moving, and so do the counters.


def open_reply_window(hours):
    until = time.time() + int(hours or 72) * 3600 + 86400
    current = frappe.utils.flt(frappe.cache.get_value(REPLY_GATE))
    frappe.cache.set_value(REPLY_GATE, max(until, current))


def reply_window_open():
    until = frappe.cache.get_value(REPLY_GATE)
    if until is None:
        latest = frappe.db.sql('''SELECT MAX(UNIX_TIMESTAMP(COALESCE(finished_at, NOW())) + reply_window_hours * 3600)
            FROM `tabRelay Campaign` WHERE operation='templates.send' AND started_at IS NOT NULL''')[0][0]
        until = float(latest or 0)
        frappe.cache.set_value(REPLY_GATE, until, expires_in_sec=600)
    return float(until) > time.time()


def link_reply(row):
    """Link an inbound WhatsApp message to the campaign row it answers: the row whose provider ID it quotes,
    else the newest row Hub holds or sent to that number in an open reply window. A reply can arrive before
    Hub reports the provider ID; recount counts it once that ID is known."""
    if not reply_window_open():
        return None
    reply_to = (row.get('provider_context') or {}).get('reply_to_message_id')
    match = None
    if reply_to:
        match = frappe.db.sql(f'SELECT name, campaign FROM `tab{RECIPIENT}` WHERE provider_id=%s LIMIT 1', reply_to, as_dict=True)
    if not match:
        match = frappe.db.sql(f'''SELECT r.name, r.campaign FROM `tab{RECIPIENT}` r JOIN `tabRelay Campaign` c ON c.name=r.campaign
            WHERE r.destination=%s AND r.attempted=1 AND r.status IN {REACHABLE}
            AND c.started_at >= NOW() - INTERVAL c.reply_window_hours HOUR ORDER BY r.creation DESC LIMIT 1''',
            row['from'], as_dict=True)
    if not match:
        return None
    frappe.db.sql(f'UPDATE `tab{RECIPIENT}` SET replied_at=NOW(6), reply_provider_id=%s WHERE name=%s AND replied_at IS NULL',
                  (row['id'], match[0].name))
    changed(match[0].campaign)
    return match[0].name


def changed(name):
    """After commit, mark the campaign; the change that marks it enqueues one trailing refresh."""
    frappe.db.after_commit.add(lambda: mark(name))


def mark(name):
    if frappe.cache.execute_command('SADD', frappe.cache.make_key(DIRTY), name):
        frappe.enqueue('relay_core.bulk_updates.refresh', name=name, queue='short', timeout=120)


def refresh(name):
    """Single owner of campaign counters, completion and progress events, at most one per PROGRESS_SECONDS.
    It waits out the rest of that time instead of dropping the change, so the last change is always published."""
    delay = PROGRESS_SECONDS - (time.time() - frappe.utils.flt(frappe.cache.get_value(PUBLISHED + name)))
    if delay > 0:
        time.sleep(delay)
    frappe.db.commit()  # A fresh snapshot: count what committed during the wait.
    frappe.cache.srem(DIRTY, name)
    publish(name, recount(name))
    frappe.cache.set_value(PUBLISHED + name, time.time(), expires_in_sec=60)


def recover():
    """Refresh campaigns a stopped worker left marked."""
    for name in list(frappe.cache.smembers(DIRTY))[:50]:
        name = name.decode() if isinstance(name, bytes) else name
        frappe.enqueue('relay_core.bulk_updates.refresh', name=name, queue='short', timeout=120)


def tally(rows):
    by_status = {row[0]: row[1] for row in rows}
    total = sum(by_status.values())

    def count(*statuses):
        return sum(by_status.get(status, 0) for status in statuses)

    return {'total': total - count('Skipped'), 'skipped': count('Skipped'),
            'queued': count('Pending', 'Dispatching', 'Queued'),
            'sent': count('Sent', 'Submitted', 'Delivered', 'Read'), 'delivered': count('Delivered', 'Read'),
            'read': count('Read'), 'failed': count('Failed', 'Rejected'), 'replied': sum(row[2] for row in rows)}


def recount(name):
    # A reply counts once Hub reports the provider ID of a send that did not fail.
    rows = frappe.db.sql(f'''SELECT status, COUNT(*), CAST(SUM(replied_at IS NOT NULL AND IFNULL(provider_id, '')!=''
        AND status NOT IN ('Failed', 'Rejected')) AS SIGNED)
        FROM `tab{RECIPIENT}` WHERE campaign=%s GROUP BY status''', name)
    counts = tally([(status, int(total), int(replied or 0)) for status, total, replied in rows])
    values = {key + '_count': value for key, value in counts.items()}
    status = frappe.db.get_value('Relay Campaign', name, 'status')
    if status == 'Running' and counts['queued'] == 0:
        values.update(status='Completed', finished_at=frappe.utils.now_datetime())
    frappe.db.set_value('Relay Campaign', name, values, update_modified=False)
    frappe.db.commit()
    return {'counts': counts, 'status': values.get('status', status)}


def publish(name, progress):
    frappe.publish_realtime('relay_campaign_progress', dict(progress, name=name),
                            doctype='Relay Campaign', docname=name)
