"""Conversation threads: one per contact endpoint on one business channel, with the shared unread split per thread."""
import datetime
import unittest
from unittest.mock import patch

from frappe import _dict
from relay_core import conversation_threads
from test_contact_primary import fake_frappe

AT = datetime.datetime(2026, 11, 20, 10, 0)


def last(name, channel, direction='Incoming'):
    return _dict(name=name, channel=channel, direction=direction, sent_at=AT, creation=AT, content='Hello ' + name,
                 message_data='{}', relay_contact='R1')


class ConversationThreadTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_frappe()
        self.fake.get_list.return_value = [
            _dict(name='CH-MAIL', channel='Email', label='Sales mail', title='', address='sales@example.invalid'),
            _dict(name='CH-WA2', channel='WhatsApp', label='Support', title='', address='+91 70000 00002'),
            _dict(name='CH-WA1', channel='WhatsApp', label='Sales', title='', address='+91 70000 00001')]
        self.fake.get_all.return_value = [last('M3', 'CH-MAIL'), last('M5', 'CH-WA1', 'Outgoing'), last('M7', 'CH-WA2'), last('M8', 'CH-HIDDEN')]
        self.enterContext(patch.object(conversation_threads, 'frappe', self.fake))
        self.enterContext(patch('relay_core.inbox.directory_preview', side_effect=lambda row: row.content))
        self.people = self.enterContext(patch.object(conversation_threads, 'readable_person', side_effect=lambda contact:
            None if contact == 'R-HIDDEN' else {'label': 'Ravi', 'frappe_contact': 'CONTACT-1'}))

    def test_each_endpoint_on_each_channel_is_its_own_thread_with_its_unread(self):
        newest = {('R1', 'CH-WA2', '911'): 'M7', ('R1', 'CH-MAIL', 'ravi@example.invalid'): 'M3', ('R1', 'CH-WA1', '911'): 'M5',
                  ('R1', 'CH-HIDDEN', '911'): 'M8', ('R-HIDDEN', 'CH-WA1', '922'): 'M5'}
        items = conversation_threads.thread_items(newest, {('R1', 'CH-WA2', '911'): (2, 'M6', 'M7')})
        self.assertEqual([(item['channel'], item['endpoint']) for item in items],
                         [('CH-WA1', '911'), ('CH-WA2', '911'), ('CH-MAIL', 'ravi@example.invalid')],
                         'WhatsApp, then Telegram, then Email; hidden channels and unreadable people are left out')
        support = items[1]
        self.assertEqual({key: support[key] for key in ('key', 'provider', 'channel_label', 'channel_address', 'unread', 'first_unread',
                                                         'last_message', 'last_direction', 'preview', 'contact_label', 'frappe_contact')},
                         {'key': 'R1|CH-WA2|911', 'provider': 'WhatsApp', 'channel_label': 'Support', 'channel_address': '+91 70000 00002',
                          'unread': 2, 'first_unread': 'M6', 'last_message': 'M7', 'last_direction': 'Incoming', 'preview': 'Hello M7',
                          'contact_label': 'Ravi', 'frappe_contact': 'CONTACT-1'})
        self.assertEqual((items[0]['unread'], items[0]['first_unread']), (0, None), 'The same endpoint on another number is another thread')

    def test_a_request_names_one_chat_or_one_record(self):
        with patch.object(conversation_threads, 'require_access'):
            for values in ({}, {'contact': 'RELAY-CON-1', 'doctype': 'Customer', 'name': 'C1'}):
                with self.subTest(values=values), self.assertRaises(ValueError):
                    conversation_threads.threads(**values)


class ReadablePersonTests(unittest.TestCase):
    def test_a_person_the_user_cannot_read_has_no_threads(self):
        fake = fake_frappe()
        with patch.object(conversation_threads, 'frappe', fake), patch.object(conversation_threads, 'readable_contact', side_effect=PermissionError):
            self.assertIsNone(conversation_threads.readable_person('R1'))
        with patch.object(conversation_threads, 'frappe', fake), patch.object(conversation_threads, 'readable_contact', return_value=(
                _dict(name='R1', display_name='', contact='CONTACT-1'), _dict(full_name='Ravi Kumar'))):
            self.assertEqual(conversation_threads.readable_person('R1'), {'label': 'Ravi Kumar', 'frappe_contact': 'CONTACT-1'})


if __name__ == '__main__':
    unittest.main()
