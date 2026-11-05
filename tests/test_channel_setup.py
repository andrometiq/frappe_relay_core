"""WhatsApp numbers are set up from Relay through the Hub's site tools; no credential crosses to Core."""
import unittest
from unittest.mock import Mock, patch

from channel_fakes import FakeSite
from relay_core import channel_setup, channels_api
from relay_core.channel_setup import SetupError, whatsapp
from relay_core.hub import HubError

SETTINGS = {'relay_hub_account': 'site-a', 'relay_hub_url': 'http://127.0.0.1/mcp', 'relay_hub_token': 't'}
HEALTH = {'channel': 'wa-120', 'connection_status': 'connected', 'partner_status': 'active', 'verified_at': '2026-11-01T10:00:00Z',
          'checked_at': '', 'check_error': '', 'webhook_subscribed': True, 'pin_kept': True,
          'settings': {'templates': True, 'sync_metadata': True}, 'delivery': {'callback_pending': 0}, 'unexpected': 'dropped'}


def rejected(code, message='Hub refused'):
    return HubError('Hub operation was rejected', None, f'{code}: {message} · code {code}')


class ChannelSetupTests(unittest.TestCase):
    def setUp(self):
        self.site = FakeSite(Relay_Channel=[
            {'name': 'Sales line', 'channel': 'WhatsApp', 'account': 'site-a', 'hub_channel': 'wa-120', 'label': 'Sales line',
             'address': '+91 99999 99120', 'enabled': 1, 'is_default': 1},
            {'name': 'Support line', 'channel': 'WhatsApp', 'account': 'site-a', 'hub_channel': 'wa-121', 'label': 'Support line',
             'enabled': 1, 'is_default': 0},
            {'name': 'Old line', 'channel': 'WhatsApp', 'account': 'site-a', 'hub_channel': 'wa-99', 'enabled': 0},
            {'name': 'Other site', 'channel': 'WhatsApp', 'account': 'site-b', 'hub_channel': 'wa-130', 'enabled': 1}])
        self.hub = Mock()
        self.answers = {'channels.list': {'channels': [{'key': 'wa-120', 'provider': 'WhatsApp'}, {'key': 'wa-121', 'provider': 'WhatsApp'},
                                                       {'key': 'wa-130', 'provider': 'WhatsApp'}]},
                        'whatsapp.number.health': HEALTH}
        self.hub.call_tool.side_effect = self.answer
        self.sync, self.publish = Mock(), Mock()
        for item in (patch.object(channel_setup, 'frappe', self.site.frappe), patch.object(whatsapp, 'frappe', self.site.frappe),
                     patch.object(channel_setup, 'connection_value', SETTINGS.get), patch.object(whatsapp, 'connection_value', SETTINGS.get),
                     patch.object(whatsapp, 'publish', self.publish), patch('relay_core.channel_sync.sync', self.sync),
                     patch('relay_core.whatsapp.client', return_value=self.hub), patch('relay_core.whatsapp.clear_hub_capabilities')):
            item.start()
            self.addCleanup(item.stop)

    def answer(self, tool, arguments):
        result = self.answers.get(tool, {})
        if isinstance(result, Exception):
            raise result
        return result

    def tools(self):
        return [call.args for call in self.hub.call_tool.call_args_list]

    def test_accounts_list_only_the_numbers_the_hub_still_lists_for_this_site(self):
        rows = whatsapp.accounts()
        self.assertEqual([row['name'] for row in rows], ['Sales line', 'Support line'])
        self.assertTrue(rows[0]['is_default'])
        self.assertNotIn('unexpected', rows[0]['health'])
        self.assertEqual(rows[0]['health']['connection_status'], 'connected')
        self.assertIn(('whatsapp.number.health', {'channel': 'wa-121'}), self.tools())

    def test_a_number_of_another_site_or_unknown_is_not_found(self):
        for name in ('Other site', 'Missing', None):
            with self.assertRaisesRegex(SetupError, 'no longer connected'):
                whatsapp.check(name)
        self.assertEqual(self.tools(), [])

    def test_check_names_the_hub_key_and_asks_to_repair(self):
        self.answers['whatsapp.number.check'] = dict(HEALTH, connection_status='reconnect_required', reconnect_required=True,
                                                     profile={'verified_name': 'Acme Textiles'})
        result = whatsapp.check('Support line')
        self.assertEqual(self.tools()[-1], ('whatsapp.number.check', {'channel': 'wa-121', 'repair': True}))
        self.assertTrue(result['reconnect_required'])
        self.assertEqual(result['profile'], {'verified_name': 'Acme Textiles'})
        self.publish.assert_called_once()

    def test_settings_send_only_known_switches_and_resync(self):
        whatsapp.save_settings('Support line', {'enabled': '0', 'templates': True})
        self.assertIn(('whatsapp.number.settings', {'channel': 'wa-121', 'enabled': False, 'templates': True}), self.tools())
        self.sync.assert_called_once()
        for wrong in ({}, {'groups': True}, 'enabled'):
            with self.assertRaises(ValueError):
                whatsapp.save_settings('Support line', wrong)

    def test_default_number_moves_to_the_chosen_enabled_number(self):
        whatsapp.set_default('Support line')
        self.assertEqual(self.site.rows('Relay Channel', {'name': 'Support line'})[0].is_default, 1)
        self.publish.assert_called_once()
        with self.assertRaisesRegex(SetupError, 'Turn the number on'):
            whatsapp.set_default('Old line')

    def test_remove_needs_confirm_and_keeps_the_relay_channel(self):
        with self.assertRaisesRegex(SetupError, 'Confirm'):
            whatsapp.remove('Support line', False)
        self.answers['whatsapp.number.remove'] = {'removed': True, 'deregistered': True, 'unsubscribed': False}
        self.assertEqual(whatsapp.remove('Support line', True), {'removed': True, 'deregistered': True, 'unsubscribed': False})
        self.assertIn(('whatsapp.number.remove', {'channel': 'wa-121', 'confirm': True}), self.tools())
        self.sync.assert_called_once()
        self.assertTrue(self.site.rows('Relay Channel', {'name': 'Support line'}))

    def test_hub_codes_become_relay_text_and_meta_words_pass_through(self):
        self.answers['whatsapp.number.pin_reset'] = rejected('reconnect_required')
        with self.assertRaisesRegex(SetupError, 'Connect again'):
            whatsapp.reset_pin('Sales line')
        self.answers['whatsapp.number.pin_reset'] = rejected('meta_rejected', 'Meta did not take the new PIN. Meta says: Invalid PIN')
        with self.assertRaisesRegex(SetupError, 'Meta says: Invalid PIN'):
            whatsapp.reset_pin('Sales line')
        self.answers['whatsapp.number.pin_reset'] = HubError('Unsupported Hub tool')
        with self.assertRaisesRegex(SetupError, 'Try again in a few minutes'):
            whatsapp.reset_pin('Sales line')

    def test_profile_fields_and_photo_are_checked_before_the_hub(self):
        with self.assertRaises(ValueError):
            whatsapp.save_profile('Sales line', {'phone': '919999999999'})
        with self.assertRaises(ValueError):
            whatsapp.save_profile('Sales line', {'websites': 'https://example.com'})
        with self.assertRaises(ValueError):
            whatsapp.save_profile('Sales line', {}, 'aGVsbG8=', 'application/pdf')
        self.assertEqual(self.tools(), [])
        self.answers['whatsapp.execute'] = {'profile': {'about': 'Fabrics for every season', 'id': 'dropped'}}
        result = whatsapp.save_profile('Sales line', {'about': 'Fabrics for every season'}, 'aGVsbG8=', 'image/png')
        self.assertEqual(self.tools()[0], ('whatsapp.execute', {'operation': 'profile.update', 'channel': 'wa-120',
                                                               'profile': {'about': 'Fabrics for every season'},
                                                               'content_base64': 'aGVsbG8=', 'mime_type': 'image/png'}))
        self.assertEqual(result['about'], 'Fabrics for every season')
        self.assertNotIn('id', result)

    def test_a_site_without_a_hub_link_is_told_to_connect(self):
        with patch.object(channel_setup, 'connection_value', {}.get), self.assertRaisesRegex(SetupError, 'Connect this site'):
            channel_setup.hub_call('channels.list', {})


