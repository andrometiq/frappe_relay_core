import json
from pathlib import Path
import unittest
from unittest.mock import patch

from frappe import _dict
from relay_core.automation.provenance import email_message_id
from relay_core.relay_core.doctype.relay_message import relay_message


class ProviderIdentityTests(unittest.TestCase):
    def test_provider_identity_is_validated_without_html_sanitization(self):
        schema = json.loads(Path(relay_message.__file__).with_suffix('.json').read_text())
        field = next(row for row in schema['fields'] if row['fieldname'] == 'provider_id')
        self.assertEqual(field['ignore_xss_filter'], 1)
        for value in ('<MiXeD+tag=123@example.invalid>', 'telegram-123', 'wamid.ABC', '', None):
            doc = _dict(provider_id=value)
            relay_message.RelayMessage.validate(doc)
            self.assertEqual(doc.provider_id, value)

    def test_markup_controls_and_header_injection_are_rejected(self):
        for value in ('<script>alert(1)</script>', '<img src=x onerror=alert(1)>',
                      '<x@example.invalid>\r\nBcc:x@example.invalid', '<x\x00@example.invalid>',
                      '<x\x7f@example.invalid>', 'id\nnext'):
            with self.subTest(value=value), patch.object(relay_message.frappe, 'throw', side_effect=ValueError):
                with self.assertRaises(ValueError):
                    relay_message.RelayMessage.validate(_dict(provider_id=value))
            if value.startswith('<'):
                self.assertIsNone(email_message_id(value))

        # HTML also accepts slash as an attribute delimiter without whitespace.
        with patch.object(relay_message.frappe, 'throw', side_effect=ValueError):
            with self.assertRaises(ValueError):
                relay_message.RelayMessage.validate(_dict(provider_id='<img/src=x@x/onerror=alert(1)>'))

    def test_sanitized_history_is_still_valid_without_rekeying(self):
        doc = _dict(provider_id='', source_key='original-source-hash', provider_message_key='original-provider-hash',
                    provider_context=json.dumps({'provider': 'Email', 'message_id': '<old@example.invalid>'}))
        before = dict(doc)
        relay_message.RelayMessage.validate(doc)
        self.assertEqual(doc, before)
