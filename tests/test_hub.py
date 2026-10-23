import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from relay_core.config import load_env
from relay_core.hub import HubClient, HubError

class ConfigTests(unittest.TestCase):
    def test_group_send_preserves_queue_receipt(self):
        hub=HubClient('http://127.0.0.1:1234/mcp','x'*64)
        receipt={'delivery':{'state':'queued','key':'group-test'}}
        with patch.object(hub,'call_tool',return_value=receipt) as call:
            self.assertEqual(hub.telegram_send(-100123,'hello',reply_to=4,message_thread_id=7,request_key='group-test'),receipt)
        call.assert_called_once_with('telegram.message',{'operation':'text','chat_id':-100123,'text':'hello','reply_to':4,'message_thread_id':7,'request_key':'group-test'})

    def test_provider_error_metadata_is_strictly_allowlisted(self):
        hub = HubClient('http://127.0.0.1:1234/mcp', 'x'*64); hub.protocol = '2025-06-18'
        metadata = {'provider': 'Telegram', 'secret': 'never-expose', 'error': {'http_status': 429,
            'code': 429, 'retry_after': 17, 'migrate_to_chat_id': -100123, 'outcome_unknown': False,
            'description': 'never-expose', 'token': 'never-expose'}}
        with patch.object(hub, '_request', return_value={'isError': True, 'structuredContent': metadata}):
            with self.assertRaises(HubError) as caught: hub.telegram_groups('info', chat_id=-1001)
        self.assertEqual(caught.exception.metadata, {'provider': 'Telegram', 'error': {
            'http_status': 429, 'code': 429, 'retry_after': 17, 'migrate_to_chat_id': -100123,
            'outcome_unknown': False}})
        self.assertNotIn('never-expose', str(caught.exception))

    def test_auth_denial_is_known_not_submitted(self):
        from urllib.error import HTTPError
        for code in (401,403):
            hub=HubClient('http://127.0.0.1:1234/mcp','x'*64)
            with patch.object(hub.opener,'open',side_effect=HTTPError(hub.url,code,'Denied',{},None)):
                with self.assertRaises(HubError) as caught:hub.initialize()
            self.assertEqual(caught.exception.metadata,{'provider':'Hub','error':{'http_status':code,'outcome_unknown':False}})
            self.assertIn('saved Hub API credential',str(caught.exception))

    def test_literal_values_and_environment_precedence(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/'.env'
            path.write_text("RELAY_HUB_URL='http://127.0.0.1:18081/mcp'\nRELAY_HUB_TOKEN=$(not-executed)\n")
            with patch.dict(os.environ, {'RELAY_HUB_URL':'https://hub.example/mcp'}):
                config = load_env(path)
            self.assertEqual(config['RELAY_HUB_TOKEN'], '$(not-executed)')
            self.assertEqual(config['RELAY_HUB_URL'], 'https://hub.example/mcp')
    def test_unknown_key_rejected(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'.env';path.write_text('PATH=bad')
            with self.assertRaises(ValueError):load_env(path)
    def test_insecure_and_credential_urls_rejected(self):
        for url in ['http://example.com/mcp','https://u:p@example.com/mcp','file:///mcp','https://example.com/mcp?token=x']:
            with self.assertRaises(ValueError):HubClient(url,'x'*64)
    def test_https_mount_prefix_supported(self):
        self.assertEqual(HubClient("https://hub.example/hub/mcp","x"*64).url,"https://hub.example/hub/mcp")
        with self.assertRaises(ValueError):HubClient("https://hub.example/../mcp","x"*64)
    def test_short_token_rejected(self):
        with self.assertRaises(ValueError):HubClient('http://127.0.0.1:18081/mcp','short')

@unittest.skipUnless(os.environ.get('RELAY_LIVE_TEST') == '1', 'opt-in local Hub integration')
class LiveHubTests(unittest.TestCase):
    def test_core_handshake_and_health(self):
        self.assertEqual(HubClient.from_env().health(), {'status':'ready','service':'relay_hub'})
    def test_wrong_token_rejected(self):
        from relay_core.hub import HubError
        good = HubClient.from_env()
        with self.assertRaisesRegex(HubError, r'\(401\)'):
            HubClient(good.url, 'invalid-'*8).health()
