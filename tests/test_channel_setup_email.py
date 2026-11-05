"""Mailboxes are connected from Relay through the Hub; SMTP and IMAP passwords go to the Hub once and are never kept in Core."""
import unittest
from unittest.mock import Mock, patch

from channel_fakes import FakeSite
from relay_core import channel_setup
from relay_core.channel_setup import SetupError, email
from relay_core.hub import HubError

SETTINGS = {'relay_hub_account': 'site-a', 'relay_hub_url': 'https://hub.example.com/mcp', 'relay_hub_token': 't'}
HEALTH = {'channel': 'mail-1', 'label': 'Acme sales', 'address': 'sales@example.com', 'enabled': True, 'connection_status': 'connected',
          'smtp_status': 'connected', 'imap_status': 'connected', 'password_saved': True, 'imap_password_saved': False, 'rejected': 2,
          'server': {'host': 'smtp.example.com', 'port': 587, 'imap_host': 'imap.example.com', 'password': 'never'},
          'sync': [{'mailbox': 'hash', 'last_sync': '2026-11-01 10:00', 'error': '', 'failures': 0, 'backoff': False}]}
FORM = {'from': 'sales@example.com', 'label': 'Acme sales', 'host': 'smtp.example.com', 'port': '587', 'username': 'sales@example.com',
        'password': 'smtp-local-only', 'imap_host': 'imap.example.com', 'imap_port': 993, 'imap_password': '', 'imap_folder': ''}


def rejected(code, message='Hub refused'):
    return HubError('Hub operation was rejected', None, f'{code}: {message} · code {code}')


