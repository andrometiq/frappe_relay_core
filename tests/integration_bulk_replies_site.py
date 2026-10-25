"""Bulk campaign reply links and counters on a real site: replies before the provider ID, cancelled campaigns,
the Redis refresh mark, and the reply lookup plans with the real destination + provider ID index on a scratch copy.
Run from the bench sites folder: PYTHONPATH=<worktree>:<worktree>/tests CI=1 ../env/bin/python -B <this file>
"""
import json
import secrets
from pathlib import Path
from unittest.mock import patch
import frappe
from frappe import _dict
from site_labels import phone

SITE = 'yrp.site'
frappe.init(site=SITE)
frappe.connect()
frappe.set_user('Administrator')
from relay_core import bulk_updates  # noqa: E402
from relay_core.automation.service import internal_save  # noqa: E402
assert Path(bulk_updates.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1]), 'Run with this checkout first on PYTHONPATH'

words = '-'.join(secrets.choice(('cedar', 'maple', 'birch', 'willow', 'olive', 'alder')) for _ in range(3))
account, title = 'replies-' + words, 'Reply link check ' + words
RECIPIENT = 'Relay Campaign Recipient'
ROWS = {'early': ('Queued', 1, ''), 'quoted': ('Read', 1, 'wamid.quoted.' + words), 'failed': ('Failed', 1, 'wamid.failed.' + words),
        'unsent': ('Pending', 0, ''), 'held': ('Queued', 1, '')}
number = {kind: phone(f'{title} {kind}') for kind in ROWS}
key = {kind: f'bulk-replies-{words}-{kind}' for kind in ROWS}
channel = None


def update(kind, status, message_id):
    rows = [{'id': len(kind), 'key': key[kind], 'state': 'submitted', 'message_id': message_id, 'status': status,
             'updated_at': '2026-10-26T10:00:00Z'}]
    with patch.object(bulk_updates, 'connection_value', return_value=account), patch.object(bulk_updates, 'changed'):
        bulk_updates.project_batch(_dict(name='no-such-event', account=account), rows)
    frappe.db.commit()


def reply(kind, quoted=None):
    row = {'id': f'wamid.reply.{kind}.{words}', 'from': number[kind],
           'provider_context': {'reply_to_message_id': quoted} if quoted else {}}
    with patch.object(bulk_updates, 'changed'), patch.object(bulk_updates, 'reply_window_open', return_value=True):
        linked = bulk_updates.link_reply(row)
    frappe.db.commit()
    return linked


def counts():
    return bulk_updates.recount(title)['counts']


def plan(query, values):
    return frappe.db.sql('EXPLAIN ' + query, values, as_dict=True)


