"""Chat list read state: mark read moves the read positions forward; mark unread reopens only the newest incoming message."""
import unittest
from unittest.mock import Mock, patch

from frappe import _dict

from relay_core import conversation_state as state, message_reads

NEWEST = 'RELAY-MSG-0000000009'
INCOMING = 'RELAY-MSG-0000000008'
BEFORE = 'RELAY-MSG-0000000007'


def fake_site(current, newest):
    site = Mock()
    site.session.user = 'reader@example.invalid'
    site.db.get_value.return_value = _dict(current)
    site.get_list.side_effect = lambda doctype, filters, **kw: [newest(filters)] if newest(filters) else []
    return site


class SetChatReadTests(unittest.TestCase):
    def run_write(self, current, read, newest):
        site = fake_site(current, newest)
        with patch.object(message_reads, 'frappe', site), patch.object(state, 'ensure_state', return_value='STATE-1'), \
                patch.object(state, 'start_exact_reads') as exact, patch('relay_core.realtime.contact_changed') as changed:
            message_reads.set_chat_read('C1', read)
        return site, exact, changed

    def test_read_moves_both_positions_forward_without_read_rows(self):
        site, exact, changed = self.run_write({'last_read': BEFORE, 'read_baseline': BEFORE}, True, lambda f: NEWEST)
        exact.assert_called_once_with('C1')
        site.db.set_value.assert_called_once_with(state.STATE, 'STATE-1', {'last_read': NEWEST, 'read_baseline': NEWEST}, update_modified=False)
        site.db.delete.assert_not_called()
        changed.assert_called_once_with('C1', 'reads')

    def test_read_never_moves_a_position_back(self):
        site, _, _ = self.run_write({'last_read': NEWEST, 'read_baseline': BEFORE}, True, lambda f: NEWEST)
        site.db.set_value.assert_called_once_with(state.STATE, 'STATE-1', {'read_baseline': NEWEST}, update_modified=False)

    def test_unread_reopens_the_newest_incoming_message_only(self):
        def newest(filters):
            return BEFORE if filters.get('name') else INCOMING
        site, _, changed = self.run_write({'last_read': NEWEST, 'read_baseline': NEWEST}, False, newest)
        self.assertEqual(site.get_list.call_args_list[0].kwargs['filters']['direction'], 'Incoming')
        site.db.delete.assert_called_once_with('Relay Message Read', {'user': 'reader@example.invalid', 'message': INCOMING})
        site.db.set_value.assert_called_once_with(state.STATE, 'STATE-1', {'read_baseline': BEFORE}, update_modified=False)
        changed.assert_called_once_with('C1', 'reads')

    def test_unread_keeps_a_baseline_that_is_already_before_the_message(self):
        site, _, _ = self.run_write({'last_read': None, 'read_baseline': BEFORE}, False, lambda f: INCOMING)
        site.db.delete.assert_called_once()
        site.db.set_value.assert_not_called()

    def test_a_chat_without_messages_is_left_alone(self):
        site, exact, changed = self.run_write({}, False, lambda f: None)
        exact.assert_not_called()
        site.db.set_value.assert_not_called()
        changed.assert_not_called()


class MarkChatTests(unittest.TestCase):
    def call(self, read):
        site = Mock()
        site.throw.side_effect = ValueError
        site.db.get_value.return_value = 1
        with patch.object(message_reads, 'frappe', site), patch.object(message_reads, 'require_access'), \
                patch.object(message_reads, 'readable_contact') as readable, \
                patch.object(state, 'fresh_write', side_effect=lambda write: write()), \
                patch.object(message_reads, 'set_chat_read') as write, \
                patch('relay_core.relay_chats.mark_read') as read_chat, patch('relay_core.relay_chats.mark_unread') as unread_chat, \
                patch('relay_core.business_access.primary', return_value=None):
            self.chats = read_chat, unread_chat
            return message_reads.mark_chat('C1', read), readable, write, site

    def test_the_contact_is_checked_and_the_shared_unread_count_returned(self):
        result, readable, write, site = self.call('0')
        readable.assert_called_once_with('C1')
        write.assert_called_once_with('C1', False)
        self.chats[1].assert_called_once_with(('Relay Contact', 'C1'))
        self.chats[0].assert_not_called()
        self.assertEqual(site.db.get_value.call_args.args[:2], ('Relay Chat', {'business_doctype': 'Relay Contact', 'business_name': 'C1'}))
        self.assertEqual(result, {'contact': 'C1', 'unread': 1})

    def test_read_clears_the_chat_row(self):
        self.call('1')
        self.chats[0].assert_called_once_with(('Relay Contact', 'C1'))
        self.chats[1].assert_not_called()

    def test_a_bad_flag_is_rejected_before_any_write(self):
        with self.assertRaises(ValueError):
            self.call('yes')


if __name__ == '__main__':
    unittest.main()


class ReceiptTimeTests(unittest.TestCase):
    def test_provider_receipt_times_are_given_in_the_site_time_zone(self):
        doc = _dict(message_updates='{"delivery": {"timestamp": 1761600000, "times": {"Sent": 1761600000, "Read": 1761600600}}}')
        with patch('frappe.utils.data.get_system_timezone', return_value='Asia/Kolkata'):
            self.assertEqual(message_reads.receipt_times(doc), {'Sent': '2025-10-28 02:50:00', 'Read': '2025-10-28 03:00:00'})
        self.assertEqual(message_reads.receipt_times(_dict(message_updates=None)), {})
        self.assertEqual(message_reads.receipt_times(_dict(message_updates='{"delivery": {"timestamp": 5}}')), {})
