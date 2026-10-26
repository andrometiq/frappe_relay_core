"""Channel registry and feature contract; the Hub boundary is stubbed."""
import sys
import types
import unittest
from unittest.mock import Mock, patch

from relay_core.channels import CHANNELS, channel, enabled
from relay_core.channels.contract import FEATURES, Channel
from relay_core.hub import HubError


class ChannelRegistryTests(unittest.TestCase):
    def test_every_channel_declares_the_whole_contract(self):
        self.assertEqual(set(CHANNELS), {'WhatsApp', 'Telegram', 'Email'})
        for item in CHANNELS.values():
            self.assertEqual(set(item.features), set(FEATURES), item.name)

    def test_contract_rejects_a_partial_feature_list(self):
        with self.assertRaises(TypeError):
            type('Partial', (Channel,), {'name': 'Partial', 'features': {'text': True}})

    def test_unknown_channel_and_feature_fail_loudly(self):
        with self.assertRaises(ValueError):
            channel('SMS')
        with self.assertRaises(ValueError):
            channel('Email').supports('teleport')

    def test_enabled_follows_the_site_switch(self):
        settings = types.SimpleNamespace(ENABLED_CHANNELS=('WhatsApp', 'Email'))
        with patch.dict(sys.modules, {'relay_core.settings': settings}):
            self.assertEqual([item.name for item in enabled()], ['WhatsApp', 'Email'])

    def test_whatsapp_supports_its_message_types(self):
        whatsapp = channel('WhatsApp')
        for feature in ('text', 'media', 'location', 'contacts', 'reply_quote', 'reactions', 'bulk_campaigns', 'voice_calls'):
            self.assertTrue(whatsapp.supports(feature, {}), feature)
        self.assertEqual(whatsapp.features['reply_window_hours'], 24)
        self.assertIn('application/pdf', whatsapp.features['media']['document'])
        self.assertFalse(channel('Email').supports('reactions'))
        self.assertTrue(channel('Telegram').supports('topics'))


class AccountFlagTests(unittest.TestCase):
    def setUp(self):
        self.whatsapp = channel('WhatsApp')

    def test_templates_and_forms_need_the_hub_account_flag(self):
        features = self.whatsapp.get_features({'templates': True, 'flows': False})
        self.assertTrue(features['templates'])
        self.assertFalse(features['forms'])
        self.assertTrue(self.whatsapp.supports('forms', {'flows': True}))

    def test_flags_are_read_from_the_hub_when_not_given(self):
        module = types.SimpleNamespace(checked_client=Mock(return_value=(Mock(), {'templates': True, 'flows': True})))
        with patch.dict(sys.modules, {'relay_core.whatsapp': module}):
            features = self.whatsapp.get_features()
        self.assertTrue(features['templates'] and features['forms'])

    def test_unreachable_hub_switches_account_features_off(self):
        module = types.SimpleNamespace(checked_client=Mock(side_effect=HubError('down')))
        with patch.dict(sys.modules, {'relay_core.whatsapp': module}):
            features = self.whatsapp.get_features()
        self.assertFalse(features['templates'] or features['forms'])
        self.assertTrue(features['text'])

    def test_channels_without_account_flags_never_call_the_hub(self):
        self.assertEqual(channel('Telegram').get_features(), channel('Telegram').features)


if __name__ == '__main__':
    unittest.main()