try:
    channel = frappe.get_doc({'doctype': 'Relay Channel', 'channel': 'WhatsApp', 'account': account, 'enabled': 1}).insert()
    internal_save(frappe.get_doc({'doctype': 'Relay Campaign', 'title': title, 'channel': channel.name, 'operation': 'templates.send',
        'template_name': 'notice', 'language': 'en', 'status': 'Running', 'account': account, 'reply_window_hours': 72,
        'started_at': frappe.utils.now_datetime(), 'arguments': json.dumps({'template': {'name': 'notice'}, 'fields': []}),
        'request_key': 'bulk-replies-' + secrets.token_hex(8)}), new=True)
    now = frappe.utils.now()
    frappe.db.bulk_insert(RECIPIENT, ('name', 'creation', 'modified', 'owner', 'modified_by', 'campaign', 'recipient_key', 'request_key',
                          'status', 'attempted', 'provider_id', 'delivery_id', 'destination', 'sheet_row'),
                          [(key[k], now, now, 'Administrator', 'Administrator', title, key[k], key[k], status, attempted, provider,
                            str(row), number[k], row + 2) for row, (k, (status, attempted, provider)) in enumerate(ROWS.items())])
    frappe.db.commit()

    assert reply('early', quoted='wamid.early.' + words) == key['early'], 'A reply before the provider ID links by number'
    assert counts()['replied'] == 0, 'Not counted until Hub reports the provider ID'
    update('early', 'read', 'wamid.early.' + words)
    assert counts()['replied'] == 1, counts()
    assert reply('quoted', quoted='wamid.quoted.' + words) == key['quoted']
    assert reply('failed') is None and reply('unsent') is None, 'Failed and never-sent rows take no reply'
    reply('early')  # A second reply from the same number changes nothing.
    assert counts()['replied'] == 2, counts()

    frappe.db.set_value('Relay Campaign', title, 'status', 'Cancelled')
    frappe.db.commit()
    before = counts()
    update('held', 'read', 'wamid.held.' + words)  # Hub could not cancel it and sent it.
    after = counts()
    assert (before['queued'], before['read'], after['queued'], after['read']) == (2, 2, 1, 3), (before, after)
    assert frappe.db.get_value('Relay Campaign', title, ['status', 'read_count']) == ('Cancelled', 3)

    with patch.object(frappe, 'enqueue') as enqueue:
        bulk_updates.mark(title)
        bulk_updates.mark(title)  # Already marked: the queued refresh covers it.
        assert enqueue.call_count == 1, enqueue.call_args_list
        frappe.cache.srem(bulk_updates.DIRTY, title)
        bulk_updates.mark(title)
        assert enqueue.call_count == 2
    frappe.cache.srem(bulk_updates.DIRTY, title)

    frappe.db.sql(f'CREATE TEMPORARY TABLE scratch_recipient LIKE `tab{RECIPIENT}`')
    frappe.db.sql('''INSERT INTO scratch_recipient (name, creation, modified, campaign, destination, provider_id, attempted, status)
        SELECT CONCAT('scratch-', seq), NOW(6), NOW(6), %s, CONCAT('9190', LPAD(seq MOD 5000, 8, '0')),
        IF(seq MOD 3, CONCAT('wamid.scratch.', seq), ''), 1, 'Read' FROM seq_1_to_20000''', title)
    frappe.db.sql('ANALYZE TABLE scratch_recipient')
    target = '919000000042'
    send = plan('''SELECT 1 FROM scratch_recipient r JOIN `tabRelay Campaign` c ON c.name=r.campaign
        WHERE c.channel=%(channel)s AND r.destination=%(endpoint)s
        AND (r.provider_id=%(reply)s OR (r.attempted=1 AND IFNULL(r.provider_id, '')='')) LIMIT 1''',
        dict(channel=channel.name, endpoint=target, reply='wamid.scratch.42'))
    link = plan(f'''SELECT r.name, r.campaign FROM scratch_recipient r JOIN `tabRelay Campaign` c ON c.name=r.campaign
        WHERE r.destination=%s AND r.attempted=1 AND r.status IN {bulk_updates.REACHABLE}
        AND c.started_at >= NOW() - INTERVAL c.reply_window_hours HOUR ORDER BY r.creation DESC LIMIT 1''', target)
    for name, rows in (('campaign_send', send), ('link_reply', link)):
        recipient = next(row for row in rows if row.table == 'r')
        print(name, [(row.table, row.type, row.key, row.rows) for row in rows])
        assert recipient.key == 'destination_provider' and int(recipient.rows) <= 10, (name, rows)
        assert next(row for row in rows if row.table == 'c').key == 'PRIMARY', (name, rows)
    print('PASS bulk replies: a reply before the provider ID counts once Hub reports it, quoted replies link, failed and '
          'unsent rows take none, a cancelled campaign keeps counting Hub updates, one Redis mark per refresh, and both '
          'reply lookups use destination_provider then the campaign primary key over 20,000 scratch rows')
finally:
    frappe.db.rollback()
    frappe.db.sql('DROP TEMPORARY TABLE IF EXISTS scratch_recipient')
    frappe.db.delete(RECIPIENT, {'campaign': title})
    if frappe.db.exists('Relay Campaign', title):
        frappe.delete_doc('Relay Campaign', title, ignore_permissions=True, force=True)
    if channel:
        frappe.delete_doc('Relay Channel', channel.name, ignore_permissions=True, force=True)
    frappe.db.commit()
    frappe.destroy()
