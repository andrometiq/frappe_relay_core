import unittest
from relay_core.message_display import decorate_messages, mailbox_addresses


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
