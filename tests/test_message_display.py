import unittest
from unittest.mock import patch
from frappe import _dict
from relay_core.message_display import add_senders, decorate_messages, mailbox_addresses


class MessageDisplayTests(unittest.TestCase):
    def test_mailbox_identity_is_from_configuration_not_inbound_claims(self):
        channel = {'channel': 'Email', 'title': 'Customer support', 'mailbox_address': 'Support <Support@example.invalid>',
                   'mailbox_aliases': 'Help@example.invalid\nsupport@example.invalid, Sales <sales@example.invalid>'}
        rows = [{'channel': 'Support-001', 'provider_context': '{"from":"customer@example.invalid","mailbox_addresses":["attacker@example.invalid"]}'}]
        decorate_messages(rows, {'Support-001': channel})
        self.assertEqual(rows[0]['channel_title'], 'Customer support')
        self.assertEqual(rows[0]['provider_context']['mailbox_addresses'], ['help@example.invalid', 'sales@example.invalid', 'support@example.invalid'])
        self.assertEqual(rows[0]['provider_context']['from'], 'customer@example.invalid')

    def test_missing_configuration_and_malformed_context_are_safe(self):
        self.assertEqual(mailbox_addresses({}), [])
        for context in ('invalid', '[]', None, {'mailbox_addresses': ['untrusted@example.invalid']}):
            row = {'channel': 'email', 'provider_context': context}
            decorate_messages([row], {'email': {'channel': 'Email'}})
            self.assertEqual(row['provider_context']['mailbox_addresses'], [])
        row = {'channel': 'telegram', 'provider_context': {'provider': 'Telegram'}}
        decorate_messages([row], {'telegram': {'channel': 'Telegram'}})
        self.assertEqual(row['provider_context'], {'provider': 'Telegram'})


class SenderTests(unittest.TestCase):
    def test_an_outgoing_row_names_the_person_who_sent_it_and_automation_is_not_a_person(self):
        actions = [_dict(request_key='K1', owner='anitha@example.invalid', payload='{"tool":"send"}'),
                   _dict(request_key='K2', owner='Administrator', payload='{"flow_run":{"name":"F1"}}'),
                   _dict(request_key='K3', owner='prakash@example.invalid', payload={'automation_run': 'RUN-1'})]
        messages = [_dict(name='M1', owner='Administrator', source_key='K1'), _dict(name='M2', owner='Administrator', source_key='K2'),
                    _dict(name='M3', owner='Administrator', source_key='K3'), _dict(name='M4', owner='Guest', source_key=None),
                    _dict(name='M5', owner='bob@example.invalid', source_key='old-key')]
        keys = []

        def get_all(doctype, filters, **kwargs):
            if doctype == 'Relay Message Action':
                keys.append(filters['request_key'][1])
                return actions
            return messages
        rows = [{'name': 'M1', 'direction': 'Outgoing'}, {'name': 'M2', 'direction': 'Outgoing'}, {'name': 'M3', 'direction': 'Outgoing'},
                {'name': 'M4', 'direction': 'Outgoing'}, {'name': 'M5', 'direction': 'Outgoing', 'legacy_author': 'old@example.invalid'},
                {'name': 'M6', 'direction': 'Incoming'}]
        cards = [{'user': 'anitha@example.invalid', 'name': 'Anitha K', 'image': '/files/a.png'}]
        with patch('frappe.get_all', side_effect=get_all), patch('relay_core.user_profiles.user_cards', return_value=cards) as read:
            add_senders(rows)
        read.assert_called_once_with(['anitha@example.invalid', 'old@example.invalid'])
        self.assertEqual(keys, [['K1', 'K2', 'K3', 'old-key']], 'Actions are read by their unique request key, in one query')
        self.assertEqual(rows[0]['sender'], {'user': 'anitha@example.invalid', 'name': 'Anitha K', 'image': '/files/a.png'})
        for row in rows[1:4]:
            self.assertEqual(row['sender'], {'automated': 1, 'name': 'Automation'}, row['name'])
        self.assertEqual(rows[4]['sender'], {'user': 'old@example.invalid', 'name': 'old@example.invalid', 'image': ''},
                         'A message without a send action names its import author')
        self.assertNotIn('sender', rows[5], 'The contact sends incoming messages')

    def test_rows_without_outgoing_messages_read_nothing(self):
        with patch('frappe.get_all') as get_all:
            self.assertEqual(add_senders([{'name': 'M1', 'direction': 'Incoming'}]), [{'name': 'M1', 'direction': 'Incoming'}])
        get_all.assert_not_called()
