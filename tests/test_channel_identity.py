import unittest
from relay_core.identity import normalize


class IdentityTests(unittest.TestCase):
    def test_formatting_aliases_cannot_bypass_binding_uniqueness(self):
        self.assertEqual(normalize('WhatsApp', '+91 (9555) 000123'), normalize('WhatsApp', '919555000123'))
        self.assertEqual(normalize('Telegram', '000123456'), normalize('Telegram', '123456'))
        self.assertEqual(normalize('Email', ' Person+Sales@EXAMPLE.INVALID '), 'person+sales@example.invalid')
        self.assertNotEqual(normalize('Email', 'person+sales@example.invalid'), normalize('Email', 'person@example.invalid'))
        self.assertEqual(normalize('WhatsApp', 'legacy-group@g.us'), 'legacy-group@g.us')

    def test_unverifiable_names_and_injected_identities_are_rejected(self):
        for provider, value in [('Telegram', '@username'), ('Telegram', '0'), ('Telegram', str(2**52)),
                                ('Telegram', '1.0'), ('Email', 'Name <name@example.invalid>'),
                                ('Email', 'name@example.invalid\nBcc:other@example.invalid'), ('Email', 'missing-domain'),
                                ('Telegram', True)]:
            with self.subTest(provider=provider, value=value), self.assertRaises(ValueError):
                normalize(provider, value)

    def test_legacy_alias_search_includes_revoked_bindings_after_first_page(self):
        from unittest.mock import patch
        from frappe import _dict
        from relay_core.identity import bindings
        rows = [_dict(name=str(i), endpoint=f'other{i}@example.invalid', verified=1) for i in range(500)]
        revoked = _dict(name='legacy', endpoint='PERSON@EXAMPLE.INVALID', verified=0, relay_contact='other-owner')
        with patch('frappe.get_all', side_effect=[rows, [revoked]]) as query:
            self.assertEqual(list(bindings('channel', 'Email', 'person@example.invalid')), [revoked])
        self.assertEqual(query.call_args.kwargs['limit_start'], 500)
        self.assertEqual(query.call_args.kwargs['filters'], {'channel': 'channel'})
