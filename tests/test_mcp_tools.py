import importlib
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import relay_core.mcp_tools  # noqa: F401  Registers every tool.
from relay_core.mcp_tools import coordination, registry
from relay_core.mcp_tools.registry import READ, SEND, WRITE, check

CON, MSG, KEY, CH = 'RELAY-CON-0000000001', 'RELAY-MSG-0000000002', 'agent-key-0001', 'yrp-319480'
HUB_ONLY = ('enrollment', 'delivery', 'telegram_delivery', 'legacy', 'operations', 'save_connection', 'save_feature',
            'recovery', 'deliveries')

# tool: (arguments, [(module, function, return value)], expected call of the first target as (args, kwargs) or None)
CASES = {
    'guide_read': ({}, [], None),
    'channels_list': ({}, [('relay_core.api', 'channel_options', {'items': []})], ((), {})),
    'settings_read': ({}, [('relay_core.settings', 'connection', {}), ('relay_core.api', 'capabilities', {})], ((), {})),
    'account_overview': ({}, [('relay_core.overview', 'read', {}), ('relay_core.queue_counts', 'read', {})], ((), {})),
    'records_types': ({}, [('relay_core.api', 'business_types', ['Customer'])], ((), {})),
    'records_list': ({'doctype': 'Customer', 'query': 'ac'}, [('relay_core.business_inbox', 'records', {'items': []})],
                     (('Customer', 'ac', None), {})),
    'records_messages': ({'doctype': 'Customer', 'name': 'C1', 'limit': 5}, [('relay_core.business_inbox', 'messages', {'items': []})],
                         (('Customer', 'C1'), {'before': None, 'channel': None, 'limit': 5})),
    'inbox_list': ({'mode': 'unread', 'query': 'ram'}, [('relay_core.inbox', 'directory', {'items': [], 'next': None})],
                   ((), {'query': 'ram', 'after': None, 'starred': 0, 'folder': '', 'mode': 'unread', 'team': None,
                         'channel': None, 'business_type': None})),
    'messages_list_unread': ({'limit': 5}, [('relay_core.inbox', 'directory', {'items': [{'name': CON, 'unread': 2}], 'next': None}),
                                            ('relay_core.api', 'messages', {'items': [{'name': MSG, 'direction': 'Incoming'}]})],
                             ((), {'mode': 'unread', 'channel': None, 'after': None})),
    'messages_list': ({'contact': CON, 'limit': 3}, [('relay_core.api', 'messages', {'items': [], 'has_more': False, 'first': None, 'last': None})],
                      ((CON,), {'before': None, 'channel': None, 'limit': 3, 'query': ''})),
    'messages_read_one': ({'message': MSG}, [('relay_core.api', 'message_context', {'contact': CON, 'items': [{'name': MSG}]}),
                                             ('relay_core.messaging', 'reply_window', {'open': True})], ((MSG,), {})),
    'chat_mark_read': ({'contact': CON, 'read': 1}, [('relay_core.message_reads', 'mark_chat', {})], ((), {'contact': CON, 'read': 1})),
    'chat_update': ({'contact': CON, 'starred': 1}, [('relay_core.inbox', 'update', {})], ((CON,), {'starred': 1, 'folder': None})),
    'chat_comment_add': ({'contact': CON, 'body': 'note', 'request_key': 'k' * 16}, [('relay_core.collaboration', 'add', {})],
                         ((CON, 'note', 'k' * 16), {'messages': None, 'mentions': None})),
    'chat_send_text': ({'message': MSG, 'text': 'Hi', 'request_key': KEY}, [('relay_core.messaging', 'send', {})],
                       ((MSG, 'text', {'text': 'Hi'}, KEY), {'quote': 1, 'via': None})),
    'chat_send_media': ({'number': '919876543210', 'channel': CH, 'media_url': 'https://x.test/a.pdf', 'media_type': 'document',
                         'request_key': KEY}, [('relay_core.messaging_api', 'send_media', {})],
                        (('919876543210', 'https://x.test/a.pdf', 'document'), {'caption': None, 'filename': None, 'key': KEY, 'channel': CH})),
    'chat_send_other': ({'message': MSG, 'kind': 'reaction', 'data': {'emoji': 'ok'}, 'request_key': KEY},
                        [('relay_core.messaging', 'send', {})], ((MSG, 'reaction', {'emoji': 'ok'}, KEY), {})),
    'chat_send_template': ({'number': '919876543210', 'channel': CH, 'template': 'hello', 'language': 'en', 'request_key': KEY},
                           [('relay_core.messaging_api', 'send_template', {})],
                           (('919876543210', 'hello', 'en'), {'params': None, 'header_media_url': None, 'key': KEY,
                                                              'business_doctype': None, 'business_name': None, 'channel': CH})),
    'chat_send_email': ({'to': ['a@b.test'], 'subject': 'S', 'body': 'B', 'channel': CH, 'request_key': KEY},
                        [('relay_core.email', 'send', {})],
                        ((['a@b.test'], 'S', 'B'), {'cc': None, 'request_key': KEY, 'message': None, 'channel_name': CH})),
    'chat_send_telegram': ({'chat_id': -100, 'text': 't', 'channel': 'Bot', 'request_key': KEY}, [('relay_core.telegram', 'send', {})],
                           ((-100, 't'), {'reply_to': 0, 'message_thread_id': 0, 'request_key': KEY, 'channel': 'Bot'})),
    'chat_start': ({'contact': 'Ravi', 'channel': CH, 'business_doctype': 'Customer', 'business_name': 'C1', 'kind': 'template',
                    'template': {'name': 'hello', 'language': 'en'}, 'request_key': KEY},
                   [('relay_core.conversation_start', 'send_business', {})],
                   (('Ravi', CH, 'whatsapp', {'operation': 'templates.send', 'arguments': {'name': 'hello', 'language': 'en'}}, KEY,
                     'Customer', 'C1'), {})),
    'send_status': ({'batch': 'b-1'}, [('relay_core.messaging_api', 'send_status', {'results': []})], (('b-1',), {})),
    'send_retry': ({'message': MSG}, [('relay_core.messaging', 'retry', {})], ((), {'message': MSG})),
    'contacts_search': ({'query': 'ra'}, [('relay_core.api', 'contact_directory', {'items': []})],
                        (('ra',), {'after': None, 'business_type': None, 'business_name': None})),
    'contacts_read': ({'contact': CON}, [('relay_core.api', 'contact_profile', {})], ((CON,), {})),
    'contacts_create': ({'name': 'Ravi', 'phone': '919876543210', 'channel': CH}, [('relay_core.contacts', 'create', {})],
                        (('Ravi', '919876543210', CH), {'links': None})),
    'contacts_set_links': ({'contact': 'Ravi', 'links': [{'doctype': 'Customer', 'name': 'C1'}]}, [('relay_core.contacts', 'set_links', {})],
                           (('Ravi', [{'doctype': 'Customer', 'name': 'C1'}]), {})),
    'contacts_set_primary': ({'contact': 'Ravi', 'doctype': 'Customer', 'name': 'C1'}, [('relay_core.contacts', 'set_primary', {})],
                             (('Ravi', 'Customer', 'C1'), {})),
    'tickets_list': ({'query': 'late'}, [('relay_core.tickets', 'directory', {'items': []})],
                     ((), {'query': 'late', 'ticket_status': None, 'mine': None, 'after': None})),
    'tickets_read': ({'name': 'TKT-00001'}, [('relay_core.tickets', 'read', {}), ('relay_core.tickets', 'transcript', {})], (('TKT-00001',), {})),
    'tickets_create': ({'subject': 'Late', 'messages': [MSG]}, [('relay_core.tickets', 'create', {})],
                       (('Late', [MSG]), {'brief': '', 'ticket_type': None})),
    'tickets_update': ({'name': 'TKT-00001', 'action': 'status', 'value': 'Closed'}, [('relay_core.tickets', 'update_status', {})],
                       (('TKT-00001', 'Closed'), {})),
    'templates_list': ({'status': 'APPROVED'}, [('relay_core.whatsapp_templates', 'directory', {'data': [{'status': 'APPROVED'}, {'status': 'PENDING'}]})],
                       ((None,), {})),
    'templates_create': ({'channel': CH, 'name': 'order_ready', 'language': 'en', 'category': 'UTILITY',
                          'components': [{'type': 'BODY', 'text': 'Ready'}]}, [('relay_core.whatsapp', 'execute', {'id': '1'})],
                         (('templates.create', {'name': 'order_ready', 'language': 'en', 'category': 'UTILITY',
                                                'parameter_format': 'positional', 'components': [{'type': 'BODY', 'text': 'Ready'}]}),
                          {'channel': CH})),
    'templates_update': ({'channel': CH, 'id': '12', 'components': [{'type': 'BODY', 'text': 'x'}]}, [('relay_core.whatsapp', 'execute', {})],
                         (('templates.update', {'id': '12', 'components': [{'type': 'BODY', 'text': 'x'}]}), {'channel': CH})),
    'templates_delete': ({'channel': CH, 'name': 'order_ready', 'confirm': True}, [('relay_core.whatsapp', 'execute', {})],
                         (('templates.delete', {'name': 'order_ready'}), {'channel': CH})),
    'templates_media_upload': ({'channel': CH, 'media_type': 'image', 'filename': 'a.png', 'content_base64': 'AA=='},
                               [('relay_core.template_media', 'upload', {'id': '9'})], ((CH, 'image', 'a.png', 'AA=='), {})),
    'campaigns_list': ({'status': 'Draft'}, [('relay_core.campaigns', 'directory', {'items': []})],
                       ((), {'after': None, 'query': '', 'status': 'Draft'})),
    'campaigns_read': ({'name': 'Promo'}, [('relay_core.bulk_campaigns', 'read', {})], (('Promo',), {'after': None, 'status': None})),
    'campaigns_create': ({'title': 'Promo', 'channel': CH, 'rows': [{'phone': '91'}], 'template_name': 'hello', 'language': 'en'},
                         [('relay_core.bulk_campaigns', 'create_with_rows', {})],
                         (('Promo', [{'phone': '91'}]), {'message': None, 'template_name': 'hello', 'language': 'en', 'mapping': None,
                                                         'start': 0, 'channel': CH, 'reply_window_hours': 72})),
    'campaigns_append': ({'name': 'Promo', 'rows': [{'phone': '91'}]}, [('relay_core.bulk_campaigns', 'append_rows', {})],
                         (('Promo', [{'phone': '91'}]), {})),
    'campaigns_retry_failed': ({'name': 'Promo', 'confirm': True}, [('relay_core.bulk_campaigns', 'retry_failed', {})], (('Promo',), {})),
    'flows_list': ({}, [('relay_core.flows.service', 'directory', {})], ((), {'after': None, 'query': ''})),
    'flows_read': ({'name': 'F1'}, [('relay_core.flows.service', 'read', {})], (('F1',), {})),
    'flows_runs': ({'flow': 'F1'}, [('relay_core.flows.service', 'runs', {})], (('F1',), {'after': None})),
    'flows_validate': ({'values': {'title': 'x'}}, [('relay_core.flows.service', 'validate_draft', {})], (({'title': 'x'},), {'name': None})),
    'flows_save': ({'values': {'title': 'x'}}, [('relay_core.flows.service', 'save', {})], (({'title': 'x'},), {'name': None})),
    'flows_publish': ({'name': 'F1', 'action': 'disable', 'confirm': True}, [('relay_core.flows.service', 'set_enabled', {})], (('F1', 0), {})),
}
COVERED_ELSEWHERE = {'campaigns_validate', 'campaigns_control', 'chat_claim', 'chat_release', 'changes_since', 'activity_log'}


