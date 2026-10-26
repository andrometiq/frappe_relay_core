"""Explicit yrp.site receipt/ingress/drain benchmark; retain local-only fixtures.

Run with bench Python -B, --receipts 12000 --output /tmp/relay-status-before.json.
Uses real signed ingress, SQL transactions, projection and automation handlers.
Only external delivery, realtime publication and RQ dispatch are intercepted.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import queue as queues
import threading
import time
import traceback
from types import SimpleNamespace
from unittest.mock import patch

os.environ['FRAPPE_STREAM_LOGGING'] = '1'
import frappe
from relay_core import inbound, whatsapp
from relay_core.automation import projection, queue
from relay_core.message_updates import provider_key

SITES = '/home/sakthi/development/pilot/benches/version_16/sites'
SECRET = 'local-status-contention-fixture-secret'


def connect():
    frappe.init(site='yrp.site', sites_path=SITES)
    frappe.connect()
    assert frappe.local.site == 'yrp.site' and frappe.conf.developer_mode
    frappe.set_user('Administrator')
    frappe.flags.mute_emails = True
    frappe.conf.relay_automation_enabled = 0


def insert(doctype, **values):
    return frappe.get_doc(dict(doctype=doctype, **values)).insert(ignore_permissions=True)


def signed_call(method, payload):
    raw = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(SECRET.encode(), timestamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    frappe.local.request = SimpleNamespace(get_data=lambda: raw, headers={
        'X-Relay-Timestamp': timestamp, 'X-Relay-Signature': signature})
    result = method()
    frappe.db.commit()
    return result


def envelope(value):
    return {'entry': [{'changes': [{'value': value}]}]}


def verify_snapshot_conflict(tag, receipt, work):
    """Force the actual MariaDB 1020, without injecting a database exception."""
    original = inbound.insert_event
    caller = threading.get_ident()
    attempts, conflicts = [], []

    def advance_series():
        connect()
        try:
            signed_call(inbound.receive_statuses, {'account': tag, 'statuses': [dict(receipt, position=1)]})
        finally:
            frappe.destroy()

    def insert_after_concurrent_commit(*args, **kwargs):
        if threading.get_ident() != caller:
            return original(*args, **kwargs)
        attempts.append(True)
        if len(attempts) == 1:
            frappe.db.sql('select current from tabSeries where name=%s', ('RELAY-EVT-',))
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(advance_series).result(timeout=10)
        try:
            return original(*args, **kwargs)
        except frappe.QueryDeadlockError as exc:
            conflicts.append(str(exc))
            raise

    with patch.object(inbound, 'insert_event', side_effect=insert_after_concurrent_commit):
        signed_call(inbound.receive_statuses, {'account': tag, 'statuses': [receipt]})
    assert len(attempts) == 2 and len(conflicts) == 1
    assert '1020' in conflicts[0] and 'tabSeries' in conflicts[0]
    assert work.qsize() == 2, 'Each committed event should schedule projection once'
    while not work.empty():
        projection.drain(work.get_nowait())
    return True


def verify_recovery(tag, channel, endpoint, work):
    """A failed attempt may already have inserted and projected its message."""
    provider = f'wamid.{tag}.rollback'
    payload = {'account': tag, 'events': [{'id': int(time.time_ns() // 1000), 'payload': envelope({
        'messages': [{'id': provider, 'from': endpoint, 'type': 'text',
                      'text': {'body': f'{tag}: rollback quantity 13, amount 1300'}}]})}]}
    original = inbound.insert_event
    attempts = []

    def fail_after_insert(*args, **kwargs):
        doc = original(*args, **kwargs)
        attempts.append(doc.name)
        if len(attempts) == 1:
            raise frappe.QueryDeadlockError(1020, 'Injected conflict after inline projection')
        return doc

    # Exclude installed workers while checking the pending/ack transaction.
    lock = queue.AUTOMATION.lock_name
    assert frappe.db.sql('select get_lock(%s, 0)', (lock,))[0][0]
    try:
        with patch.object(inbound, 'insert_event', side_effect=fail_after_insert), \
                patch.object(queue, 'wake') as wake:
            signed_call(inbound.receive, payload)
            assert len(attempts) == 2
            assert wake.call_count == 1, 'Rolled-back after_commit hook survived'
            signed_call(inbound.receive, payload)
            assert len(attempts) == 2, 'Replay inserted a second event'
            assert wake.call_count == 1
        assert work.empty(), 'Inline projection unexpectedly queued'
        assert frappe.db.count('Relay Hub Event', {'event_key': f"{tag}:{payload['events'][0]['id']}"}) == 1
        found = frappe.get_all('Relay Message', filters={'channel': channel, 'provider_id': provider}, pluck='name')
        assert len(found) == 1
        name = found[0]
        assert frappe.db.get_value('Relay Message', name, 'automation_status') == 'Pending'

        def contend():
            connect()
            try:
                return queue.drain()
            finally:
                frappe.destroy()
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(contend).result(timeout=10) == 0

        # All real handlers run. Rollback must undo acknowledgement, then a
        # committed retry must exclude replay of those handlers.
        queue._process(name)
        assert frappe.db.get_value('Relay Message', name, 'automation_status') == 'Complete'
        frappe.db.rollback()
        assert frappe.db.get_value('Relay Message', name, 'automation_status') == 'Pending'
        queue._process(name)
        frappe.db.commit()
        get_attr = frappe.get_attr
        def no_replay(path):
            assert path not in queue.HANDLERS, 'Completed hooks replayed'
            return get_attr(path)
        with patch.object(frappe, 'get_attr', side_effect=no_replay):
            queue._process(name)
        frappe.db.commit()
    finally:
        frappe.db.sql('select release_lock(%s)', (lock,))
    return {'partial_insert_rolled_back': True, 'one_committed_wake': True,
            'replay_deduplicated': True, 'drain_rollback_recovered': True,
            'completed_hooks_not_replayed': True, 'concurrent_drain_excluded': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipts', type=int, default=12000)
    parser.add_argument('--output', required=True)
    parser.add_argument('--pace', type=float, default=1, help='Seconds between Hub status batches')
    parser.add_argument('--verify', action='store_true', help='Exercise rollback and replay after the load run')
    args = parser.parse_args()
    assert args.receipts > 0 and Path(args.output).resolve().is_relative_to('/tmp')
    os.chdir(SITES)
    connect()
    tag = 'local-status-' + str(time.time_ns())
    work = queues.Queue()
    errors, conflicts, latencies, timings, spans = [], [], [], [], []
    queries = defaultdict(Counter)
    durations = defaultdict(Counter)
    finished = threading.Event()
    receiving = threading.Event()

    def scoped(doctype, *args, **kwargs):
        # The drains see only this run's events, never other local Pending rows.
        if doctype == 'Relay Hub Event' and isinstance(kwargs.get('filters'), list):
            kwargs['filters'] = kwargs['filters'] + [['account', '=', tag]]
        return get_all(doctype, *args, **kwargs)

    def settings(key):
        return {'relay_hub_account': tag, 'relay_callback_secret': SECRET}.get(key)

    def error(lane, exc):
        errors.append({'lane': lane, 'type': type(exc).__name__, 'detail': str(exc), 'frames': [
            f'{Path(f.filename).name}:{f.lineno}:{f.name}' for f in traceback.extract_tb(exc.__traceback__)]})

    def profile(lane):
        original = frappe.db.sql
        def sql(query, *values, **kwargs):
            statement = str(query)
            # Keep only the statement template, never its parameter values.
            key = statement.split(' WHERE ')[0].split(' where ')[0]
            if len(key) > 180:
                key = key[:180]
            start = time.perf_counter()
            try:
                return original(query, *values, **kwargs)
            except frappe.QueryDeadlockError as exc:
                conflicts.append({'lane': lane, 'detail': str(exc)})
                raise
            finally:
                queries[lane][key] += 1
                durations[lane][key] += time.perf_counter() - start
        frappe.db.sql = sql

    get_all = frappe.get_all
    wakes = [patch.object(signal, 'wake', side_effect=lambda kind=kind: work.put(kind))
             for kind, signal in projection.DRAINS.items()]
    with patch.object(frappe, 'enqueue', side_effect=AssertionError('Unexpected enqueue')), \
         patch.object(frappe, 'get_all', side_effect=scoped), wakes[0], wakes[1], \
         patch.object(frappe, 'publish_realtime'), patch.object(queue, 'wake'), \
         patch.object(inbound, 'connection_value', side_effect=settings), \
         patch.object(whatsapp, 'client', side_effect=AssertionError('External delivery forbidden')):
        assert not frappe.db.exists('Relay Message', {'automation_status': 'Pending'})
        assert not frappe.db.exists('Notification', {'enabled': 1, 'document_type': ['in',
            ['Relay Message', 'Relay Hub Event', 'Relay Channel', 'Relay Contact Endpoint']]})
        base = frappe.get_doc('Relay Contact', {'display_name': ['like', 'Local simulation%'], 'automation_paused': 1})
        person = frappe.get_doc('Contact', base.contact)
        assert len(person.links) == 1
        business = (person.links[0].link_doctype, person.links[0].link_name)
        channel = insert('Relay Channel', channel='WhatsApp', account=tag, enabled=1)
        endpoint = '919999990099'
        insert('Relay Contact Endpoint', channel=channel.name, endpoint=endpoint, relay_contact=base.name, verified=1)
        providers, names = [], []
        for i in range(math.ceil(args.receipts / 3)):
            provider = f'wamid.{tag}.{i}'
            doc = insert('Relay Message', relay_contact=base.name, channel=channel.name,
                direction='Outgoing', status='Sent', provider_id=provider, sender_endpoint=endpoint,
                provider_message_key=provider_key(channel.name, endpoint, provider),
                source_key=f'{tag}-{i}', message_type='text', content=f'{tag}: quantity 12, amount 1250',
                business_doctype=business[0], business_name=business[1],
                provider_context=json.dumps({'provider': 'WhatsApp', 'message_id': provider}))
            providers.append(provider)
            names.append(doc.name)
            if i % 500 == 0:
                frappe.db.commit()
                print(f'Fixture messages: {i + 1}', flush=True)
        frappe.db.commit()
        stamp = int(time.time())
        rows = [{'event_id': stamp, 'position': i, 'message_id': providers[i // 3],
                 'recipient': endpoint, 'status': ('sent', 'delivered', 'read')[i % 3],
                 'timestamp': stamp + i % 3} for i in range(args.receipts)]

        def receive():
            connect(); profile('receive')
            try:
                for start in range(0, len(rows), 500):
                    payload = {'account': tag, 'statuses': rows[start:start + 500]}
                    for attempt in range(20):
                        try:
                            signed_call(inbound.receive_statuses, payload)
                            break
                        except frappe.QueryDeadlockError as exc:
                            error('receive', exc); frappe.db.rollback(); time.sleep(1)
                    else:
                        raise AssertionError('Receipt retry exhausted')
                    if start + 500 < len(rows):
                        time.sleep(args.pace)
            finally:
                receiving.set(); frappe.destroy()

        def project():
            connect(); profile('projection')
            try:
                while not receiving.is_set() or not work.empty():
                    try:
                        kind = work.get(timeout=.1)
                    except queues.Empty:
                        continue
                    start = time.perf_counter()
                    if projection.drain(kind):
                        timings.append(time.perf_counter() - start)
                        spans.append((start, time.perf_counter()))
            finally:
                finished.set(); frappe.destroy()

        def incoming():
            connect(); profile('inbound')
            try:
                i = 0
                while not finished.is_set() or i < 10:
                    provider = f'wamid.{tag}.incoming.{i}'
                    payload = {'account': tag, 'events': [{'id': stamp + i, 'payload': envelope({
                        'messages': [{'id': provider, 'from': endpoint, 'type': 'text',
                                      'text': {'body': f'{tag}: quantity 7, amount 700'}}]})}]}
                    start = time.perf_counter()
                    try:
                        signed_call(inbound.receive, payload)
                        latencies.append((time.perf_counter() - start) * 1000)
                    except frappe.QueryDeadlockError as exc:
                        error('inbound', exc); frappe.db.rollback()
                    i += 1
                    time.sleep(.05)
            finally:
                frappe.destroy()

        def drain():
            connect(); profile('drain')
            try:
                while not finished.is_set():
                    try:
                        queue.drain()
                    except frappe.QueryDeadlockError as exc:
                        error('drain', exc); frappe.db.rollback()
                    time.sleep(.01)
                queue.drain()
            finally:
                frappe.destroy()

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(fn) for fn in (receive, project, incoming, drain)]
            for future in futures:
                future.result(timeout=180)
        elapsed = time.perf_counter() - started
        frappe.db.rollback()
        queue.drain()
        read_count = frappe.db.count('Relay Message', {'name': ['in', names], 'status': 'Read'})
        assert read_count == args.receipts // 3
        assert not frappe.db.exists('Relay Message', {'channel': channel.name, 'automation_status': 'Pending'})
        result = {'fixture': tag, 'receipts': args.receipts, 'seconds': elapsed,
                  'projection_seconds': sum(timings), 'receipts_per_second': args.receipts / elapsed,
                  'status_projection_seconds': spans[-1][1] - spans[0][0],
                  'inbound_samples': len(latencies), 'inbound_p95_ms': sorted(latencies)[math.ceil(len(latencies) * .95) - 1],
                  'errors': errors, 'read_messages': read_count,
                  'database_conflicts': conflicts,
                  'queries': {lane: sum(counts.values()) for lane, counts in queries.items()},
                  'sql_time': {lane: counts.most_common(10) for lane, counts in durations.items()}}
        if args.verify:
            # Replay and delayed weaker evidence cannot edit message timestamps
            # or regress Read. The callback and projection paths remain real.
            before = frappe.db.get_value('Relay Message', names[0], ['status', 'modified'])
            signed_call(inbound.receive_statuses, {'account': tag, 'statuses': rows[:500]})
            assert work.empty(), 'Duplicate status callback queued again'
            late = dict(rows[0], event_id=stamp + 1000000, timestamp=stamp + 1000000, status='delivered')
            signed_call(inbound.receive_statuses, {'account': tag, 'statuses': [late]})
            projection.drain(work.get_nowait())
            assert frappe.db.get_value('Relay Message', names[0], ['status', 'modified']) == before
            result['verification'] = verify_recovery(tag, channel.name, endpoint, work)
            result['verification']['late_delivery_preserves_read_and_modified'] = True
            result['verification']['real_snapshot_conflict_recovered'] = verify_snapshot_conflict(
                tag, dict(late, event_id=late['event_id'] + 1), work)
        Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({k: v for k, v in result.items() if k != 'sql_time'}, indent=2))
    frappe.destroy()


if __name__ == '__main__':
    main()
