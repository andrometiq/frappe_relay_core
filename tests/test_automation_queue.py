import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, PropertyMock, patch

from frappe import _dict
from relay_core.automation import queue
from relay_core.automation.service import on_message as automation
from relay_core.translations import on_message as translation
from relay_core.flows.service import on_message as flow
from relay_core.email_preferences import on_message as email
from relay_core.ai import service as skills
from relay_core.automation import service
from relay_core import translations


class AutomationQueueTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('relay_core.email_preferences.recover'))

    def test_every_inbound_hook_defers_policy_reads_and_redis_until_commit(self):
        callbacks = []
        fake = SimpleNamespace(db=SimpleNamespace(after_commit=SimpleNamespace(add=callbacks.append)))
        doc = _dict(name='message', direction='Incoming', flags=_dict())
        with patch.object(queue, 'frappe', fake), patch.object(queue, 'wake') as wake:
            for handler in (translation, flow, automation, email):
                handler(doc, 'after_insert')
            wake.assert_not_called()
            self.assertEqual(callbacks, [wake])
            callbacks[0]()
            wake.assert_called_once_with()

    def test_rollback_and_outgoing_or_imported_messages_do_no_automation_work(self):
        handler = Mock(__module__='local', __name__='handler')
        wrapped = queue.after_message_commit(handler)
        callbacks = []
        fake = SimpleNamespace(db=SimpleNamespace(after_commit=SimpleNamespace(add=callbacks.append)))
        with patch.object(queue, 'frappe', fake), patch.object(queue, 'wake') as wake:
            for values in ({'direction': 'Outgoing'}, {'direction': 'Incoming', 'legacy_source': 'old'}):
                wrapped(_dict(name='ignored', **values), 'after_insert')
            self.assertEqual(callbacks, [])
            wrapped(_dict(name='rolled-back', direction='Incoming', flags=_dict()), 'after_insert')
            callbacks.clear()
            wake.assert_not_called()
        handler.assert_not_called()
        self.assertEqual(wrapped('manual'), handler.return_value)

    def test_marker_is_atomic_with_insert_and_ignores_supplied_status(self):
        from relay_core.relay_core.doctype.relay_message.relay_message import RelayMessage
        for values, expected in (({'direction': 'Incoming'}, 'Pending'),
                                 ({'direction': 'Outgoing'}, ''),
                                 ({'direction': 'Incoming', 'legacy_source': 'old'}, '')):
            doc = _dict(**values, automation_status='Complete')
            RelayMessage.before_insert(doc)
            self.assertEqual(doc.automation_status, expected)

    def test_signal_coalesces_300_arrivals_and_uses_default(self):
        fake = Mock(conf={})
        rq = MagicMock()
        rq.fetch_job.return_value.get_status.return_value = 'queued'
        pipe = rq.connection.pipeline.return_value.__enter__.return_value
        pipe.get.side_effect = [None] + [b'waiting'] * 299
        with patch.object(queue, 'frappe', fake), patch.object(queue, 'get_queue', return_value=rq) as get_queue, \
                patch.object(queue, 'create_job_id', side_effect=lambda value: value):
            for _ in range(300):
                queue.wake()
        rq.enqueue_call.assert_called_once()
        self.assertEqual(get_queue.call_args.args, ('default',))
        self.assertIs(rq.enqueue_call.call_args.kwargs['pipeline'], pipe)
        pipe.execute.assert_called_once()
        self.assertEqual(pipe.set.call_args.kwargs, {'ex': queue.WAKE_TTL})

    def test_stale_signal_replaced_when_job_is_missing_or_not_live(self):
        for status in (None, 'finished', 'failed', 'stopped', 'canceled'):
            with self.subTest(status=status):
                fake = Mock(conf={})
                rq = MagicMock()
                pipe = rq.connection.pipeline.return_value.__enter__.return_value
                pipe.get.return_value = b'lost-token'
                rq.fetch_job.return_value = None if status is None else Mock(
                    get_status=Mock(return_value=status))
                with patch.object(queue, 'frappe', fake), patch.object(queue, 'get_queue', return_value=rq), \
                        patch.object(queue, 'create_job_id', side_effect=lambda value: value):
                    self.assertIs(queue.wake(), rq.enqueue_call.return_value)
                rq.fetch_job.assert_called_once_with('relay-message-automation-drain:lost-token')
                rq.enqueue_call.assert_called_once()
                token = pipe.set.call_args.args[1]
                self.assertNotEqual(token, 'lost-token')
                self.assertEqual(rq.enqueue_call.call_args.kwargs['job_id'],
                                 f'relay-message-automation-drain:{token}')
                pipe.execute.assert_called_once()
                fake.db.sql.assert_not_called()  # The site-wide turn lock is unchanged.
                fake.log_error.assert_not_called()

    def test_live_signal_job_keeps_its_reservation(self):
        for status in ('queued', 'started'):
            with self.subTest(status=status):
                fake = Mock(conf={})
                rq = MagicMock()
                pipe = rq.connection.pipeline.return_value.__enter__.return_value
                pipe.get.return_value = b'live-token'
                rq.fetch_job.return_value.get_status.return_value = status
                with patch.object(queue, 'frappe', fake), patch.object(queue, 'get_queue', return_value=rq), \
                        patch.object(queue, 'create_job_id', side_effect=lambda value: value):
                    queue.wake()
                rq.fetch_job.assert_called_once_with('relay-message-automation-drain:live-token')
                rq.enqueue_call.assert_not_called()
                pipe.set.assert_not_called()
                pipe.execute.assert_not_called()
                fake.log_error.assert_not_called()

    def test_interrupted_enqueue_does_not_publish_an_orphan_reservation(self):
        fake = Mock(conf={})
        rq = MagicMock()
        rq.fetch_job.return_value.get_status.return_value = 'queued'
        pipe = rq.connection.pipeline.return_value.__enter__.return_value
        pipe.get.return_value = None
        rq.enqueue_call.side_effect = ConnectionError()
        with patch.object(queue, 'frappe', fake), patch.object(queue, 'get_queue', return_value=rq), \
                patch.object(queue, 'create_job_id', side_effect=lambda value: value):
            queue.wake()
            pipe.set.assert_called_once()  # Staged only; invisible to competing wakes.
            pipe.execute.assert_not_called()
            rq.enqueue_call.side_effect = None
            self.assertIs(queue.wake(), rq.enqueue_call.return_value)
        pipe.execute.assert_called_once()  # Recovery can publish immediately, no TTL wait.
        fake.log_error.assert_called_once()
        fake.db.set_value.assert_not_called()

    def test_competing_wake_retries_watch_conflict_and_keeps_winners_job(self):
        fake = Mock(conf={})
        rq = MagicMock()
        rq.fetch_job.return_value.get_status.return_value = 'queued'
        pipe = rq.connection.pipeline.return_value.__enter__.return_value
        pipe.get.side_effect = [None, b'winner']
        pipe.execute.side_effect = queue.WatchError()
        with patch.object(queue, 'frappe', fake), patch.object(queue, 'get_queue', return_value=rq), \
                patch.object(queue, 'create_job_id', side_effect=lambda value: value):
            queue.wake()
        rq.enqueue_call.assert_called_once()
        fake.log_error.assert_not_called()

    def test_expired_jobs_cannot_release_a_successors_signal(self):
        rq = Mock()
        with patch.object(queue, 'get_queue', return_value=rq), \
                patch.object(queue.Drain, 'signal_key', new_callable=PropertyMock, return_value='key'):
            queue.AUTOMATION.release_signal('old-token')
        args = rq.connection.eval.call_args.args
        self.assertIn("redis.call('get', KEYS[1]) == ARGV[1]", args[0])
        self.assertEqual(args[1:], (1, 'key', 'old-token'))

    def test_one_drain_processes_300_in_order_and_commits_each(self):
        fake = Mock(local=SimpleNamespace(site='test'))
        fake.db.db_type = 'mariadb'
        fake.db.sql.return_value = [(1,)]
        fake.get_all.side_effect = [list(range(n, n + 100)) for n in (0, 100, 200)] + [[]]
        with patch.object(queue, 'frappe', fake), patch.object(queue, '_process') as process, \
                patch.object(queue, 'recover') as recover:
            self.assertEqual(queue.drain(), 300)
        self.assertEqual([c.args[0] for c in process.call_args_list], list(range(300)))
        self.assertEqual(fake.db.commit.call_count, 304)  # Each list read ends its snapshot, then one per message.
        self.assertEqual(fake.get_all.call_args.kwargs['order_by'], 'creation asc, name asc')
        recover.assert_called_once()

    def test_postgres_session_lock_survives_commits_and_releases_on_failure(self):
        for fail in (False, True):
            fake = Mock(local=SimpleNamespace(site='test'))
            fake.db.db_type = 'postgres'
            fake.db.sql.return_value = [(True,)]
            fake.get_all.side_effect = [['first', 'second'], []]
            with patch.object(queue, 'frappe', fake), patch.object(queue, 'recover'), \
                    patch.object(queue, '_process', side_effect=RuntimeError if fail else None):
                if fail:
                    with self.assertRaises(RuntimeError): queue.drain()
                    fake.db.rollback.assert_called_once()
                else:
                    self.assertEqual(queue.drain(), 2)
                    self.assertEqual(fake.db.commit.call_count, 4)
            acquire, release = fake.db.sql.call_args_list
            self.assertEqual(acquire.args[0], 'select pg_try_advisory_lock(%s)')
            self.assertEqual(release.args[0], 'select pg_advisory_unlock(%s)')
            self.assertEqual(acquire.args[1], release.args[1])
            self.assertIsInstance(acquire.args[1][0], int)

    def test_postgres_contended_lock_reschedules_without_unlocking_owner(self):
        fake = Mock(local=SimpleNamespace(site='test'))
        fake.db.db_type = 'postgres'; fake.db.sql.return_value = [(False,)]
        with patch.object(queue, 'frappe', fake), patch.object(queue, 'wake') as wake:
            self.assertEqual(queue.drain(), 0)
        self.assertEqual(fake.db.sql.call_count, 1)
        wake.assert_called_once()
        fake.get_all.assert_not_called()

    def test_concurrent_drain_cannot_run_hooks(self):
        fake = Mock(local=SimpleNamespace(site='test'))
        fake.db.db_type = 'mariadb'
        fake.db.sql.return_value = [(0,)]
        with patch.object(queue, 'frappe', fake), patch.object(queue, '_process') as process, \
                patch.object(queue.AUTOMATION, 'release_signal') as release, patch.object(queue, 'wake') as wake:
            self.assertEqual(queue.drain(token='consumed'), 0)
        process.assert_not_called()
        release.assert_called_once_with('consumed')
        wake.assert_called_once()  # Final-empty-read race must retain a successor.

    def test_crash_rolls_back_and_releases_lock_without_retry_spin(self):
        fake = Mock(local=SimpleNamespace(site='test'))
        fake.db.db_type = 'mariadb'
        fake.db.sql.return_value = [(1,)]
        fake.get_all.return_value = ['oldest', 'newer']
        with patch.object(queue, 'frappe', fake), patch.object(queue, '_process', side_effect=RuntimeError), \
                patch.object(queue, 'recover') as recover:
            with self.assertRaises(RuntimeError):
                queue.drain()
        fake.db.rollback.assert_called_once()
        fake.db.commit.assert_called_once()  # Only the list snapshot; the failed message commits nothing.
        self.assertIn('release_lock', fake.db.sql.call_args.args[0])
        recover.assert_not_called()

    def test_tail_arrival_and_bounded_turn_schedule_successor(self):
        fake = Mock(local=SimpleNamespace(site='test'))
        fake.db.db_type = 'mariadb'
        fake.db.sql.return_value = [(1,)]
        fake.get_all.return_value = ['one', 'two']
        with patch.object(queue, 'frappe', fake), patch.object(queue, '_process') as process, \
                patch.object(queue.AUTOMATION, 'release_signal') as release, \
                patch.object(queue, 'wake') as wake, \
                patch.object(queue.time, 'monotonic', side_effect=[0, 0, 6, 6]):
            self.assertEqual(queue.drain(token='signal'), 1)
        release.assert_called_once_with('signal')
        process.assert_called_once_with('one')
        wake.assert_called_once()  # Pending tail is signalled after unlocking.

    def test_completed_message_is_not_replayed_and_pause_is_checked_by_admission(self):
        fake = Mock(conf={'relay_automation_enabled': 1})
        fake.db.get_value.return_value = ('Complete', 'contact')
        with patch.object(queue, 'frappe', fake):
            queue._process('done')
        fake.get_doc.assert_not_called()
        fake.db.get_value.side_effect = [('Pending', 'contact'), 'contact']
        fake.get_doc.return_value = _dict(direction='Incoming', relay_contact='contact')
        with patch.object(queue, 'frappe', fake):
            queue._process('paused')
        self.assertEqual([c.args[0] for c in fake.get_attr.call_args_list],
                         list(queue.HANDLERS))
        fake.db.set_value.assert_called_once_with('Relay Message', 'paused', 'automation_status',
                                                 'Complete', update_modified=False)

    def test_the_message_and_its_contact_are_locked_before_the_first_plain_read(self):
        fake = Mock()
        order = []
        fake.db.get_value.side_effect = lambda doctype, *args, **kwargs: order.append((doctype, kwargs.get('for_update'))) or (
            ('Pending', 'contact') if doctype == 'Relay Message' else 'contact')
        fake.get_doc.side_effect = lambda *args: order.append('read') or _dict(direction='Incoming')
        with patch.object(queue, 'frappe', fake):
            queue._process('message')
        self.assertEqual(order, [('Relay Message', True), ('Relay Contact', True), 'read'])

    def test_a_message_without_a_contact_takes_no_contact_lock(self):
        fake = Mock()
        fake.db.get_value.return_value = ('Pending', None)
        fake.get_doc.return_value = _dict(direction='Incoming')
        with patch.object(queue, 'frappe', fake):
            queue._process('message')
        fake.db.get_value.assert_called_once()

    def test_pre_upgrade_jobs_join_the_durable_drain_without_replaying_completed_rows(self):
        fake = Mock()
        with patch.object(queue, 'frappe', fake), patch.object(queue, 'drain') as drain:
            for values in ({'direction': 'Outgoing'}, {'direction': 'Incoming', 'legacy_source': 'old'},
                           {'direction': 'Incoming', 'automation_status': 'Complete'}):
                fake.get_doc.return_value = _dict(**values)
                queue.run_message_hooks(queue.HANDLERS, 'old-job')
            drain.assert_not_called()
            fake.db.sql.assert_not_called()
            fake.get_doc.return_value = _dict(direction='Incoming', automation_status=None)
            queue.run_message_hooks(queue.HANDLERS, 'old-job')
            fake.db.commit.assert_called_once()
            drain.assert_called_once()

    def test_recovery_runs_even_when_ai_is_disabled(self):
        fake = SimpleNamespace(conf={}, get_all=Mock(return_value=[]))
        with patch.object(service, 'frappe', fake), patch.object(queue, 'recover') as recover, \
                patch.object(skills, 'recover_deliveries') as deliveries:
            service.recover()
        recover.assert_called_once()
        deliveries.assert_called_once()

    def test_ai_recovery_keeps_work_off_both_projection_queues(self):
        fake = SimpleNamespace(conf={'relay_automation_enabled': 1}, enqueue=Mock(),
            get_all=Mock(side_effect=[[], [], [_dict(name='run')], [_dict(name='outbox')]]))
        with patch.object(service, 'frappe', fake), patch.object(queue, 'recover'), patch.object(skills, 'recover_deliveries'):
            service.recover()
        self.assertEqual([c.kwargs['queue'] for c in fake.enqueue.call_args_list], ['default', 'default'])

    def test_translation_recovery_uses_automation_queue(self):
        fake = SimpleNamespace(conf={'relay_automation_enabled': 1}, enqueue=Mock(), utils=Mock(),
            get_all=Mock(return_value=[_dict(name='translation', status='Pending')]))
        with patch.object(translations, 'frappe', fake):
            translations.recover()
        self.assertEqual(fake.enqueue.call_args.kwargs['queue'], 'default')


def setUpModule():
    """These tests cover AI behavior, so the AI features switch is on."""
    from unittest import addModuleCleanup, mock
    switch = mock.patch('relay_core.ai_features.is_enabled', return_value=True)
    switch.start()
    addModuleCleanup(switch.stop)


if __name__ == '__main__':
    unittest.main()