def run_case(name, arguments, targets):
    mocks = []
    with patch.object(coordination, 'with_actors', side_effect=lambda rows: rows), \
            patch.object(coordination, 'active_claim', return_value=None):
        patches = []
        for module, function, value in targets:
            mock = Mock(return_value=value)
            patches.append(patch.object(importlib.import_module(module), function, mock))
            mocks.append(mock)
        for item in patches:
            item.start()
        try:
            result = registry.TOOLS[name].handler(**arguments)
        finally:
            for item in patches:
                item.stop()
    return result, mocks


class RegistryTests(unittest.TestCase):
    def test_every_listed_tool_is_documented_and_safe_by_class(self):
        for entry in registry.listed():
            self.assertRegex(entry.name, registry.NAME)
            self.assertIn(entry.safety, (READ, WRITE, SEND))
            for key, _ in registry.DOC_PARTS:
                self.assertTrue(entry.doc.get(key), f'{entry.name} lacks {key}')
            self.assertFalse(entry.schema['additionalProperties'])
            self.assertTrue(set(entry.schema['required']) <= set(entry.schema['properties']), entry.name)
            self.assertIn('Use when:', entry.description)
            self.assertEqual(entry.annotations['readOnlyHint'], entry.safety == READ)

    def test_every_customer_send_requires_a_request_key_or_confirm(self):
        # Template create/update are Meta reviews, retry has its own key, campaign control checks confirm per action.
        exempt = {'templates_create', 'templates_update', 'send_retry', 'campaigns_control'}
        for entry in registry.listed():
            if entry.safety == SEND and entry.name not in exempt:
                self.assertTrue({'request_key', 'confirm'} & set(entry.schema['required']), entry.name)

    def test_chat_tools_take_after_message(self):
        chat = {entry.name for entry in registry.listed() if entry.chat}
        self.assertEqual(chat, {'chat_send_text', 'chat_send_media', 'chat_send_other', 'chat_send_template', 'chat_send_email',
                                'chat_send_telegram', 'chat_start', 'send_retry'})
        for name in chat:
            self.assertIn('after_message', registry.TOOLS[name].schema['properties'])

    def test_no_hub_only_or_settings_write_function_is_exposed(self):
        import re

        from relay_core.mcp_tools import legacy
        hub_only = re.compile(r'relay_core(\.| import )(' + '|'.join(HUB_ONLY) + r')\b|save_connection|save_feature')
        for area in ('account', 'campaigns', 'chats', 'contacts', 'flows', 'inbox', 'send', 'templates', 'tickets'):
            self.assertIsNone(hub_only.search(Path(f'relay_core/mcp_tools/{area}.py').read_text()), area)
        self.assertFalse({module for module, _ in legacy.TARGETS.values()} & {'relay_core.' + word for word in HUB_ONLY})

    def test_legacy_names_still_resolve_but_are_not_listed(self):
        listed = {entry.name for entry in registry.listed()}
        for name in ('relay.messaging.send', 'relay.whatsapp.send_text', 'relay.campaigns.create', 'relay.flows.generate'):
            self.assertIsNotNone(registry.find(name))
            self.assertNotIn(name, listed)

    def test_every_listed_tool_has_a_unit_case(self):
        self.assertEqual(set(CASES) | COVERED_ELSEWHERE, {entry.name for entry in registry.listed()})


