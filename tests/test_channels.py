"""Channel registry and feature contract; the Hub boundary is stubbed."""
import sys
import types
import unittest
from unittest.mock import Mock, patch

from relay_core.channels import CHANNELS, channel, enabled
from relay_core.channels.contract import FEATURES, Channel
from relay_core.hub import HubError
from site_file_limit import use_relay_file_limit


def setUpModule():
    use_relay_file_limit()


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
        with patch.dict(sys.modules, {'relay_core.settings': settings}), patch('relay_core.channels.linked', return_value=set()):
            self.assertEqual([item.name for item in enabled()], ['WhatsApp', 'Email'])

    def test_a_linked_bot_or_mailbox_switches_its_channel_on(self):
        settings = types.SimpleNamespace(ENABLED_CHANNELS=('WhatsApp',))
        for linked, expected in ((set(), ['WhatsApp']), ({'Email'}, ['WhatsApp', 'Email']),
                                 ({'Telegram', 'Email'}, ['WhatsApp', 'Telegram', 'Email'])):
            with self.subTest(linked=linked), patch.dict(sys.modules, {'relay_core.settings': settings}), \
                    patch('relay_core.channels.linked', return_value=linked):
                self.assertEqual([item.name for item in enabled()], expected)

    def test_linked_reads_enabled_channels_of_the_site_account(self):
        settings = types.SimpleNamespace(value=Mock(return_value='acme'))
        frappe = types.SimpleNamespace(get_all=Mock(return_value=['Telegram']))
        with patch.dict(sys.modules, {'relay_core.settings': settings, 'frappe': frappe}):
            from relay_core.channels import linked
            self.assertEqual(linked(), {'Telegram'})
        filters = frappe.get_all.call_args.kwargs['filters']
        self.assertEqual((filters['enabled'], filters['account']), (1, 'acme'))

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


class WhatsAppSendFormatTests(unittest.TestCase):
    def prepare(self, kind, file_name, raw=b'bytes'):
        from frappe import _dict
        from relay_core import messaging
        source = _dict(name='source', sender_endpoint='919800000001', provider_id='wamid.1')
        file = _dict(name='file', file_name=file_name)
        with patch('relay_core.attachments.file_content', return_value=(file, raw)):
            return messaging._prepare(source, _dict(channel='WhatsApp'), {'provider': 'WhatsApp'}, kind, {'attachment': 'file'})

    def test_send_accepts_only_the_declared_media_types(self):
        tool, args, _content = self.prepare('voice', 'note.ogg')
        self.assertEqual((tool, args['media_type'], args['mime_type']), ('whatsapp.execute', 'audio', 'audio/ogg'))
        self.assertEqual(self.prepare('document', 'invoice.pdf')[1]['filename'], 'invoice.pdf')
        for kind, file_name in (('photo', 'sticker.webp'), ('document', 'archive.zip')):
            with self.assertRaisesRegex(ValueError, 'supported WhatsApp attachment format'):
                self.prepare(kind, file_name)

    def test_send_applies_the_lower_whatsapp_limit_of_the_kind(self):
        photo = channel('WhatsApp').features['max_media_bytes']['photo']
        with patch('relay_core.file_limits.get_max_bytes', return_value=photo + 10):
            self.prepare('photo', 'offer.png', b'x' * photo)
            with self.assertRaisesRegex(ValueError, 'A WhatsApp photo must be at most 5 MB'):
                self.prepare('photo', 'offer.png', b'x' * (photo + 1))
            self.prepare('document', 'invoice.pdf', b'x' * (photo + 10))


if __name__ == '__main__':
    unittest.main()
