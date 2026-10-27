import unittest
from unittest.mock import Mock, patch

import frappe

from relay_core import ai_features, scheduled_jobs, settings, summaries, tickets, translations, voice_transcripts
from relay_core.ai import configuration
from relay_core.automation import service as automation
from relay_core.learning import service as learning

AI_JOBS = ('recover_learning', 'recover_summaries', 'recover_translations', 'recover_voice_transcripts')
AI_APIS = ((configuration.directory, ()), (configuration.save, ({},)), (learning.directory, ()), (summaries.latest, ('CON-1',)),
           (summaries.generate, ('CON-1', 'WA', 'all', 'key')), (translations.retry, ('T-1',)), (tickets.resume_ai, ('TKT-1',)),
           (tickets.ai_history, ('TKT-1',)), (automation.takeover, ('CON-1',)))


def settings_db(ai_enabled):
    database = Mock()
    database.get_single_value.side_effect = lambda doctype, field: {
        'hub_url': 'https://hub.example/mcp', 'enable_ai_features': ai_enabled}.get(field)
    return database


def throw(message, exception=frappe.ValidationError):
    raise exception(message)


class AiFeatureSwitchTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(frappe, 'throw', throw)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ai_jobs_return_at_once_while_off(self):
        with patch.object(frappe, 'db', settings_db(0)), patch.object(frappe, 'conf', {}), \
             patch.object(frappe, 'get_attr') as get_attr:
            for job in AI_JOBS:
                getattr(scheduled_jobs, job)()
            scheduled_jobs.recover_messages()
        get_attr.assert_called_once_with('relay_core.messaging.recover')

    def test_ai_jobs_run_while_on(self):
        with patch.object(frappe, 'db', settings_db(1)), patch.object(frappe, 'conf', {}), \
             patch.object(frappe, 'get_attr') as get_attr:
            for job in AI_JOBS:
                getattr(scheduled_jobs, job)()
        self.assertEqual(get_attr.call_count, len(AI_JOBS))

    def test_ai_apis_are_denied_while_off(self):
        with patch.object(frappe, 'db', settings_db(0)):
            for api, arguments in AI_APIS:
                with self.subTest(api=api.__qualname__), self.assertRaisesRegex(frappe.PermissionError, ai_features.OFF_MESSAGE):
                    api(*arguments)

    def test_queued_ai_work_and_inbound_hooks_do_nothing_while_off(self):
        message = Mock(direction='Incoming', message_type='voice', legacy_source=None)
        message.get.return_value = None
        with patch.object(frappe, 'db', settings_db(0)), patch.object(frappe, 'get_doc') as get_doc, \
             patch.object(frappe, 'enqueue') as enqueue:
            self.assertIsNone(summaries.process('SUM-1'))
            self.assertIsNone(learning.process('EVAL-1'))
            self.assertIsNone(translations.process('TR-1'))
            self.assertIsNone(voice_transcripts.process('MSG-1'))
            self.assertIsNone(voice_transcripts.on_message(message))
        get_doc.assert_not_called()
        enqueue.assert_not_called()

    def test_translation_needs_the_switch_and_the_site_opt_in(self):
        message = Mock(direction='Incoming', message_type='text')
        message.get.return_value = None
        for enabled, conf in ((0, {'relay_automation_enabled': 1}), (1, {})):
            database = settings_db(enabled)
            with self.subTest(enabled=enabled, conf=conf), patch.object(frappe, 'db', database), \
                 patch.object(frappe, 'conf', conf):
                self.assertIsNone(translations.on_message(message))
            database.get_value.assert_not_called()

    def test_guarded_function_runs_unchanged_while_on(self):
        target = ai_features.required(lambda value: value * 2)
        with patch.object(frappe, 'db', settings_db(1)):
            self.assertEqual(target(4), 8)

    def test_a_missing_setting_reads_as_off(self):
        database = Mock()
        database.get_single_value.return_value = None
        with patch.object(frappe, 'db', database):
            self.assertFalse(ai_features.is_enabled())

    def test_only_a_system_manager_can_switch_ai(self):
        database = settings_db(0)
        with patch.object(settings, 'require_access'), patch.object(frappe, 'db', database), \
             patch.object(frappe, 'get_roles', return_value=['Relay Communication Manager']):
            with self.assertRaises(frappe.PermissionError):
                settings.save_ai_features(1)
        database.set_single_value.assert_not_called()
        with patch.object(settings, 'require_access'), patch.object(frappe, 'db', database), \
             patch.object(frappe, 'get_roles', return_value=['System Manager']):
            settings.save_ai_features(1)
        database.set_single_value.assert_called_once_with('Relay Settings', 'enable_ai_features', 1)


if __name__ == '__main__':
    unittest.main()
