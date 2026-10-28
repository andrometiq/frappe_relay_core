"""Business contact chips and counts match the chats the record timeline shows."""
from unittest.mock import Mock, patch
import unittest
from relay_core import business_inbox


def fake_frappe(linked, contact_readable, chat_readable):
    fake = Mock()
    fake.get_all.side_effect = lambda doctype, **kwargs: (
        list(linked) if 'pluck' in kwargs else
        [{'name': name} for name in kwargs['filters']['name'][1]])
    fake.get_list.side_effect = lambda doctype, **kwargs: list(
        chat_readable if doctype == 'Relay Contact' else contact_readable)
    return fake


class BusinessContactTests(unittest.TestCase):
    def test_contact_behind_readable_chat_is_listed_without_contact_permission(self):
        fake = fake_frappe(['chat 1', 'chat 2', 'hidden'], [], ['chat 2', 'chat 1'])
        with patch.object(business_inbox, 'frappe', fake):
            rows = business_inbox._linked_contacts('Supplier', 'local')
        self.assertEqual([row['name'] for row in rows], ['chat 1', 'chat 2'])
        relay_call = next(call for call in fake.get_list.call_args_list if call.args[0] == 'Relay Contact')
        self.assertEqual(relay_call.kwargs['filters'], {'contact': ['in', ['chat 1', 'chat 2', 'hidden']]})

    def test_readable_contact_without_chat_stays_listed(self):
        fake = fake_frappe(['owned'], ['owned'], [])
        with patch.object(business_inbox, 'frappe', fake):
            self.assertEqual([row['name'] for row in business_inbox._linked_contacts('Supplier', 'local')], ['owned'])

    def test_record_without_visible_contacts_returns_nothing(self):
        fake = fake_frappe(['hidden'], [], [])
        with patch.object(business_inbox, 'frappe', fake):
            self.assertEqual(business_inbox._linked_contacts('Supplier', 'local'), [])
        self.assertEqual(fake.get_all.call_count, 1)

    def test_invalid_search_is_rejected_before_any_query(self):
        fake = fake_frappe([], [], []); fake.throw.side_effect = ValueError
        with patch.object(business_inbox, 'frappe', fake), self.assertRaises(ValueError):
            business_inbox._linked_contacts('Supplier', 'local', query='x' * 81)
        fake.get_all.assert_not_called()


if __name__ == '__main__':
    unittest.main()
