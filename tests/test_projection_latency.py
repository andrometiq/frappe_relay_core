"""Inline projection bounds, transaction boundary and projection drain contracts."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from frappe import _dict
from relay_core import inbound
from relay_core.automation import projection, queue


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
                    patch.object(inbound, 'require_access'), \
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
                    patch.object(inbound, 'require_access'), \
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

    def test_recovery_wakes_both_drains_and_retries_uncategorized_in_order(self):
        fake = SimpleNamespace(db=Mock(), cache=Mock(), get_all=Mock(return_value=['old', 'newer']))
        fake.db.exists.return_value = True
        with patch.object(projection, 'frappe', fake), patch.object(projection, 'project_committed') as project, \
                patch.object(projection.DRAINS['short'], 'wake') as short, patch.object(projection.DRAINS['long'], 'wake') as long:
            projection.recover()
        short.assert_called_once_with(); long.assert_called_once_with()
        self.assertEqual([c.args[0] for c in project.call_args_list], ['old', 'newer'])
        self.assertEqual(fake.get_all.call_args.kwargs['filters'], {'projection_status': 'Uncategorized'})

    def test_burst_of_callbacks_wakes_one_drain_per_queue_after_commit(self):
        callbacks = []
        fake = SimpleNamespace(db=SimpleNamespace(after_commit=SimpleNamespace(add=callbacks.append)))
        with patch.object(projection, 'frappe', fake):
            for index in range(50):
                projection.on_event(_dict(name=f'text-{index}', payload=json.dumps(text_payload()), flags=_dict()))
            projection.on_event(_dict(name='status', payload=json.dumps({'channel_statuses': []}), flags=_dict()))
        self.assertEqual(len(callbacks), 51)  # Redis is touched only after commit.
        rq = MagicMock()
        pipe = rq.connection.pipeline.return_value.__enter__.return_value
        reserved = {}
        pipe.get.side_effect = reserved.get
        pipe.set.side_effect = lambda key, token, ex: reserved.setdefault(key, token)
        fake = Mock(conf={}, local=SimpleNamespace(site='test'))
        fake.cache.make_key.side_effect = lambda key: key
        with patch.object(queue, 'frappe', fake), patch.object(queue, 'get_queue', return_value=rq) as get_queue, \
                patch.object(queue, 'create_job_id', side_effect=lambda value: value):
            for callback in callbacks:
                callback()
        jobs = [c.kwargs['kwargs'] for c in rq.enqueue_call.call_args_list]
        self.assertEqual([(job['method'], job['kwargs']['queue']) for job in jobs],
                         [('relay_core.automation.projection.drain', 'short'), ('relay_core.automation.projection.drain', 'long')])
        self.assertEqual({c.args[0] for c in get_queue.call_args_list}, {'long', 'short'})

    def drain_frappe(self, pages):
        fake = Mock(local=SimpleNamespace(site='test'), QueryDeadlockError=type('Conflict', (Exception,), {}))
        fake.db.db_type = 'mariadb'
        fake.db.sql.return_value = [(1,)]
        fake.get_all.side_effect = [[_dict(name=name, payload=json.dumps(body)) for name, body in page] for page in pages]
        cursors = {}
        fake.cache.get_value.side_effect = cursors.get
        fake.cache.set_value.side_effect = cursors.__setitem__
        fake.cache.delete_value.side_effect = lambda key: cursors.pop(key, None)
        fake.cursors = cursors
        return fake

    def test_drain_projects_its_kind_in_name_order_until_none_remain(self):
        status = {'channel_statuses': []}
        fake = self.drain_frappe([[('e1', text_payload()), ('e2', status), ('e3', text_payload())],
                                  [('e4', text_payload())], []])
        order = []
        signal = projection.DRAINS['short']
        with patch.object(queue, 'frappe', fake), patch.object(projection, 'frappe', fake), \
                patch.object(signal, 'release_signal', side_effect=lambda token: order.append('release')), \
                patch.object(signal, 'wake') as wake, \
                patch.object(projection, 'project_committed', side_effect=order.append):
            self.assertEqual(projection.drain('short', token='signal'), 3)
        self.assertEqual(order, ['release', 'e1', 'e3', 'e4'])  # A wake from now on reserves a successor.
        cursors = [next(f[2] for f in c.kwargs['filters'] if f[0] == 'name') for c in fake.get_all.call_args_list]
        self.assertEqual(cursors, ['', 'e3', 'e4'])
        self.assertIn(['event_key', 'not like', 'statuses:%'], fake.get_all.call_args.kwargs['filters'])
        self.assertEqual(fake.get_all.call_args.kwargs['order_by'], 'name asc')
        wake.assert_not_called()
        self.assertIn('release_lock', fake.db.sql.call_args.args[0])

    def test_long_drain_takes_only_its_kind_and_tries_a_failed_event_once(self):
        fake = self.drain_frappe([[('text', text_payload()), ('bad', {'channel_statuses': []})], []])
        with patch.object(queue, 'frappe', fake), patch.object(projection, 'frappe', fake), \
                patch.object(inbound, 'frappe', fake), \
                patch.object(projection, 'project', side_effect=RuntimeError('invalid')) as project, \
                patch.object(projection.DRAINS['long'], 'wake') as wake:
            self.assertEqual(projection.drain('long'), 1)
        project.assert_called_once_with('bad')
        self.assertEqual(fake.log_error.call_args.kwargs['reference_name'], 'bad')
        self.assertEqual(len(fake.get_all.call_args.kwargs['filters']), 2)
        wake.assert_not_called()  # The failed event waits for recovery instead of spinning.

    def test_failed_event_is_not_retried_by_the_next_drain_until_recovery(self):
        fake = self.drain_frappe([[('bad', text_payload())], [], [('new', text_payload())], []])
        def project(name):
            if name == 'bad':
                raise RuntimeError('invalid')
        with patch.object(queue, 'frappe', fake), patch.object(projection, 'frappe', fake), \
                patch.object(inbound, 'frappe', fake), \
                patch.object(projection, 'project', side_effect=project) as projected:
            projection.drain('short')
            projection.drain('short')
        self.assertEqual([c.args[0] for c in projected.call_args_list], ['bad', 'new'])
        cursors = [next(f[2] for f in c.kwargs['filters'] if f[0] == 'name') for c in fake.get_all.call_args_list]
        self.assertEqual(cursors, ['', 'bad', 'bad', 'new'])  # The second drain starts after the failure.
        fake.log_error.assert_called_once()
        fake.db.exists.return_value = True
        fake.get_all.side_effect = None
        fake.get_all.return_value = []
        with patch.object(projection, 'frappe', fake), patch.object(projection.DRAINS['short'], 'wake'), \
                patch.object(projection.DRAINS['long'], 'wake'):
            projection.recover()
        self.assertEqual(fake.cursors, {})  # Recovery rescans failed events from the start once a minute.

    def test_turn_ending_mid_page_resumes_after_the_last_event_tried(self):
        fake = self.drain_frappe([[('one', text_payload()), ('two', text_payload())]])
        with patch.object(queue, 'frappe', fake), patch.object(projection, 'frappe', fake), \
                patch.object(projection.DRAINS['short'], 'wake'), patch.object(projection, 'project_committed'), \
                patch.object(projection.time, 'monotonic', side_effect=[0, 0, 0, 6, 6]):
            projection.drain('short')
        self.assertEqual(fake.cursors, {projection.CURSOR + 'short': 'one'})

    def test_contended_or_unfinished_drain_keeps_a_successor(self):
        fake = self.drain_frappe([])
        fake.db.sql.return_value = [(0,)]
        signal = projection.DRAINS['short']
        with patch.object(queue, 'frappe', fake), patch.object(projection, 'frappe', fake), \
                patch.object(signal, 'wake') as wake:
            self.assertEqual(projection.drain('short'), 0)
        wake.assert_called_once_with()
        fake.get_all.assert_not_called()
        fake = self.drain_frappe([[('one', text_payload()), ('two', text_payload())]])
        with patch.object(queue, 'frappe', fake), patch.object(projection, 'frappe', fake), \
                patch.object(signal, 'wake') as wake, patch.object(projection, 'project_committed') as project, \
                patch.object(projection.time, 'monotonic', side_effect=[0, 0, 0, 6, 6]):
            self.assertEqual(projection.drain('short'), 1)
        project.assert_called_once_with('one')
        wake.assert_called_once_with()

    def test_batch_sends_one_triage_invalidation_after_all_events(self):
        from relay_core import realtime
        fake = SimpleNamespace(get_all=Mock(return_value=['manager']), publish_realtime=Mock())
        with patch.object(realtime, 'frappe', fake), \
                patch('frappe.permissions.get_doctype_roles', return_value=['Relay Communication Manager']):
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
