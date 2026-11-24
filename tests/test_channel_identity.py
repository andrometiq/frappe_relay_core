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

    def test_legacy_alias_search_is_one_indexed_read_that_includes_revoked_bindings(self):
        from unittest.mock import patch
        from frappe import _dict
        from relay_core.identity import bindings
        revoked = _dict(name='legacy', endpoint='PERSON@EXAMPLE.INVALID', verified=0, relay_contact='other-owner')
        with patch('frappe.get_all', return_value=[revoked]) as query:
            self.assertEqual(list(bindings('channel', 'Email', ' Person@Example.invalid')), [revoked])
        query.assert_called_once()
        self.assertEqual(query.call_args.kwargs['filters'],
                         {'channel': 'channel', 'canonical_endpoint': 'person@example.invalid'})

    def test_canonical_endpoint_matches_every_stored_alias_and_skips_rejected_values(self):
        from relay_core.identity import canonical_endpoint
        for stored in ('+91 98765-43210', '(91) 98765 43210', '919876543210'):
            self.assertEqual(canonical_endpoint('WhatsApp', stored), '919876543210')
        self.assertEqual(canonical_endpoint('Telegram', '000123456'), '123456')
        self.assertIsNone(canonical_endpoint('Telegram', '@username'))
        self.assertIsNone(canonical_endpoint(None, '919876543210'))