class MailboxSetupTests(unittest.TestCase):
    def setUp(self):
        self.site = FakeSite(Relay_Channel=[
            {'name': 'Acme sales', 'channel': 'Email', 'account': 'site-a', 'hub_channel': 'mail-1', 'label': 'Acme sales', 'enabled': 1,
             'is_default': 1, 'mailbox_aliases': 'orders@example.com', 'triage_owner': 'owner@example.com'},
            {'name': 'Other mail', 'channel': 'Email', 'account': 'site-b', 'hub_channel': 'mail-9', 'enabled': 1}])
        self.hub = Mock()
        self.answers = {'channels.list': {'channels': [{'key': 'mail-1', 'provider': 'Email'}]}, 'email.mailbox.health': HEALTH,
                        'channels.health': {'Email': [HEALTH, dict(HEALTH, channel='mail-9')]}}
        self.hub.call_tool.side_effect = self.answer
        self.sync, self.publish = Mock(side_effect=self.synced), Mock()
        for item in (patch.object(channel_setup, 'frappe', self.site.frappe), patch.object(email, 'frappe', self.site.frappe),
                     patch.object(channel_setup, 'connection_value', SETTINGS.get), patch.object(email, 'publish', self.publish),
                     patch('relay_core.channel_sync.publish', self.publish), patch('relay_core.channel_sync.sync', self.sync),
                     patch('relay_core.whatsapp.client', return_value=self.hub)):
            item.start()
            self.addCleanup(item.stop)

    def answer(self, tool, arguments):
        result = self.answers.get(tool, {})
        if isinstance(result, Exception):
            raise result
        return result

    def synced(self):
        if not self.site.rows('Relay Channel', {'hub_channel': 'mail-2'}):
            self.site.add('Relay Channel', {'name': 'New mail', 'channel': 'Email', 'account': 'site-a', 'hub_channel': 'mail-2', 'enabled': 1})

    def tools(self):
        return [call.args for call in self.hub.call_tool.call_args_list]

    def test_health_keeps_only_known_fields_and_never_a_password(self):
        rows = email.accounts()
        self.assertEqual(self.tools(), [('channels.health', {'provider': 'Email'})])
        self.assertEqual([row['name'] for row in rows], ['Acme sales'])
        row = rows[0]
        self.assertEqual(row['health']['server'], {'host': 'smtp.example.com', 'port': 587, 'imap_host': 'imap.example.com'})
        self.assertEqual(row['health']['sync'], [{'last_sync': '2026-11-01 10:00', 'error': '', 'failures': 0, 'backoff': False}])
        self.assertNotIn('never', repr(row))

    def test_connect_sends_the_filled_fields_once(self):
        self.answers['email.mailbox.connect'] = dict(HEALTH, channel='mail-2')
        result = email.connect(FORM)
        self.assertEqual(self.tools(), [('email.mailbox.connect', {'from': 'sales@example.com', 'host': 'smtp.example.com', 'port': 587,
                                                                   'username': 'sales@example.com', 'imap_host': 'imap.example.com', 'imap_port': 993,
                                                                   'password': 'smtp-local-only', 'label': 'Acme sales'})])
        self.assertEqual(result['name'], 'New mail')
        self.assertNotIn('smtp-local-only', repr(result) + repr(self.site.tables))

    def test_a_password_goes_to_the_hub_as_typed(self):
        self.answers['email.mailbox.connect'] = dict(HEALTH, channel='mail-2')
        email.connect(dict(FORM, password=' local only pass '))
        self.assertEqual(self.tools()[0][1]['password'], ' local only pass ')

    def test_connect_checks_the_form_before_the_hub(self):
        for change in ({'from': 'not an address'}, {'port': 'abc'}, {'imap_port': 70000}, {'host': 5}, {'password': 7}):
            with self.assertRaises(ValueError):
                email.connect(dict(FORM, **change))
        self.assertEqual(self.tools(), [])

    def test_hub_refusals_become_relay_text(self):
        for code, text in (('host_refused', 'public internet'), ('port_refused', 'port 25'), ('in_use', 'already connected'),
                           ('login_failed', 'could not sign in to the IMAP server')):
            self.answers['email.mailbox.connect'] = rejected(code, 'The Hub could not sign in to the IMAP server.')
            with self.assertRaisesRegex(SetupError, text) as caught:
                email.connect(FORM)
            self.assertNotIn('smtp-local-only', str(caught.exception))

    def test_passwords_never_go_to_a_plain_http_hub(self):
        with patch.object(channel_setup, 'connection_value', dict(SETTINGS, relay_hub_url='http://hub.example.com/mcp').get):
            for call in (lambda: email.connect(FORM), lambda: email.save_settings('Acme sales', {'password': 'new-local-only'})):
                with self.assertRaisesRegex(SetupError, 'only over HTTPS'):
                    call()
        self.assertEqual(self.tools(), [])

    def test_settings_keep_blank_fields_and_core_only_fields(self):
        email.save_settings('Acme sales', {'imap_folder': 'Support', 'password': '', 'enabled': 1, 'label': 'Acme support'})
        self.assertIn(('email.mailbox.settings', {'channel': 'mail-1', 'imap_folder': 'Support', 'enabled': True, 'label': 'Acme support'}), self.tools())
        row = self.site.rows('Relay Channel', {'name': 'Acme sales'})[0]
        self.assertEqual((row.mailbox_aliases, row.triage_owner), ('orders@example.com', 'owner@example.com'))
        for wrong in ({}, {'from': 'other@example.com'}, {'password': ''}):
            with self.assertRaises(ValueError):
                email.save_settings('Acme sales', wrong)

    def test_check_and_remove_use_the_hub_key(self):
        email.check('Acme sales')
        self.assertIn(('email.mailbox.check', {'channel': 'mail-1'}), self.tools())
        with self.assertRaisesRegex(SetupError, 'Confirm'):
            email.remove('Acme sales', False)
        self.answers['email.mailbox.remove'] = {'removed': True}
        self.assertEqual(email.remove('Acme sales', True), {'removed': True})
        with self.assertRaisesRegex(SetupError, 'no longer connected'):
            email.check('Other mail')


if __name__ == '__main__':
    unittest.main()
