import io
import types
import unittest
from unittest.mock import MagicMock, Mock, patch

import frappe

from relay_core import test_mode
from relay_core.hub import HubClient

REMOTE = 'https://hub.example/mcp'
LOCAL = 'http://127.0.0.1:18191/mcp'
TOKEN = 'x' * 64


def throw(message, exc=frappe.ValidationError):
    raise exc(message)


def response(body=b'{}', content_type='application/json'):
    reply = MagicMock()
    reply.__enter__.return_value = reply
    reply.read.side_effect = io.BytesIO(body).read
    reply.headers = {'Content-Type': content_type}
    return reply


class TestModeCase(unittest.TestCase):
    def setUp(self):
        for target in (patch.object(test_mode, 'is_enabled', return_value=True), patch.object(frappe, 'throw', throw)):
            target.start()
            self.addCleanup(target.stop)


class LocalAddressTests(unittest.TestCase):
    def test_only_loopback_and_local_names_are_local(self):
        for url in (LOCAL, 'http://[::1]:9/mcp', 'http://localhost/mcp', 'http://hub.localhost/mcp', 'http://hub.test/mcp', 'http://127.8.0.1/'):
            self.assertTrue(test_mode.is_local_url(url), url)
        for url in (REMOTE, 'https://127.0.0.1.example.com/', 'http://localhost.example.com/', 'http://0.0.0.0/', 'http://10.0.0.5/', '', None):
            self.assertFalse(test_mode.is_local_url(url), url)

    def test_switch_reads_relay_settings_only_on_a_site(self):
        self.assertFalse(test_mode.is_enabled())
        db = Mock()
        with patch.object(frappe, 'local', types.SimpleNamespace(db=db)):
            for stored, expected in ((1, True), ('1', True), (0, False), (None, False)):
                db.get_single_value.return_value = stored
                self.assertIs(test_mode.is_enabled(), expected)
        db.get_single_value.assert_called_with('Relay Settings', 'test_mode')

    def test_switch_off_allows_any_address(self):
        with patch.object(test_mode, 'is_enabled', return_value=False):
            test_mode.ensure_allowed(REMOTE)
            test_mode.ensure_email_allowed()


class HubTests(TestModeCase):
    def test_remote_hub_is_refused_before_network(self):
        hub = HubClient(REMOTE, TOKEN)
        with patch.object(hub.opener, 'open') as opened:
            with self.assertRaises(test_mode.TestModeBlocked) as caught:
                hub.call_tool('whatsapp.execute', {'operation': 'messages.send'})
        opened.assert_not_called()
        self.assertIn('hub.example', str(caught.exception))
        self.assertIsInstance(caught.exception, frappe.ValidationError)

    def test_every_hub_request_shares_the_guard(self):
        hub = HubClient(REMOTE, TOKEN)
        hub.protocol = '2025-06-18'
        calls = (lambda: hub.health(), lambda: hub.media('WhatsApp', 'media-1'), lambda: hub.telegram_send(1, 'hi'),
                 lambda: hub.execute({'operation': 'templates.create'}), lambda: hub.call_tool('channels.list', {}))
        with patch.object(hub.opener, 'open') as opened:
            for call in calls:
                with self.assertRaises(test_mode.TestModeBlocked):
                    call()
        opened.assert_not_called()

    def test_local_simulator_is_allowed(self):
        hub = HubClient(LOCAL, TOKEN)
        hub.protocol = '2025-06-18'
        body = b'{"jsonrpc":"2.0","id":2,"result":{"structuredContent":{"messages":[{"id":"wamid.1"}]}}}'
        with patch.object(hub.opener, 'open', return_value=response(body)) as opened:
            result = hub.call_tool('whatsapp.execute', {'operation': 'messages.send'})
        self.assertEqual(result, {'messages': [{'id': 'wamid.1'}]})
        self.assertEqual(opened.call_args.args[0].full_url, LOCAL)

    def test_email_is_refused_even_through_the_local_simulator(self):
        hub = HubClient(LOCAL, TOKEN)
        with patch.object(hub.opener, 'open') as opened:
            with self.assertRaises(test_mode.TestModeBlocked):
                hub.email_send(['someone@example.com'], 'Subject', 'Body')
        opened.assert_not_called()