class SchemaTests(unittest.TestCase):
    def test_sample_arguments_are_accepted(self):
        for name, (arguments, _, _) in CASES.items():
            self.assertIsNone(check(registry.TOOLS[name].schema, arguments), name)

    def test_unknown_field_wrong_enum_and_type_are_rejected(self):
        schema = registry.TOOLS['inbox_list'].schema
        self.assertIn('unknown field', check(schema, {'ignore_permissions': 1}))
        self.assertIn('must be one of', check(schema, {'mode': 'everything'}))
        self.assertIn('must be integer', check(schema, {'starred': True}))
        self.assertIn('invalid format', check(registry.TOOLS['messages_list'].schema, {'contact': 'frappe.db.sql'}))

    def test_sends_refuse_missing_or_short_request_key(self):
        schema = registry.TOOLS['chat_send_text'].schema
        self.assertIn('request_key is required', check(schema, {'message': MSG, 'text': 'Hi'}))
        self.assertIn('invalid format', check(schema, {'message': MSG, 'text': 'Hi', 'request_key': 'short'}))

    def test_confirm_must_be_literal_true(self):
        schema = registry.TOOLS['templates_delete'].schema
        for value in ('true', 1, False):
            self.assertIn('must be true', check(schema, {'channel': CH, 'name': 'x', 'confirm': value}))
        self.assertIn('confirm is required', check(schema, {'channel': CH, 'name': 'x'}))


