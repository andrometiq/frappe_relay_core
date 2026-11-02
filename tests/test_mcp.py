import json
import types
import unittest
from unittest.mock import Mock, patch

import frappe
from relay_core import mcp
from relay_core.mcp_tools import coordination, registry


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.headers = {'Authorization': 'token key:secret'}
        self.body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}}
        self.fake = types.SimpleNamespace(session=types.SimpleNamespace(user='agent@x.test'), get_request_header=self.headers.get,
                                          request=types.SimpleNamespace(method='POST', content_length=300, get_json=lambda: self.body),
                                          db=types.SimpleNamespace(rollback=Mock()), log_error=Mock())
        self.patches = [patch.object(mcp, 'frappe', self.fake), patch.object(mcp, 'require_access')]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()

    def call(self):
        response = mcp.endpoint()
        return response.status_code, response.get_data(as_text=True)

    def test_token_origin_get_and_size_rules(self):
        self.assertEqual(self.call()[0], 200)
        self.fake.request.method = 'GET'
        self.assertEqual(self.call()[0], 405)
        self.fake.request.method = 'POST'
        del self.headers['Authorization']
        self.assertEqual(self.call()[0], 401)  # A cookie session has no token header.
        self.headers['Authorization'] = 'token key:secret'
        self.fake.session.user = 'Guest'
        self.assertEqual(self.call()[0], 401)
        self.fake.session.user = 'agent@x.test'
        self.headers['Origin'] = 'https://browser.test'
        self.assertEqual(self.call()[0], 403)
        del self.headers['Origin']
        for length in (0, 2 * 1024 * 1024, 7 * 1024 * 1024 + 1):
            self.fake.request.content_length = length
            self.assertEqual(self.call()[0], 413, length)

    def test_large_requests_only_for_media_upload(self):
        self.fake.request.content_length = 2 * 1024 * 1024
        self.body.update(method='tools/call', params={'name': 'templates_media_upload', 'arguments': {}})
        with patch.object(registry, 'call', return_value={'isError': False}) as call:
            self.assertEqual(self.call()[0], 200)
        call.assert_called_once()

    def test_role_check_runs_before_anything(self):
        mcp.require_access.side_effect = frappe.PermissionError
        with self.assertRaises(frappe.PermissionError):
            mcp.endpoint()

    def test_notifications_never_run_tools(self):
        self.body = {'jsonrpc': '2.0', 'method': 'tools/call', 'params': {'name': 'chat_send_text', 'arguments': {}}}
        with patch.object(registry, 'call') as call:
            self.assertEqual(self.call()[0], 400)
            self.body['method'] = 'notifications/initialized'
            self.assertEqual(self.call()[0], 202)
        call.assert_not_called()

    def test_unexpected_failures_hide_their_text(self):
        self.body.update(method='tools/call', params={'name': 'guide_read', 'arguments': {}})
        with patch.object(registry, 'call', side_effect=RuntimeError('secret-provider-token')):
            status, text = self.call()
        self.assertEqual(status, 200)
        self.assertNotIn('secret-provider-token', text)
        self.assertEqual(json.loads(text)['error']['code'], -32603)
        self.fake.db.rollback.assert_called_once()

    def test_tool_errors_roll_back(self):
        self.body.update(method='tools/call', params={'name': 'guide_read', 'arguments': {}})
        with patch.object(registry, 'call', return_value={'isError': True, 'content': []}):
            self.assertTrue(json.loads(self.call()[1])['result']['isError'])
        self.fake.db.rollback.assert_called_once()


class ProtocolTests(unittest.TestCase):
    def test_initialize_returns_instructions_and_remembers_the_client(self):
        with patch.object(coordination, 'remember_client') as remember:
            result = mcp.dispatch('initialize', {'protocolVersion': '2025-11-25', 'clientInfo': {'name': 'agent-a'}})
        remember.assert_called_once_with({'name': 'agent-a'})
        self.assertEqual(result['protocolVersion'], '2025-06-18')
        self.assertIn('guide_read', result['instructions'])
        self.assertIn('resources', result['capabilities'])

    def test_tools_list_shows_only_documented_area_tools(self):
        tools = mcp.dispatch('tools/list', {})['tools']
        names = [entry['name'] for entry in tools]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn('chat_send_text', names)
        self.assertFalse([name for name in names if name.startswith('relay.')])
        self.assertTrue(all({'name', 'description', 'inputSchema', 'annotations'} <= set(entry) for entry in tools))

    def test_guide_resource(self):
        self.assertEqual(mcp.dispatch('resources/list', {})['resources'][0]['uri'], 'relay://guide')
        text = mcp.dispatch('resources/read', {'uri': 'relay://guide'})['contents'][0]['text']
        self.assertIn('Safe polling loop', text)
        with self.assertRaises(mcp.ProtocolError):
            mcp.dispatch('resources/read', {'uri': 'relay://secrets'})

    def test_unknown_methods_and_tools_are_protocol_errors(self):
        for method, params in (('frappe.db.sql', {}), ('tools/call', {'name': 'frappe.db.sql', 'arguments': {}}),
                               ('tools/call', {'name': 'guide_read', 'arguments': []})):
            with self.assertRaises(mcp.ProtocolError):
                mcp.dispatch(method, params)

    def test_legacy_alias_calls_the_same_core_function(self):
        import relay_core.messaging_api as api
        with patch.object(api, 'send_text', return_value={'status': 'Submitted'}) as send, \
                patch.object(coordination, 'audit'):
            result = mcp.dispatch('tools/call', {'name': 'relay.whatsapp.send_text',
                                                 'arguments': {'number': '919876543210', 'body': 'Hi', 'key': 'k-1'}})
        send.assert_called_once_with(number='919876543210', body='Hi', key='k-1')
        self.assertEqual(result['structuredContent'], {'status': 'Submitted'})

    def test_generated_docs_match_the_registry(self):
        from pathlib import Path

        from relay_core.mcp_tools.guide import markdown
        self.assertEqual(Path('docs/mcp.md').read_text(), markdown() + '\n')


if __name__ == '__main__':
    unittest.main()
