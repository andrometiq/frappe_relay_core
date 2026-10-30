"""Business contact chips and counts match the chats the record timeline shows."""
from unittest.mock import Mock, patch
import unittest
from relay_core import business_inbox


def fake_frappe(linked, contact_readable, chat_readable):
    fake = Mock()
    fake.get_all.side_effect = lambda doctype, **kwargs: [{'name': name} for name in sorted(linked)[:kwargs['page_length']]]
    fake.get_list.side_effect = lambda doctype, **kwargs: list(
        chat_readable if doctype == 'Relay Contact' else contact_readable)
    return fake


class BusinessContactTests(unittest.TestCase):
    def test_contact_behind_readable_chat_is_listed_without_contact_permission(self):
        fake = fake_frappe(['chat 1', 'chat 2', 'hidden'], [], ['chat 2', 'chat 1'])
        with patch.object(business_inbox, 'frappe', fake):
            rows = business_inbox._linked_contacts('Supplier', 'local')
        self.assertEqual([row['name'] for row in rows], ['chat 1', 'chat 2', 'hidden'])
        fake.get_list.assert_not_called()

    def test_readable_contact_without_chat_stays_listed(self):
        fake = fake_frappe(['owned'], ['owned'], [])
        with patch.object(business_inbox, 'frappe', fake):
            self.assertEqual([row['name'] for row in business_inbox._linked_contacts('Supplier', 'local')], ['owned'])

    def test_record_without_visible_contacts_returns_nothing(self):
        fake = fake_frappe([], [], [])
        with patch.object(business_inbox, 'frappe', fake):
            self.assertEqual(business_inbox._linked_contacts('Supplier', 'local'), [])
        self.assertEqual(fake.get_all.call_count, 1)

    def test_invalid_search_is_rejected_before_any_query(self):
        fake = fake_frappe([], [], []); fake.throw.side_effect = ValueError
        with patch.object(business_inbox, 'frappe', fake), self.assertRaises(ValueError):
            business_inbox._linked_contacts('Supplier', 'local', query='x' * 81)
        fake.get_all.assert_not_called()

    def test_contact_whose_number_another_contact_owns_is_flagged(self):
        from relay_core import conversation_start
        rows = [Mock(full_name=name, mobile_no=phone, phone=None, email_id='x@y.z') for name, phone in
                (('Shared', '7790844803'), ('Own', '9150031035'), ('No number', ''))]
        for row in rows:
            row.name = row.full_name
        held = Mock(return_value={'Shared'})
        with patch.object(business_inbox, 'check_type'), patch.object(business_inbox, 'business_document'), \
                patch.object(business_inbox, '_linked_contacts', return_value=rows), \
                patch('relay_core.contacts.contact_emails', return_value={}), \
                patch('relay_core.identity.phone_number', side_effect=lambda value: '91' + value), \
                patch.object(conversation_start, 'numbers_held_elsewhere', held):
            items = business_inbox.contacts('Customer', 'AURA')['items']
        self.assertEqual([item['number_elsewhere'] for item in items], [True, False, False])
        held.assert_called_once_with({'Shared': {'917790844803'}, 'Own': {'919150031035'}})


if __name__ == '__main__':
    unittest.main()
