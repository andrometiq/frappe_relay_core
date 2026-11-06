"""Telegram bots are connected from Relay through the Hub; the bot token goes to the Hub once and is never kept in Core."""
import json
import unittest
from unittest.mock import Mock, patch

from channel_fakes import FakeSite
from relay_core import channel_setup, channels_api
from relay_core.channel_setup import SetupError, telegram
from relay_core.hub import HubError, revealed

SETTINGS = {'relay_hub_account': 'site-a', 'relay_hub_url': 'http://127.0.0.1/mcp', 'relay_hub_token': 't'}
TOKEN = '111111:acme_bot_token_local_only_aaaa'
HEALTH = {'channel': 'tg-1', 'label': 'Acme Textiles', 'username': 'acme_textiles_bot', 'bot_id': '111111', 'enabled': True,
          'webhook_status': 'registered', 'checked_at': '2026-11-01T10:00:00Z', 'check_error': '', 'token_saved': True, 'unexpected': 'dropped'}


def rejected(code, message='Hub refused'):
    return HubError('Hub operation was rejected', None, f'{code}: {message} · code {code}')


class TelegramSetupTests(unittest.TestCase):
    def setUp(self):
        self.site = FakeSite(Relay_Channel=[
            {'name': 'Acme bot', 'channel': 'Telegram', 'account': 'site-a', 'hub_channel': 'tg-1', 'label': 'Acme Textiles', 'enabled': 1, 'is_default': 1},
            {'name': 'Sales bot', 'channel': 'Telegram', 'account': 'site-a', 'hub_channel': 'tg-2', 'label': 'Acme Sales', 'enabled': 0, 'is_default': 0},
            {'name': 'Sales line', 'channel': 'WhatsApp', 'account': 'site-a', 'hub_channel': 'wa-120', 'enabled': 1},
            {'name': 'Other bot', 'channel': 'Telegram', 'account': 'site-b', 'hub_channel': 'tg-9', 'enabled': 1}])
        self.hub = Mock()
        self.answers = {'channels.list': {'channels': [{'key': 'tg-1', 'provider': 'Telegram'}, {'key': 'wa-120', 'provider': 'WhatsApp'}]},
                        'telegram.bot.health': HEALTH, 'channels.health': {'Telegram': [HEALTH]}}
        self.hub.call_tool.side_effect = self.answer
        self.sync, self.publish = Mock(side_effect=self.synced), Mock()
        for item in (patch.object(channel_setup, 'frappe', self.site.frappe), patch.object(telegram, 'frappe', self.site.frappe),
                     patch.object(channel_setup, 'connection_value', SETTINGS.get), patch.object(telegram, 'publish', self.publish),
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
        """The channel sync adds the bot the Hub just connected, as channel_sync.store does."""
        if not self.site.rows('Relay Channel', {'hub_channel': 'tg-3'}):
            self.site.add('Relay Channel', {'name': 'New bot', 'channel': 'Telegram', 'account': 'site-a', 'hub_channel': 'tg-3', 'enabled': 1})

    def tools(self):
        """The tool calls as the Hub gets them: a Secret is revealed only in the request body."""
        return [(tool, json.loads(json.dumps(arguments, default=revealed))) for tool, arguments in
                (call.args for call in self.hub.call_tool.call_args_list)]

    def test_accounts_list_only_the_bots_the_hub_still_lists(self):
        rows = telegram.accounts()
        self.assertEqual(self.tools(), [('channels.health', {'provider': 'Telegram'})])
        self.assertEqual([row['name'] for row in rows], ['Acme bot'])
        self.assertEqual(rows[0]['health']['webhook_status'], 'registered')
        self.assertNotIn('unexpected', rows[0]['health'])

    def test_the_hub_admin_lock_reaches_the_card(self):
        self.answers['channels.health'] = {'Telegram': [dict(HEALTH, enabled=False, admin_off=True)]}
        self.assertTrue(telegram.accounts()[0]['health']['admin_off'])
        self.answers['telegram.bot.settings'] = rejected('admin_off')
        with self.assertRaisesRegex(SetupError, 'Ask your Relay provider to turn it on'):
            telegram.save_settings('Acme bot', {'enabled': '1'})

    def test_a_hub_without_the_batch_tool_is_asked_once_per_bot(self):
        from relay_core.hub import OlderHubError
        self.answers['channels.health'] = OlderHubError('no such tool')
        self.assertEqual([row['name'] for row in telegram.accounts()], ['Acme bot'])
        self.assertEqual(self.tools()[1:], [('channels.list', {}), ('telegram.bot.health', {'channel': 'tg-1'})])

    def test_connect_sends_the_token_once_and_returns_no_credential(self):
        self.answers['telegram.bot.connect'] = dict(HEALTH, channel='tg-3')
        result = telegram.connect({'bot_token': ' ' + TOKEN + ' ', 'label': 'Acme Textiles'})
        self.assertEqual(self.tools(), [('telegram.bot.connect', {'bot_token': TOKEN, 'label': 'Acme Textiles'})])
        self.assertEqual(result['name'], 'New bot')
        self.assertNotIn(TOKEN, repr(result))
        self.assertNotIn(TOKEN, repr(self.site.tables))
        self.sync.assert_called_once()

    def test_connect_needs_a_token(self):
        for values in ({}, {'bot_token': '  '}, {'bot_token': 5}):
            with self.assertRaises(ValueError):
                telegram.connect(values)
        self.assertEqual(self.tools(), [])

    def test_hub_refusals_become_relay_text_without_the_token(self):
        for code, text in (('invalid_token', 'did not accept this bot token'), ('in_use', 'already connected'), ('rate_limited', 'Wait an hour'),
                           ('not_available', 'does not let sites connect')):
            self.answers['telegram.bot.connect'] = rejected(code, 'Hub words')
            with self.assertRaisesRegex(SetupError, text) as caught:
                telegram.connect({'bot_token': TOKEN})
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_a_token_is_never_sent_to_a_plain_http_hub(self):
        insecure = dict(SETTINGS, relay_hub_url='http://hub.example.com/mcp')
        with patch.object(channel_setup, 'connection_value', insecure.get):
            for call in (lambda: telegram.connect({'bot_token': TOKEN}), lambda: telegram.save_settings('Acme bot', {'bot_token': TOKEN})):
                with self.assertRaisesRegex(SetupError, 'only over HTTPS'):
                    call()
        self.assertEqual([tool for tool, _ in self.tools()], [])

    def test_settings_send_only_known_fields(self):
        telegram.save_settings('Acme bot', {'label': ' Acme Sales ', 'enabled': '0', 'bot_token': TOKEN})
        self.assertIn(('telegram.bot.settings', {'channel': 'tg-1', 'enabled': False, 'label': 'Acme Sales', 'bot_token': TOKEN}), self.tools())
        self.sync.assert_called_once()
        for wrong in ({}, {'username': 'x'}, {'bot_token': ''}, 'enabled'):
            with self.assertRaises(ValueError):
                telegram.save_settings('Acme bot', wrong)

    def test_check_default_and_remove_use_the_hub_key(self):
        self.answers['telegram.bot.check'] = dict(HEALTH, webhook_status='not_registered', webhook_missing='No HTTPS')
        result = telegram.check('Acme bot', True)
        self.assertEqual(result['health']['webhook_missing'], 'No HTTPS')
        self.assertIn(('telegram.bot.check', {'channel': 'tg-1', 'repair': True}), self.tools())
        with self.assertRaisesRegex(SetupError, 'Turn the channel on'):
            telegram.set_default('Sales bot')
        with self.assertRaisesRegex(SetupError, 'Confirm'):
            telegram.remove('Acme bot', False)
        self.answers['telegram.bot.remove'] = {'removed': True, 'webhook_deleted': True}
        self.assertEqual(telegram.remove('Acme bot', True), {'removed': True, 'webhook_deleted': True})
        self.assertTrue(self.site.rows('Relay Channel', {'name': 'Acme bot'}))

    def test_a_bot_of_another_site_or_provider_is_not_found(self):
        for name in ('Other bot', 'Sales line', 'Missing'):
            with self.assertRaisesRegex(SetupError, 'no longer connected'):
                telegram.check(name)
        self.assertEqual(self.tools(), [])


class TelegramApiTests(unittest.TestCase):
    def test_connect_is_for_a_system_manager_only(self):
        module = Mock()
        with patch.object(channels_api, 'system_manager', side_effect=PermissionError('Only a System Manager can set up Relay')), \
                patch.dict(channels_api.PROVIDERS, {'Telegram': module}), self.assertRaises(PermissionError):
            channels_api.connect('Telegram', {'bot_token': TOKEN})
        self.assertEqual(module.method_calls, [])

    def test_connect_goes_to_the_provider_and_whatsapp_is_refused(self):
        module = Mock()
        with patch.object(channels_api, 'system_manager'), patch.dict(channels_api.PROVIDERS, {'Telegram': module}):
            channels_api.connect('Telegram', '{"bot_token": "%s"}' % TOKEN)
        module.connect.assert_called_once_with({'bot_token': TOKEN})
        frappe = Mock(throw=Mock(side_effect=ValueError('setup page')), parse_json=lambda value: value)
        with patch.object(channels_api, 'system_manager'), patch.object(channels_api, 'frappe', frappe), self.assertRaises(ValueError):
            channels_api.connect('WhatsApp', {})


if __name__ == '__main__':
    unittest.main()
