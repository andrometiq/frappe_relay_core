"""Inline projection bounds, transaction boundary and worker timing contracts."""
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core import inbound
from relay_core.automation import projection


def text_payload():
    return {'entry': [{'changes': [{'field': 'messages', 'value': {'messages': [
        {'id': 'local-text', 'from': '919999999999', 'type': 'text', 'text': {'body': 'Hello'}}]}}]}]}


class ProjectionLatencyTests(unittest.TestCase):
    def test_receive_bounds_inline_work_and_replays_do_not_project_twice(self):
        for count in (1, 2):
            payload = {'account': 'local', 'events': [{'id': i + 1, 'payload': text_payload()} for i in range(count)]}
            fake = SimpleNamespace(get_roles=lambda user: ['Relay Hub Service'], session=_dict(user='service'),
                request=Mock(), db=Mock(), publish_realtime=Mock())
            fake.db.get_value.return_value = None
            doc = _dict(flags=_dict(relay_projection_ms=12))
            with patch.object(inbound, 'frappe', fake), patch.object(inbound, 'connection_value'), \
                    patch.object(inbound, 'validate_callback', return_value=payload), \
                    patch.object(inbound, 'insert_event', return_value=doc) as insert:
                reply = inbound.receive()
                self.assertEqual(reply['accepted'], count)
                self.assertEqual(insert.call_count, count)
                self.assertEqual(insert.call_args.kwargs['inline'], count == 1)
                insert.reset_mock()
                fake.db.get_value.return_value = json.dumps(text_payload())
                self.assertEqual(inbound.receive()['accepted'], count)
                insert.assert_not_called()

    def test_inline_bounds_exclude_bulk_updates_media_and_malformed_payloads(self):
        payload = text_payload()
        self.assertTrue(inbound.single_text(payload))
        variants = [None, {}, {'entry': None}, {'entry': [{}]}, dict(payload, channel='Email')]
        for change in ({'statuses': [{}]}, {'calls': [{}]}, {'messages': []}, {'messages': [None]},
                       {'messages': text_payload()['entry'][0]['changes'][0]['value']['messages'] * 2},
                       {'messages': [{'type': 'image'}]}, {'messages': [{'type': 'reaction'}]},
                       {'messages': [{'type': 'text', 'text': {'body': 'x' * 16384}}]}):
            value = text_payload()
            value['entry'][0]['changes'][0]['value'].update(change)
            variants.append(value)
        for value in variants:
            with self.subTest(value=str(value)[:80]):
                self.assertFalse(inbound.single_text(value))

    def test_inline_runs_in_current_transaction_without_queue_or_commit(self):
        doc = _dict(name='event', payload=json.dumps(text_payload()), flags=_dict(relay_inline_projection=True))
        fake = SimpleNamespace(db=Mock(), enqueue=Mock())
        with patch.object(projection, 'frappe', fake), patch.object(projection, 'project') as project:
            projection.on_event(doc)
        project.assert_called_once_with('event')
        fake.enqueue.assert_not_called()
        fake.db.commit.assert_not_called()
        fake.db.after_commit.add.assert_not_called()
        self.assertGreaterEqual(doc.flags.relay_projection_ms, 0)

    def test_inline_failure_propagates_to_callback_transaction(self):
        doc = _dict(name='event', flags=_dict(relay_inline_projection=True))
        with patch.object(projection, 'project', side_effect=RuntimeError('retry')):
            with self.assertRaisesRegex(RuntimeError, 'retry'):
                projection.on_event(doc)

    def test_failed_worker_projection_does_not_report_committed_timing(self):
        fake = SimpleNamespace(db=Mock())
        with patch.object(projection, 'frappe', fake), patch('rq.get_current_job', return_value=Mock()), \
                patch.object(projection, 'project', side_effect=RuntimeError('rollback')):
            with self.assertRaisesRegex(RuntimeError, 'rollback'):
                projection.project_queued('event', 1)
        fake.db.after_commit.add.assert_not_called()

    def test_recovery_retains_queue_routing(self):
        rows = [_dict(name='inbound', payload=json.dumps(text_payload())), _dict(name='status', payload='{}')]
        fake = SimpleNamespace(get_all=Mock(return_value=rows), enqueue=Mock())
        with patch.object(projection, 'frappe', fake):
            projection.recover()
        self.assertEqual([(c.kwargs['name'], c.kwargs['queue']) for c in fake.enqueue.call_args_list],
                         [('inbound', 'short'), ('status', 'long')])

    def test_bulk_and_status_jobs_enqueue_only_after_commit_on_separate_queues(self):
        for payload, queue in ((text_payload(), 'short'), ({'entry': []}, 'long'),
                               ({'channel_statuses': []}, 'long')):
            callbacks = []
            fake = SimpleNamespace(db=SimpleNamespace(after_commit=SimpleNamespace(add=callbacks.append)), enqueue=Mock())
            doc = _dict(name='event', payload=json.dumps(payload), flags=_dict(relay_received_ns=1))
            with patch.object(projection, 'frappe', fake):
                projection.on_event(doc)
                fake.enqueue.assert_not_called()
                callbacks.pop()()
            self.assertEqual(fake.enqueue.call_args.kwargs['queue'], queue)
            self.assertEqual(fake.enqueue.call_args.kwargs['received_ns'], 1)

    def test_worker_records_enqueue_pickup_setup_and_committed_projection(self):
        callbacks = []
        job = SimpleNamespace(meta={}, enqueued_at=datetime.fromtimestamp(2, timezone.utc),
                              started_at=datetime.fromtimestamp(3, timezone.utc), save_meta=Mock())
        fake = SimpleNamespace(db=SimpleNamespace(after_commit=SimpleNamespace(add=callbacks.append)))
        with patch.object(projection, 'frappe', fake), patch.object(projection, 'project') as project, \
                patch('rq.get_current_job', return_value=job), patch.object(projection.time, 'time_ns', return_value=4_000_000_000), \
                patch.object(projection.time, 'monotonic_ns', side_effect=[4_000_000_000, 5_000_000_000]):
            projection.project_queued('event', 1_500_000_000, 1_000_000_000)
            job.save_meta.assert_not_called()
            callbacks.pop()()
        project.assert_called_once_with('event')
        timing = job.meta['relay_timing']
        self.assertEqual(timing['receive_to_enqueue_ms'], 500)
        self.assertEqual(timing['enqueue_ms'], 500)
        self.assertEqual(timing['queue_wait_ms'], 1000)
        self.assertEqual(timing['worker_setup_ms'], 1000)
        self.assertEqual(timing['projection_ms'], 1000)
        job.save_meta.assert_called_once()


class ProjectionRetryTests(unittest.TestCase):
    def test_background_projection_retries_whole_transaction_and_discards_failed_callbacks(self):
        class Conflict(Exception):
            pass
        callbacks = []
        db = Mock()
        db.after_commit.add.side_effect = callbacks.append
        db.rollback.side_effect = callbacks.clear
        attempts = []
        def project(name):
            attempts.append(name)
            callbacks.append('attempt')
            if len(attempts) == 1:
                raise Conflict(1020)
        fake = SimpleNamespace(db=db, QueryDeadlockError=Conflict)
        with patch.object(inbound, 'frappe', fake), patch.object(projection, 'frappe', fake), \
                patch.object(projection, 'project', side_effect=project), patch.object(inbound.time, 'sleep'), \
                patch('rq.get_current_job', return_value=None):
            projection.project_queued('event', submitted_ns=1)
        self.assertEqual(attempts, ['event', 'event'])
        self.assertEqual(callbacks, ['attempt'])
        db.rollback.assert_called_once()
        db.commit.assert_not_called()
