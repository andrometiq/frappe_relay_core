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

    def test_events_and_knowledge_stay_open_while_off(self):
        from relay_core import hooks
        from relay_core.ai import events, knowledge
        for doctype in ('Relay AI Event', 'Relay AI Event Build', 'Relay AI Playbook'):
            self.assertNotEqual(hooks.has_permission.get(doctype), 'relay_core.ai_features.document_permission', doctype)
            self.assertNotIn('validate', hooks.doc_events.get(doctype, {}), doctype)
        self.assertEqual(hooks.has_permission['Relay AI Skill'], 'relay_core.ai_features.document_permission')
        with patch.object(frappe, 'db', settings_db(0)), patch.object(events, 'require_access'), \
             patch.object(knowledge, 'require_access'), patch.object(frappe, 'get_list', return_value=[]):
            self.assertEqual(events.directory(), {'items': [], 'next': None})
            self.assertEqual(knowledge.directory(), {'items': [], 'next': None})

    def test_content_pickers_work_while_off_and_skill_pickers_do_not(self):
        with patch.object(frappe, 'db', settings_db(0)), patch.object(configuration, 'require_access') as access, \
             patch.object(frappe, 'get_list', return_value=[frappe._dict(name='Example Co')]):
            self.assertEqual(configuration.editor_options('company_record')['items'][0]['value'], 'Example Co')
            access.assert_called_once_with()
            with self.assertRaisesRegex(frappe.PermissionError, ai_features.OFF_MESSAGE):
                configuration.editor_options('report', business_doctype='Customer')

    def test_turning_ai_on_queues_every_event_and_off_builds_nothing(self):
        from relay_core.ai import event_memory
        with patch.object(frappe, 'get_all', return_value=['Fair-001', 'Sale-001']), \
             patch.object(event_memory, 'queue_build') as build, \
             patch('relay_core.ai.knowledge_base.ingest.queue_event') as source:
            event_memory.queue_all()
        self.assertEqual([call.args for call in build.call_args_list], [('Fair-001',), ('Sale-001',)])
        self.assertEqual([call.args for call in source.call_args_list], [('Fair-001',), ('Sale-001',)])
        with patch.object(frappe, 'db', settings_db(0)), patch.object(frappe, 'enqueue') as enqueue:
            self.assertIsNone(event_memory.queue_build('Fair-001'))
        enqueue.assert_not_called()

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

    def test_hub_address_is_shown_to_managers_only(self):
        hub = {'relay_hub_url': 'https://hub.example/mcp', 'relay_hub_account': 'sim-account'}
        with patch.object(settings, 'require_access'), patch.object(settings, 'value', side_effect=hub.get), \
             patch.object(settings.features, 'is_enabled', return_value=True), patch.object(frappe, 'get_roles', return_value=[]):
            for configure, manage, shown in ((False, False, False), (False, True, True), (True, False, True)):
                with self.subTest(configure=configure, manage=manage), patch.object(settings, 'can_configure', return_value=configure), \
                     patch.object(settings, 'can_manage', return_value=manage):
                    result = settings.connection()
                    self.assertEqual((result['url'], result['account']), (hub['relay_hub_url'], hub['relay_hub_account']) if shown else ('', ''))
                    self.assertTrue(result['ai_enabled'] and result['flows_enabled'])

    def test_only_a_system_manager_can_switch_ai(self):
        database = settings_db(0)
        with patch.object(settings, 'require_access'), patch.object(frappe, 'db', database), \
             patch.object(frappe, 'get_roles', return_value=['Relay Communication Manager']):
            with self.assertRaises(frappe.PermissionError):
                settings.save_feature('ai', 1)
        database.set_single_value.assert_not_called()
        with patch.object(settings, 'require_access'), patch.object(frappe, 'db', database), \
             patch.object(frappe, 'get_roles', return_value=['System Manager']), \
             patch('relay_core.ai.event_memory.queue_all') as queue_all:
            settings.save_feature('ai', 1)
            settings.save_feature('folders', 0)
            settings.save_feature('teams', 1)
            with self.assertRaises(frappe.ValidationError):
                settings.save_feature('billing', 1)
        self.assertEqual([call.args for call in database.set_single_value.call_args_list],
                         [('Relay Settings', 'enable_ai_features', 1), ('Relay Settings', 'enable_chat_folders', 0), ('Relay Settings', 'enable_teams', 1)])
        queue_all.assert_called_once_with()  # Events saved while AI was off get their memory once it is on.


if __name__ == '__main__':
    unittest.main()
