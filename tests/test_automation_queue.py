import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
        fake = Mock()
        fake.cache.set.side_effect = [True] + [False] * 299
        with patch.object(queue, 'frappe', fake):
            for _ in range(300):
                queue.wake()
        fake.enqueue.assert_called_once()
        self.assertEqual(fake.enqueue.call_args.kwargs['queue'], 'default')
        self.assertEqual(fake.cache.set.call_args.kwargs, {'nx': True, 'ex': queue.WAKE_TTL})

    def test_enqueue_failure_leaves_durable_work_for_recovery(self):
        fake = Mock()
        fake.enqueue.side_effect = ConnectionError()
        with patch.object(queue, 'frappe', fake), patch.object(queue, '_release_signal') as release:
            queue.wake()
        release.assert_called_once()
        fake.log_error.assert_called_once()
        fake.db.set_value.assert_not_called()

    def test_one_drain_processes_300_in_order_and_commits_each(self):
        fake = Mock(local=SimpleNamespace(site='test'))
        fake.db.sql.return_value = [(1,)]
        fake.get_all.side_effect = [list(range(n, n + 100)) for n in (0, 100, 200)] + [[]]
        with patch.object(queue, 'frappe', fake), patch.object(queue, '_process') as process, \
                patch.object(queue, 'recover') as recover:
            self.assertEqual(queue.drain(), 300)
        self.assertEqual([c.args[0] for c in process.call_args_list], list(range(300)))
        self.assertEqual(fake.db.commit.call_count, 301)
        self.assertEqual(fake.get_all.call_args.kwargs['order_by'], 'creation asc, name asc')
        recover.assert_called_once()

    def test_concurrent_drain_cannot_run_hooks(self):
        fake = Mock(local=SimpleNamespace(site='test'))
        fake.db.sql.return_value = [(0,)]
        with patch.object(queue, 'frappe', fake), patch.object(queue, '_process') as process:
            self.assertEqual(queue.drain(), 0)
        process.assert_not_called()

    def test_crash_rolls_back_and_releases_lock_without_retry_spin(self):
        fake = Mock(local=SimpleNamespace(site='test'))
        fake.db.sql.return_value = [(1,)]
        fake.get_all.return_value = ['oldest', 'newer']
        with patch.object(queue, 'frappe', fake), patch.object(queue, '_process', side_effect=RuntimeError), \
                patch.object(queue, 'recover') as recover:
            with self.assertRaises(RuntimeError):
                queue.drain()
        fake.db.rollback.assert_called_once()
        fake.db.commit.assert_not_called()
        self.assertIn('release_lock', fake.db.sql.call_args.args[0])
        recover.assert_not_called()

    def test_tail_arrival_and_bounded_turn_schedule_successor(self):
        fake = Mock(local=SimpleNamespace(site='test'))
        fake.db.sql.return_value = [(1,)]
        fake.get_all.return_value = ['one', 'two']
        with patch.object(queue, 'frappe', fake), patch.object(queue, '_process') as process, \
                patch.object(queue, '_release_signal') as release, \
                patch.object(queue.time, 'monotonic', side_effect=[0, 0, 6, 6]):
            self.assertEqual(queue.drain(token='signal'), 1)
        release.assert_called_once_with('signal')
        process.assert_called_once_with('one')
        fake.enqueue.assert_called_once()  # Pending tail is signalled after unlocking.

    def test_completed_message_is_not_replayed_and_pause_only_skips_ai(self):
        fake = Mock(conf={'relay_automation_enabled': 1})
        fake.db.get_value.return_value = 'Complete'
        with patch.object(queue, 'frappe', fake):
            queue._process('done')
        fake.get_doc.assert_not_called()
        fake.db.get_value.side_effect = ['Pending', 1]
        fake.get_doc.return_value = _dict(direction='Incoming', relay_contact='paused')
        with patch.object(queue, 'frappe', fake):
            queue._process('paused')
        self.assertEqual([c.args[0] for c in fake.get_attr.call_args_list],
                         [p for p in queue.HANDLERS if p != 'relay_core.automation.service.on_message'])
        fake.db.set_value.assert_called_once_with('Relay Message', 'paused', 'automation_status',
                                                 'Complete', update_modified=False)

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
        fake = SimpleNamespace(conf={})
        with patch.object(service, 'frappe', fake), patch.object(queue, 'recover') as recover, \
                patch.object(skills, 'recover_deliveries') as deliveries:
            service.recover()
        recover.assert_called_once()
        deliveries.assert_called_once()

    def test_ai_creation_and_recovery_keep_work_off_both_projection_queues(self):
        fake = SimpleNamespace(get_doc=Mock(return_value=_dict(name='run', status='Pending')), enqueue=Mock())
        message = _dict(name='message', relay_contact='contact')
        skill = _dict(name='skill', modified='version', run_as_user='operator')
        with patch.object(skills, 'frappe', fake), patch.object(skills, 'lock_contact',
                return_value=_dict(automation_paused=0, automation_generation=0)), \
                patch.object(skills, 'internal_save'), patch.object(skills, 'message_hash', return_value='hash'):
            self.assertEqual(skills.create_run(message, skill)['name'], 'run')
        self.assertEqual(fake.enqueue.call_args.kwargs['queue'], 'default')
        self.assertTrue(fake.enqueue.call_args.kwargs['enqueue_after_commit'])

        fake = SimpleNamespace(conf={'relay_automation_enabled': 1}, enqueue=Mock(),
            get_all=Mock(side_effect=[[], [_dict(name='run')], [_dict(name='outbox')]]))
        with patch.object(service, 'frappe', fake), patch.object(queue, 'recover'), patch.object(skills, 'recover_deliveries'):
            service.recover()
        self.assertEqual([c.kwargs['queue'] for c in fake.enqueue.call_args_list], ['default', 'default'])

    def test_translation_recovery_uses_automation_queue(self):
        fake = SimpleNamespace(conf={'relay_automation_enabled': 1}, enqueue=Mock(), utils=Mock(),
            get_all=Mock(return_value=[_dict(name='translation', status='Pending')]))
        with patch.object(translations, 'frappe', fake):
            translations.recover()
        self.assertEqual(fake.enqueue.call_args.kwargs['queue'], 'default')


if __name__ == '__main__':
    unittest.main()
