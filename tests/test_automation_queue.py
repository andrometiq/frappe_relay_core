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
        fake = SimpleNamespace(db=SimpleNamespace(after_commit=SimpleNamespace(add=callbacks.append)),
                               enqueue=Mock())
        doc = _dict(name='message', direction='Incoming', flags=_dict())
        hooks = (translation, flow, automation, email)
        with patch.object(queue, 'frappe', fake):
            for handler in hooks:
                handler(doc, 'after_insert')
            fake.enqueue.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
        call = fake.enqueue.call_args
        self.assertEqual(call.args, ('relay_core.automation.queue.run_message_hooks',))
        self.assertEqual(call.kwargs['message'], doc.name)
        self.assertEqual(call.kwargs['handlers'], [handler.__module__ + '.on_message' for handler in hooks])
        self.assertEqual(call.kwargs['queue'], 'default')
        self.assertTrue(call.kwargs['deduplicate'])

    def test_rollback_and_outgoing_or_imported_messages_do_no_automation_work(self):
        handler = Mock()
        handler.__module__, handler.__name__ = 'local', 'handler'
        wrapped = queue.after_message_commit(handler)
        callbacks = []
        fake = SimpleNamespace(db=SimpleNamespace(after_commit=SimpleNamespace(add=callbacks.append)), enqueue=Mock())
        with patch.object(queue, 'frappe', fake):
            for values in ({'direction': 'Outgoing'}, {'direction': 'Incoming', 'legacy_source': 'old'}):
                wrapped(_dict(name='ignored', **values), 'after_insert')
            self.assertEqual(callbacks, [])
            wrapped(_dict(name='rolled-back', direction='Incoming', flags=_dict()), 'after_insert')
            callbacks.clear()  # Frappe discards transaction callbacks on rollback.
        fake.enqueue.assert_not_called()
        handler.assert_not_called()

    def test_worker_loads_committed_message_and_manual_calls_keep_result(self):
        handler = Mock(return_value='intent')
        handler.__module__, handler.__name__ = 'local', 'handler'
        doc = _dict(name='message', content='committed')
        wrapped = queue.after_message_commit(handler)
        fake = SimpleNamespace(get_doc=Mock(return_value=doc), get_attr=Mock(return_value=wrapped))
        with patch.object(queue, 'frappe', fake):
            queue.run_message_hooks(['local.handler'], 'message')
        fake.get_doc.assert_called_once_with('Relay Message', 'message')
        handler.assert_called_once_with(doc, None)
        self.assertEqual(wrapped(doc), 'intent')

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
        with patch.object(service, 'frappe', fake):
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