class WrappedCallTests(unittest.TestCase):
    def test_each_tool_calls_its_core_function_with_the_arguments(self):
        for name, (arguments, targets, expected) in CASES.items():
            with self.subTest(tool=name):
                result, mocks = run_case(name, arguments, targets)
                for mock in mocks:
                    mock.assert_called_once()
                if expected:
                    self.assertEqual((mocks[0].call_args.args, mocks[0].call_args.kwargs), expected)
                self.assertIsNotNone(result)

    def test_template_status_filter_and_unread_grouping(self):
        result, _ = run_case('templates_list', *CASES['templates_list'][:2])
        self.assertEqual(result['data'], [{'status': 'APPROVED'}])
        result, mocks = run_case('messages_list_unread', *CASES['messages_list_unread'][:2])
        self.assertEqual(result['chats'][0]['messages'], [{'name': MSG, 'direction': 'Incoming'}])
        self.assertEqual(mocks[1].call_args.kwargs['limit'], 2)

    def test_tool_errors_are_specific_and_safe(self):
        import frappe
        with patch('relay_core.messaging.send', side_effect=frappe.ValidationError('Outside the 24-hour reply window')), \
                patch.object(coordination, 'run', side_effect=lambda entry, arguments: entry.handler(**arguments)):
            result = registry.call('chat_send_text', {'message': MSG, 'text': 'Hi', 'request_key': KEY})
        self.assertTrue(result['isError'])
        self.assertEqual(result['content'][0]['text'], 'Outside the 24-hour reply window')
        with patch('relay_core.api.contact_profile', side_effect=frappe.PermissionError), patch.object(frappe, 'log_error'):
            self.assertTrue(registry.call('contacts_read', {'contact': CON})['content'][0]['text'].startswith('Not permitted'))
        with patch('relay_core.api.contact_profile', side_effect=RuntimeError('secret-token-xyz')), patch.object(frappe, 'log_error'):
            text = registry.call('contacts_read', {'contact': CON})['content'][0]['text']
        self.assertNotIn('secret-token-xyz', text)
        self.assertIn('unknown field', registry.call('contacts_read', {'contact': CON, 'x': 1})['content'][0]['text'])

    def test_chat_start_needs_the_argument_of_its_kind(self):
        with patch.object(coordination, 'run', side_effect=lambda entry, arguments: entry.handler(**arguments)):
            result = registry.call('chat_start', {'contact': 'Ravi', 'channel': CH, 'business_doctype': 'Customer',
                                                  'business_name': 'C1', 'kind': 'text', 'request_key': KEY})
        self.assertEqual(result['content'][0]['text'], 'kind text needs the text argument')


