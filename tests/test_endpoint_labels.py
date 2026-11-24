"""A Telegram chat shows the person's linked mobile number, never the numeric Telegram chat id."""
import unittest
from unittest.mock import MagicMock, patch

from frappe import _dict
from relay_core.endpoint_labels import contact_titles, telegram_labels


class TelegramLabelTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def get_all(self, doctype, filters=None, **kwargs):
        self.calls.append(doctype)
        if doctype == 'Relay Channel':
            return ['WA-1']
        if doctype == 'Relay Contact':
            return [_dict(name='R1', contact='', display_name='Ravi'), _dict(name='R2', contact='CON-2', display_name='5501'),
                    _dict(name='R3', contact='', display_name='Meena'), _dict(name='R4', contact='', display_name='550044')]
        if doctype == 'Contact':
            return [_dict(name='CON-2', mobile_no='+91 98765 43210', phone='')]
        if filters.get('channel') == ['in', ['WA-1']]:
            return [_dict(relay_contact='R1', endpoint='919000001234')]
        return [_dict(channel='TG', endpoint='5501', relay_contact='R1'), _dict(channel='TG', endpoint='5502', relay_contact='R2'),
                _dict(channel='TG', endpoint='5503', relay_contact='R3'), _dict(channel='TG', endpoint='5504', relay_contact='R4'),
                _dict(channel='OTHER', endpoint='5501', relay_contact='R9')]

    def test_the_linked_mobile_comes_first_then_the_username_then_the_name(self):
        pairs = [('TG', '5501'), ('TG', '5502'), ('TG', '5503'), ('TG', '5504'), ('TG', '5505')]
        with patch('frappe.get_all', side_effect=self.get_all):
            labels = telegram_labels(pairs, {('TG', '5503'): '@meena', ('TG', '5501'): '@ravi'})
        self.assertEqual(labels, {
            ('TG', '5501'): '+919000001234',       # the person's WhatsApp number on the same Relay Contact
            ('TG', '5502'): '+91 98765 43210',     # else the mobile of the linked Frappe Contact
            ('TG', '5503'): '@meena',              # else the Telegram username
            ('TG', '5504'): 'Telegram',            # a name that is only a number is not shown
            ('TG', '5505'): 'Telegram',            # an unknown chat
        })
        for label in labels.values():
            self.assertNotIn(label, ('5501', '5502', '5503', '5504', '5505'), 'A raw chat id is never a label')
        self.assertEqual(self.calls, ['Relay Contact Endpoint', 'Relay Contact', 'Relay Channel', 'Relay Contact Endpoint', 'Contact'],
                         'Every chat is labelled in the same few batched reads')

    def test_a_saved_name_shows_when_there_is_no_number_or_username(self):
        with patch('frappe.get_all', side_effect=self.get_all):
            self.assertEqual(telegram_labels([('TG', '5503')]), {('TG', '5503'): 'Meena'})

    def test_a_contact_saved_under_its_chat_id_is_titled_by_mobile_then_username_then_telegram_user(self):
        def get_all(doctype, filters=None, **kwargs):
            if doctype == 'Relay Channel':
                return ['TG'] if filters == {'channel': 'Telegram'} else ['WA-1']
            if doctype == 'Relay Contact':
                return [_dict(name=name, contact='', display_name='') for name in filters['name'][1]]
            if filters.get('channel') == ['in', ['WA-1']]:
                return [_dict(relay_contact='R1', endpoint='919000001234')]
            return [_dict(relay_contact='R1', channel='TG', endpoint='5501'), _dict(relay_contact='R2', channel='TG', endpoint='5502'),
                    _dict(relay_contact='R3', channel='TG', endpoint='5503'), _dict(relay_contact='R5', channel='TG', endpoint='5505')]
        usernames = {'R2': '{"username": "meena"}', 'R3': None}
        names = {'R1': '5501', 'R2': '5502', 'R3': '5503', 'R4': '+91 98765 43210', 'R5': '7777', 'R6': 'Ravi'}
        fake = MagicMock()
        fake.get_all.side_effect = get_all
        fake.db.get_value.side_effect = lambda doctype, filters, *args, **kwargs: usernames[filters['relay_contact']]
        with patch('relay_core.endpoint_labels.frappe', fake):
            titles = contact_titles(names)
        self.assertEqual(titles, {'R1': '+919000001234', 'R2': '@meena', 'R3': 'Telegram user'},
                         'A WhatsApp-only number (R4), a number that is not its chat id (R5) and a real name (R6) keep their names')

    def test_contacts_with_names_read_nothing(self):
        with patch('frappe.get_all') as get_all:
            self.assertEqual(contact_titles({'R1': 'Ravi', 'R2': 'Meena'}), {})
        get_all.assert_not_called()

    def test_no_telegram_chats_read_nothing(self):
        with patch('frappe.get_all') as get_all:
            self.assertEqual(telegram_labels([('TG', ''), ('', '5501')]), {})
        get_all.assert_not_called()