class ProviderTests(TestModeCase):
    def test_ai_provider_needs_local_address_or_opt_in(self):
        from relay_core.automation import providers
        model_reply = b'{"choices":[{"finish_reason":"stop","message":{"content":"{\\"ok\\": true}"}}]}'
        with patch('urllib.request.OpenerDirector.open', side_effect=lambda *args, **kwargs: response(model_reply)) as opened:
            with self.assertRaises(test_mode.TestModeBlocked):
                providers.complete('OpenRouter', 'model-1', 'key', 'prompt')
            opened.assert_not_called()
            self.assertEqual(providers.complete('OpenRouter', 'model-1', 'key', 'prompt', allow_in_test_mode=True), {'ok': True})
            spec = providers.request_spec('OpenRouter', 'model-1', 'key', 'prompt')
            with patch.object(providers, 'request_spec', return_value=('http://127.0.0.1:18300/chat', *spec[1:])):
                self.assertEqual(providers.complete('OpenRouter', 'model-1', 'key', 'prompt'), {'ok': True})
        self.assertEqual(opened.call_count, 2)

    def test_transcription_needs_opt_in(self):
        from relay_core.automation import multimodal
        with patch.object(multimodal, 'audio_extension', return_value='ogg'), \
                patch('urllib.request.OpenerDirector.open', return_value=response(b'{"text":"hello"}')) as opened:
            with self.assertRaises(test_mode.TestModeBlocked):
                multimodal.transcribe('whisper-1', 'key', b'audio', 'audio/ogg')
            opened.assert_not_called()
            self.assertEqual(multimodal.transcribe('whisper-1', 'key', b'audio', 'audio/ogg', allow_in_test_mode=True), 'hello')

    def test_ai_model_route_needs_a_local_account_address(self):
        from relay_core.ai import adapter
        model = frappe._dict(enabled=1, account='Account')
        for base_url, allowed in (('', False), ('https://openrouter.ai/api/v1', False), ('http://127.0.0.1:18300/v1', True)):
            account = frappe._dict(enabled=1, base_url=base_url)
            with patch.object(frappe, 'get_doc', side_effect=[model, account]), \
                    patch('frappe_tools.ai.client.route_options', return_value={}), \
                    patch('frappe_tools.ai.agent.get_known_secrets', return_value=[]):
                if allowed:
                    self.assertEqual(adapter.route('Model')[0], account)
                else:
                    with self.assertRaises(test_mode.TestModeBlocked):
                        adapter.route('Model')


class SubmissionTests(TestModeCase):
    def test_refused_send_is_recorded_as_not_sent(self):
        from relay_core import messaging
        action = frappe._dict(name='ACT-1', status='Pending', result=None, outbound_message=None, reload=Mock())
        with patch.object(messaging.frappe, 'db', Mock()), patch.object(messaging, 'internal_save') as saved, \
                patch.object(messaging, 'action_error', return_value='refused'):
            result = messaging.record_submission_error(action, test_mode.TestModeBlocked('refused'))
        self.assertEqual(action.status, 'Rejected')
        self.assertEqual(result['status'], 'Rejected')
        saved.assert_called_once_with(action)

    def test_voice_transcript_passes_the_provider_opt_in(self):
        from relay_core import voice_transcripts
        provider = frappe._dict(provider='OpenAI', model='whisper-1', allow_in_test_mode=1, get_password=lambda field: 'key')
        source = frappe._dict(name='MSG-1')
        audio = types.SimpleNamespace(get_data=lambda: b'audio', mimetype='audio/ogg')
        with patch.object(voice_transcripts, 'message_hash', return_value='other'), \
                patch('relay_core.attachments.read', return_value=audio), \
                patch('relay_core.automation.multimodal.transcribe', return_value='hello') as transcribe, \
                patch.object(voice_transcripts.frappe, 'db', Mock()), \
                patch.object(voice_transcripts.frappe, 'get_doc', return_value=source), \
                patch.object(voice_transcripts.frappe.utils, 'now_datetime', return_value='now'):
            voice_transcripts.create(source, provider)
        self.assertTrue(transcribe.call_args.kwargs['allow_in_test_mode'])


if __name__ == '__main__':
    unittest.main()
