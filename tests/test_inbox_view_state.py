"""Where a contact conversation opens: first unread message, with the saved channel and position kept as data."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
from relay_core import inbox


class ViewStateTests(unittest.TestCase):
    def state(self, views, message_contact='RELAY-CON-0000000001', unread='RELAY-MSG-0000000027'):
        fake = Mock()
        fake.session.user = 'local-reader@example.invalid'
        fake.db.get_value.return_value = json.dumps(views)
        fake.get_doc.side_effect = lambda doctype, name: SimpleNamespace(relay_contact=message_contact, channel='Local WhatsApp',
            check_permission=Mock())
        first = Mock(return_value=unread)
        with patch.object(inbox, 'frappe', fake), patch.object(inbox, 'require_access'), patch.object(inbox, 'readable_contact'), \
                patch.object(inbox, 'first_unread', first):
            return inbox.view_state('RELAY-CON-0000000001'), first

    def test_first_unread_is_returned_for_the_preferred_channel_beside_the_saved_position(self):
        result, first = self.state({'_active': '', 'combined': {'name': 'RELAY-MSG-0000000001', 'offset': 62.5, 'atBottom': False}})
        self.assertEqual(result, {'channel': '', 'first_unread': 'RELAY-MSG-0000000027',
            'name': 'RELAY-MSG-0000000001', 'offset': 62.5, 'atBottom': False})
        first.assert_called_once_with('RELAY-CON-0000000001', '')

    def test_a_read_conversation_without_a_saved_position_still_has_the_full_shape(self):
        result, _ = self.state({}, unread=None)
        self.assertEqual(result, {'channel': '', 'first_unread': None})

    def test_a_position_from_another_conversation_is_dropped(self):
        result, _ = self.state({'combined': {'name': 'RELAY-MSG-0000000001'}}, message_contact='RELAY-CON-0000000002')
        self.assertNotIn('name', result)

    def test_denied_contact_reads_nothing(self):
        first = Mock()
        with patch.object(inbox, 'require_access'), patch.object(inbox, 'readable_contact', side_effect=PermissionError), \
                patch.object(inbox, 'first_unread', first):
            with self.assertRaises(PermissionError): inbox.view_state('RELAY-CON-0000000001')
        first.assert_not_called()
