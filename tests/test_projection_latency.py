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


def channel_text(channel):
    payload = dict(channel=channel, direction='inbound', provider_id='123', sender='1234', body='Quantity 12')
    if channel == 'Email':
        payload.update(sender='person@example.invalid', provider_id='<local@example.invalid>',
            payload={'message_id': '<local@example.invalid>', 'authentication': {'status': 'pass'}})
    else:
        payload['payload'] = {'update_id': 123, 'message': {'message_id': 456,
            'chat': {'id': 1234, 'type': 'private'}, 'from': {'id': 1234}, 'text': payload['body']}}
    return payload


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

    def test_telegram_and_email_single_text_share_size_and_batch_bounds(self):
        for channel in ('Telegram', 'Email'):
            payload = channel_text(channel)
            self.assertTrue(inbound.single_text(payload))
            for changes in ({'body': 'x' * 16384}, {'direction': 'outbound'}, {'body': None},
                            {'channel_statuses': []}, {'provider_id': ''}):
                self.assertFalse(inbound.single_text(dict(payload, **changes)))
            fake = SimpleNamespace(get_roles=lambda user: ['Relay Hub Service'], session=_dict(user='service'),
                request=Mock(), db=Mock(), publish_realtime=Mock())
            fake.db.get_value.return_value = None
            for count in (1, 2):
                batch = {'account': 'local', 'events': [{'id': i + 1, 'payload': payload} for i in range(count)]}
                with patch.object(inbound, 'frappe', fake), patch.object(inbound, 'connection_value'), \
                        patch.object(inbound, 'validate_callback', return_value=batch), \
                        patch.object(inbound, 'insert_event', return_value=_dict(flags=_dict())) as insert:
                    inbound.receive()
                self.assertEqual(insert.call_count, count)
                self.assertEqual(insert.call_args.kwargs['inline'], count == 1)

    def test_channel_media_edits_reactions_and_dsns_stay_background(self):
        payload = channel_text('Email')
        payload['payload']['attachments'] = [{'filename': 'invoice.pdf', 'size': 12}]
        self.assertFalse(inbound.single_text(payload))
        payload = channel_text('Telegram')
        message = payload['payload'].pop('message')
        for key in ('edited_message', 'message_reaction'):
            payload['payload'] = {'update_id': 123, key: message}
            self.assertFalse(inbound.single_text(payload))
        message.pop('text')
        message['photo'] = [{'file_id': 'local-photo'}]
        message['caption'] = payload['body']
        payload['payload'] = {'update_id': 123, 'message': message}
        self.assertFalse(inbound.single_text(payload))
        self.assertFalse(inbound.single_text({'channel': 'Email', 'channel_statuses': [{'state': 'bounced'}]}))

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

    def test_failed_event_is_logged_and_the_rest_of_the_batch_projects(self):
        fake = SimpleNamespace(db=Mock(), log_error=Mock(), QueryDeadlockError=type('Conflict', (Exception,), {}))
        def project(name):
            if name == 'bad':
                raise RuntimeError('invalid')
        with patch.object(projection, 'frappe', fake), patch.object(inbound, 'frappe', fake), \
                patch('rq.get_current_job', return_value=None), \
                patch.object(projection, 'project', side_effect=project) as projected:
            projection.project_queued(names=['first', 'bad', 'last'], submitted_ns=1)
        self.assertEqual([c.args[0] for c in projected.call_args_list], ['first', 'bad', 'last'])
        fake.db.rollback.assert_called_once()
        self.assertEqual(fake.db.commit.call_count, 4)
        self.assertEqual(fake.log_error.call_args.kwargs['reference_name'], 'bad')

    def test_job_timeout_stops_the_batch(self):
        from rq.timeouts import JobTimeoutException
        fake = SimpleNamespace(db=Mock(), log_error=Mock(), QueryDeadlockError=type('Conflict', (Exception,), {}))
        def project(name):
            if name == 'slow':
                raise JobTimeoutException('timed out')
        with patch.object(projection, 'frappe', fake), patch.object(inbound, 'frappe', fake), \
                patch('rq.get_current_job', return_value=None), \
                patch.object(projection, 'project', side_effect=project) as projected, \
                self.assertRaises(JobTimeoutException):
            projection.project_queued(names=['first', 'slow', 'last'], submitted_ns=1)
        self.assertEqual([c.args[0] for c in projected.call_args_list], ['first', 'slow'])
        fake.log_error.assert_not_called()

    def test_recovery_retains_queue_routing(self):
        rows = [_dict(name='inbound', payload=json.dumps(text_payload())), _dict(name='status', payload='{}'),
                _dict(name='later', payload=json.dumps(text_payload()))]
        fake = SimpleNamespace(get_all=Mock(return_value=rows), enqueue=Mock())
        with patch.object(projection, 'frappe', fake):
            projection.recover()
        self.assertEqual([(c.kwargs['names'], c.kwargs['queue']) for c in fake.enqueue.call_args_list],
                         [(['inbound', 'later'], 'short'), (['status'], 'long')])

    def batch_frappe(self):
        callbacks = SimpleNamespace(commit=[], rollback=[])
        db = SimpleNamespace(after_commit=SimpleNamespace(add=callbacks.commit.append),
                             after_rollback=SimpleNamespace(add=callbacks.rollback.append))
        return SimpleNamespace(db=db, local=SimpleNamespace(), enqueue=Mock()), callbacks

    def test_callback_batch_enqueues_one_ordered_job_per_queue_after_commit(self):
        fake, callbacks = self.batch_frappe()
        events = [('first', text_payload()), ('status', {'channel_statuses': []}), ('second', text_payload())]
        with patch.object(projection, 'frappe', fake):
            for name, payload in events:
                projection.on_event(_dict(name=name, payload=json.dumps(payload), flags=_dict(relay_received_ns=1)))
            fake.enqueue.assert_not_called()
            self.assertEqual(len(callbacks.commit), 1)
            callbacks.commit.pop()()
        self.assertEqual([(c.kwargs['names'], c.kwargs['queue'], c.kwargs['received_ns'])
                          for c in fake.enqueue.call_args_list],
                         [(['first', 'second'], 'short', 1), (['status'], 'long', 1)])
        self.assertFalse(hasattr(fake.local, 'relay_projection_batch'))

    def test_rolled_back_callback_enqueues_nothing(self):
        fake, callbacks = self.batch_frappe()
        with patch.object(projection, 'frappe', fake):
            projection.on_event(_dict(name='lost', payload=json.dumps(text_payload()), flags=_dict()))
            callbacks.rollback.pop()()
            callbacks.commit.clear()
            projection.on_event(_dict(name='kept', payload=json.dumps(text_payload()), flags=_dict()))
            callbacks.commit.pop()()
        self.assertEqual(fake.enqueue.call_args.kwargs['names'], ['kept'])

    def test_worker_records_enqueue_pickup_setup_and_projection(self):
        job = SimpleNamespace(meta={}, enqueued_at=datetime.fromtimestamp(2, timezone.utc),
                              started_at=datetime.fromtimestamp(3, timezone.utc), save_meta=Mock())
        fake = SimpleNamespace(db=Mock())
        with patch.object(projection, 'frappe', fake), patch.object(projection, 'project') as project, \
                patch('rq.get_current_job', return_value=job), patch.object(projection.time, 'time_ns', return_value=4_000_000_000), \
                patch.object(projection.time, 'monotonic_ns', side_effect=[4_000_000_000, 5_000_000_000]):
            projection.project_queued(names=['event', 'next'], submitted_ns=1_500_000_000, received_ns=1_000_000_000)
        self.assertEqual([c.args[0] for c in project.call_args_list], ['event', 'next'])
        timing = job.meta['relay_timing']
        self.assertEqual(timing['events'], 2)
        self.assertEqual(timing['receive_to_enqueue_ms'], 500)
        self.assertEqual(timing['enqueue_ms'], 500)
        self.assertEqual(timing['queue_wait_ms'], 1000)
        self.assertEqual(timing['worker_setup_ms'], 1000)
        self.assertEqual(timing['projection_ms'], 1000)
        job.save_meta.assert_called_once()


    def test_batch_sends_one_triage_invalidation_after_all_events(self):
        from relay_core import realtime
        fake = SimpleNamespace(get_all=Mock(return_value=['manager']), publish_realtime=Mock())
        with patch.object(realtime, 'frappe', fake):
            with realtime.one_incoming_change():
                realtime.incoming_changed()
                realtime.incoming_changed()
                fake.publish_realtime.assert_not_called()
            self.assertEqual(sorted(c.kwargs['user'] for c in fake.publish_realtime.call_args_list), ['Administrator', 'manager'])
            fake.publish_realtime.reset_mock()
            with realtime.one_incoming_change():
                pass
            fake.publish_realtime.assert_not_called()
            realtime.incoming_changed()
            self.assertEqual(fake.publish_realtime.call_count, 2)


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
        self.assertEqual(db.commit.call_count, 2)
