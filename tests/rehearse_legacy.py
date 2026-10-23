"""Explicit local rehearsal. Source is protected by a read-only DB transaction.

Run with bench Python, FRAPPE_STREAM_LOGGING=1, PYTHONDONTWRITEBYTECODE=1 and
PYTHONPATH pointing at the worktree. Private bundles/reports stay outside git.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from unittest.mock import patch

import frappe
from relay_core import legacy, legacy_bundle
from relay_core.legacy_metadata import direct_document, prepare_import


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['export', 'import', 'replay', 'verify'])
    parser.add_argument('--directory', required=True)
    parser.add_argument('--frozen', action='store_true', help='Full final export; requires all source writers frozen')
    args = parser.parse_args()
    root = Path(args.directory); root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chdir('/home/sakthi/development/pilot/benches/version_16/sites')
    started = time.monotonic()
    frappe.init(site='sales-prod.site' if args.mode == 'export' else 'yrp.site'); frappe.connect()
    if args.mode == 'export':
        frappe.db.sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
    frappe.set_user('Administrator'); frappe.flags.mute_emails = True
    try:
        if args.mode == 'export':
            watermark = str(frappe.db.sql('SELECT CURRENT_TIMESTAMP(6)')[0][0])
            source_count = frappe.db.count(legacy.SOURCE)
            index = {'source_count': source_count, 'watermark': watermark, 'segments': [], 'types': {}, 'files': 0, 'bytes': 0, 'unavailable': 0}
            for i, conversation in enumerate(frappe.get_all('WhatsApp Core Conversation', pluck='name', order_by='name', limit_page_length=0)):
                after = upper = None
                while True:
                    path = root / (str(len(index['segments'])) + '.zip')
                    result = legacy_bundle.export_conversation(conversation, path, after=after, upper=upper,
                        watermark=watermark, frozen=args.frozen)
                    index['segments'].append(path.name)
                    bundle = legacy_bundle.decode(path)
                    for row in bundle['rows']:
                        index['types'][row.message_type] = index['types'].get(row.message_type, 0) + 1
                    for entries in bundle['files'].values():
                        for entry in entries:
                            index['files'] += 1
                            index['bytes'] += entry.get('size', 0)
                            index['unavailable'] += entry.get('availability') != 'available'
                    after = result['next']; upper = result['upper']
                    if not after: break
                if (i + 1) % 100 == 0: print('exported conversations', i + 1, flush=True)
            assert sum(index['types'].values()) == source_count
            index['seconds'] = round(time.monotonic() - started, 2)
            (root / 'index.json').write_text(json.dumps(index, indent=2))
            print(json.dumps({k: v for k, v in index.items() if k != 'segments'}, indent=2), flush=True)
            frappe.db.rollback()
            return
        index = json.loads((root / 'index.json').read_text())
        # All mutation paths in this rehearsal are history-only. Any attempted job/send fails.
        with patch.object(frappe, 'enqueue', side_effect=AssertionError('History enqueued work')), \
             patch.object(frappe, 'sendmail', side_effect=AssertionError('History sent email')), \
             patch('relay_core.whatsapp.client', side_effect=AssertionError('History called provider')):
            if args.mode in ('import', 'replay'):
                channel = frappe.db.get_value('Relay Channel', {'account': 'local-only-sales-history-rehearsal'}, 'name')
                if not channel:
                    channel = direct_document('Relay Channel', dict(channel='WhatsApp', account='local-only-sales-history-rehearsal', enabled=0)).name
                users = {name: name for name in frappe.get_all('User', pluck='name', limit_page_length=0)}
                jobs = []; totals = Counter()
                for i, segment in enumerate(index['segments']):
                    path = root / segment; bundle = legacy_bundle.decode(path)
                    filename = 'local-only-sales-history-' + bundle['sha256'] + '.zip'
                    target = Path(frappe.get_site_path('private', 'files', filename))
                    if not target.exists(): shutil.copyfile(path, target); target.chmod(0o600)
                    file_name = 'relay-bundle-' + bundle['sha256']
                    if not frappe.db.exists('File', file_name):
                        direct_document('File', dict(file_name=filename, file_url='/private/files/' + filename,
                            is_private=1, file_size=target.stat().st_size), file_name)
                    job = prepare_import(bundle['manifest'], channel, source_bundle=file_name, user_map=users)
                    frappe.db.commit()
                    while True:
                        result = legacy.run_batch(job.name)
                        if result['status'] == 'Completed': break
                    jobs.append(job.name)
                    for key in ('imported', 'skipped', 'updated', 'mismatches'): totals[key] += result.get(key, 0)
                    if (i + 1) % 100 == 0: print(args.mode, i + 1, dict(totals), flush=True)
                output = dict(totals, seconds=round(time.monotonic() - started, 2), jobs=jobs, channel=channel)
                (root / (args.mode + '.json')).write_text(json.dumps(output, indent=2))
                print(json.dumps({k: v for k, v in output.items() if k != 'jobs'}, indent=2), flush=True)
            else:
                state = json.loads((root / ('replay.json' if (root / 'replay.json').exists() else 'import.json')).read_text())
                mismatches = []; types = Counter(); statuses = Counter(); total_bytes = 0; checked = 0
                available = unavailable = 0
                for segment in index['segments']:
                    bundle = legacy_bundle.decode(root / segment)
                    for row in bundle['rows']:
                        target = frappe.db.get_value('Relay Message', {'source_key': legacy.source_key(bundle['manifest']['source_site'], row.name)},
                            ['name', 'legacy_data', 'legacy_checksum', 'message_data', 'status', 'legacy_author', 'legacy_triage'], as_dict=True)
                        if not target:
                            mismatches.append({'source': row.name, 'kind': 'missing'}); continue
                        checked += 1; types[row.message_type] += 1; statuses[target.status] += 1
                        if not (target.legacy_checksum == legacy_bundle.checksum(row) == legacy_bundle.checksum(json.loads(target.legacy_data)['row'])):
                            mismatches.append({'source': row.name, 'kind': 'payload'})
                        if target.status != legacy.status(row) or target.legacy_author != row.owner or not target.legacy_triage:
                            mismatches.append({'source': row.name, 'kind': 'projection'})
                        for entry in json.loads(target.message_data).get('legacy_attachments', []):
                            if entry['availability'] != 'available': unavailable += 1; continue
                            file = frappe.get_doc('File', entry['attachment'])
                            with open(file.get_full_path(), 'rb') as handle:
                                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
                            size = Path(file.get_full_path()).stat().st_size
                            total_bytes += size; available += 1
                            if digest != entry['sha256'] or size != entry['size']:
                                mismatches.append({'source': row.name, 'kind': 'media'})
                reviews = Counter()
                for name in state['jobs']:
                    report = json.loads(frappe.db.get_value('Relay Legacy Import', name, 'reconcile_report'))
                    reviews.update(item['kind'] for item in report.get('mismatches', []))
                actual_count = frappe.db.count('Relay Message', {'channel': state['channel']})
                if actual_count != checked: mismatches.append({'kind': 'identity_parity', 'detail': 'Unexpected target messages'})
                result = dict(source=index['source_count'], target=checked, target_total=actual_count, types=dict(types), statuses=dict(statuses),
                    review_categories=dict(reviews), business_triage=frappe.db.count('Relay Message', {'channel': state['channel'], 'legacy_triage': 1}),
                    attachment_bytes=total_bytes, available_attachments=available, unavailable_media=unavailable,
                    mismatches=mismatches, seconds=round(time.monotonic() - started, 2))
                assert checked == index['source_count'] and not mismatches, result
                (root / 'verify.json').write_text(json.dumps(result, indent=2)); print(json.dumps(result, indent=2))
    finally:
        frappe.destroy()


if __name__ == '__main__': main()