class ChannelsApiPermissionTests(unittest.TestCase):
    def test_only_a_system_manager_configures(self):
        for endpoint, arguments in ((channels_api.check_number, ('Sales line',)), (channels_api.save_number_settings, ('Sales line', '{"enabled": 1}')),
                                    (channels_api.set_default, ('Sales line',)), (channels_api.reset_pin, ('Sales line',)),
                                    (channels_api.remove_number, ('Sales line', 1)), (channels_api.save_number_profile, ('Sales line', '{}'))):
            with patch.object(channels_api, 'system_manager', side_effect=PermissionError('Only a System Manager can set up Relay')), \
                    patch.object(channels_api, 'whatsapp') as provider, self.assertRaises(PermissionError):
                endpoint(*arguments)
            self.assertEqual(provider.method_calls, [])

    def test_readers_need_configure_or_manage_rights(self):
        frappe = Mock(PermissionError=PermissionError, throw=Mock(side_effect=PermissionError('Not permitted')))
        with patch.object(channels_api, 'frappe', frappe), patch.object(channels_api, 'require_access'), \
                patch.object(channels_api, 'can_configure', return_value=False), patch.object(channels_api, 'can_manage', return_value=False), \
                patch.object(channels_api, 'whatsapp') as provider, self.assertRaises(PermissionError):
            channels_api.accounts()
        self.assertEqual(provider.method_calls, [])

    def test_a_provider_without_setup_is_refused(self):
        frappe = Mock(throw=Mock(side_effect=ValueError('not yet')))
        with patch.object(channels_api, 'frappe', frappe), patch.object(channels_api, 'readers'), self.assertRaises(ValueError):
            channels_api.accounts('Email')
