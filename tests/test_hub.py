import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from relay_core.config import load_env
from relay_core.hub import HubClient

class ConfigTests(unittest.TestCase):
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
