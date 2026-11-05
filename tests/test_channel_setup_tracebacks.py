"""Developer mode writes the local variables of every frame into the Error Log traceback; a bot token or a mail password
that a setup endpoint forwards to the Hub must not be among them."""
import unittest
from unittest.mock import patch

import frappe
from frappe.utils import get_traceback

from channel_fakes import FakeSite
from relay_core import channel_setup, channels_api
from relay_core.hub import HubClient

TOKEN = '111111:acme_bot_token_local_only_aaaa'
PASSWORD = 'smtp-local-only-password'
IMAP_PASSWORD = 'imap-local-only-password'
HUB_TOKEN = 'relay_hub_site_token_local_only_0123456789'
SETTINGS = {'relay_hub_account': 'site-a', 'relay_hub_url': 'http://127.0.0.1/mcp', 'relay_hub_token': HUB_TOKEN}


class BrokenTransport:
    """A Hub connection that fails in an unexpected way after Core built the request, as a bug would."""

    def __init__(self, test):
        self.test = test

    def open(self, request, timeout=None):
        self.test.wire = request.data
        raise RuntimeError('the Hub transport broke')


class SetupTracebackTests(unittest.TestCase):
    def setUp(self):
        self.site = FakeSite(Relay_Channel=[{'name': 'Acme bot', 'channel': 'Telegram', 'account': 'site-a', 'hub_channel': 'tg-1',
                                             'label': 'Acme Textiles', 'enabled': 1, 'is_default': 1}])
        hub = HubClient(SETTINGS['relay_hub_url'], SETTINGS['relay_hub_token'])
        hub.protocol, hub.opener, self.wire = '2025-06-18', BrokenTransport(self), b''
        for item in (patch.object(channel_setup, 'frappe', self.site.frappe), patch.object(channel_setup, 'connection_value', SETTINGS.get),
                     patch.object(channels_api, 'system_manager'), patch('relay_core.whatsapp.client', return_value=hub),
                     patch.object(frappe.local, 'conf', frappe._dict(developer_mode=1), create=True)):
            item.start()
            self.addCleanup(item.stop)

    def error_log_traceback(self, form):
        """The traceback Frappe's Error Log keeps for an endpoint call that fails at the Hub."""
        with patch.object(frappe.local, 'form_dict', frappe._dict(form), create=True), self.assertRaises(RuntimeError):
            try:
                frappe.call(getattr(channels_api, form['cmd']), **form)
            except RuntimeError:
                text = get_traceback(with_context=True)
                raise
        self.assertIn('_request', text)
        self.assertIn('hub_call', text)
        self.assertNotIn(HUB_TOKEN, text)
        return text

    def test_a_bot_token_is_not_in_the_traceback_of_a_failed_connect_or_settings_change(self):
        for form in ({'cmd': 'connect', 'channel': 'Telegram', 'values': {'label': 'Acme Textiles'}, 'secrets': {'bot_token': TOKEN}},
                     {'cmd': 'save_settings', 'channel': 'Acme bot', 'settings': {'label': 'Acme Sales'}, 'secrets': {'bot_token': TOKEN}}):
            text = self.error_log_traceback(form)
            self.assertNotIn(TOKEN, text)
            self.assertNotIn('acme_bot_token', text)
            self.assertIn(TOKEN.encode(), self.wire)

    def test_mail_passwords_are_not_in_the_traceback_of_a_failed_connect(self):
        text = self.error_log_traceback({'cmd': 'connect', 'channel': 'Email',
                                         'values': {'from': 'sales@example.com', 'host': 'smtp.example.com', 'label': 'Acme sales'},
                                         'secrets': {'password': PASSWORD, 'imap_password': IMAP_PASSWORD}})
        for secret in (PASSWORD, IMAP_PASSWORD, 'local-only'):
            self.assertNotIn(secret, text)
        self.assertIn(PASSWORD.encode(), self.wire)
        self.assertIn(IMAP_PASSWORD.encode(), self.wire)


if __name__ == '__main__':
    unittest.main()