class CampaignGuardTests(unittest.TestCase):
    def setUp(self):
        import relay_core.bulk_campaigns as bulk
        draft = {'name': 'Promo', 'status': 'Draft', 'operation': 'templates.send', 'validated': True, 'last_error': '',
                 'counts': {'total': 12, 'skipped': 2}, 'issues': [], 'error_rows': []}
        self.control = Mock(return_value={'status': 'Running'})
        self.patches = [patch.object(bulk, 'read', Mock(return_value=draft)), patch.object(bulk, 'window', Mock()),
                        patch.object(bulk, 'control', self.control)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()

    def handler(self, **arguments):
        return registry.TOOLS['campaigns_control'].handler(name='Promo', **arguments)

    def test_validate_reports_the_sendable_count(self):
        result = registry.TOOLS['campaigns_validate'].handler(name='Promo')
        self.assertEqual((result['recipients'], result['ready'], result['window']), (10, True, None))

    def test_start_needs_confirm_and_the_validated_count(self):
        with self.assertRaisesRegex(registry.ToolError, 'confirm'):
            self.handler(action='start', expected_recipients=10)
        with self.assertRaisesRegex(registry.ToolError, 'now has 10 recipients'):
            self.handler(action='start', confirm=True, expected_recipients=11)
        self.control.assert_not_called()
        self.handler(action='start', confirm=True, expected_recipients=10)
        self.control.assert_called_once_with('Promo', 'start', scheduled_at=None)

    def test_pause_needs_no_confirm(self):
        self.handler(action='pause')
        self.control.assert_called_once_with('Promo', 'pause', scheduled_at=None)


if __name__ == '__main__':
    unittest.main()
