"""The composer's reply window: a chat on a disabled channel reads as closed; real denials stay denials."""
import unittest
from unittest.mock import patch

import frappe
from frappe import _dict
from relay_core import messaging

SOURCE = _dict(name='RELAY-MSG-0000000001', channel='Shop', relay_contact='C1', sender_endpoint='+91 9')
SHOP = _dict(name='Shop', channel='WhatsApp', account='site-a', enabled=1)


def raise_error(message, exc=frappe.ValidationError):
    raise exc(message)


class ReplyWindowTests(unittest.TestCase):
    def window(self, channel, readable=None):
        readable = readable or patch.object(messaging, 'readable_message', return_value=(SOURCE, channel))
        with readable, patch.object(messaging, 'connection_value', return_value='site-a'), \
                patch.object(messaging, 'require_binding') as binding, patch.object(messaging, 'context_of', return_value={}), \
                patch('relay_core.service_window.status', return_value={'open': True, 'remaining_seconds': 60}) as status:
            return messaging.reply_window(SOURCE.name), binding, status

    def test_a_disabled_or_moved_channel_reads_as_closed_without_a_permission_error(self):
        for channel in (_dict(SHOP, enabled=0), _dict(SHOP, account='site-b')):
            with self.subTest(channel=channel):
                result, binding, status = self.window(channel)
                self.assertEqual(result, {'open': False, 'channel_disabled': True})
                binding.assert_not_called()
                status.assert_not_called()

    def test_a_live_whatsapp_channel_checks_the_binding_and_the_window(self):
        result, binding, status = self.window(SHOP)
        self.assertEqual(result, {'open': True, 'remaining_seconds': 60})
        binding.assert_called_once_with(SOURCE)
        status.assert_called_once_with('C1', 'Shop', '+91 9')

    def test_a_chat_the_user_cannot_read_is_still_denied(self):
        denied = patch.object(messaging, 'readable_message', side_effect=frappe.PermissionError('No access'))
        with self.assertRaises(frappe.PermissionError):
            self.window(SHOP, denied)

    def test_sending_on_a_disabled_channel_is_still_denied(self):
        with patch.object(messaging, 'readable_message', return_value=(SOURCE, _dict(SHOP, enabled=0))), \
                patch.object(messaging, 'connection_value', return_value='site-a'), patch.object(messaging.frappe, 'throw', raise_error), \
                self.assertRaises(frappe.PermissionError):
            messaging.readable_source(SOURCE.name)


if __name__ == '__main__':
    unittest.main()
