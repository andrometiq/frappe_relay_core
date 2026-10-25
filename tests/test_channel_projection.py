"""Provider-neutral input validation before any conversation writes."""
import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import patch


class ChannelProjectionTests(unittest.TestCase):
    def setUp(self):
        path = pathlib.Path(__file__).parents[1] / 'relay_core/automation/projection.py'
        spec = importlib.util.spec_from_file_location('channel_projection_under_test', path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe': types.ModuleType('frappe')}):
            spec.loader.exec_module(self.module)

    def test_normalized_inbound_preserves_endpoint_and_provider_id(self):
        for channel, sender in [('Telegram', '-100123456'), ('Email', 'person@example.test')]:
            with self.subTest(channel=channel):
                rows = self.module.extract_messages(dict(channel=channel, direction='inbound',
                    provider_id='provider-1', sender=sender, body='Hello'))
                self.assertEqual([{key:row[key] for key in ('id','from','type','text')} for row in rows], [{'id': 'provider-1', 'from': sender,
                    'type': 'text', 'text': {'body': 'Hello'}}])

    def test_outbound_does_not_become_incoming(self):
        self.assertEqual(self.module.extract_messages({'channel': 'Email', 'direction': 'outbound'}), [])

    def test_invalid_identities_rejected_before_writes(self):
        for changes in [{'provider_id': ''}, {'sender': None}, {'body': {}}, {'sender': 'x'*201}]:
            payload = dict(channel='Telegram', direction='inbound', provider_id='1', sender='2', body='Hi')
            payload.update(changes)
            with self.assertRaises(ValueError):
                self.module.extract_messages(payload)


class InteractiveMessageTests(unittest.TestCase):
    def test_form_reply_retains_fields_without_exposing_correlation_token(self):
        from relay_core.message_types import normalize
        result=normalize('interactive',{'nfm_reply':{'body':'Feedback received','response_json':'{"flow_token":"secret","rating":5,"details":{"helpful":true}}'}},provider='WhatsApp')
        self.assertEqual(result['text'],'Feedback received')
        self.assertEqual(result['form_response'],{'rating':5,'details':{'helpful':True}})
        self.assertNotIn('secret',str(result))

    def test_invalid_form_replies_are_rejected(self):
        from relay_core.message_types import normalize
        for raw in ('[]','not json','x'*12001):
            with self.assertRaises(ValueError):normalize('interactive',{'nfm_reply':{'response_json':raw}},provider='WhatsApp')

class WhatsAppInboundTypesTests(unittest.TestCase):
    setUp = ChannelProjectionTests.setUp

    def extract(self, kind, detail, **extra):
        message = {'id': 'wamid.fixture', 'from': '919999999999', 'from_user_id': 'business-scoped-user',
                   'type': kind, kind: detail, **extra}
        return self.module.extract_messages({'entry': [{'changes': [{'value': {'messages': [message]}}]}]})

    def test_media_preserves_metadata_and_ignores_download_urls(self):
        from relay_core.message_types import preview
        for kind in ('image', 'audio', 'video', 'document', 'sticker'):
            detail = {'id': '123', 'mime_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                      'filename': 'Local fixture.docx', 'file_size': 12345, 'caption': 'Local test caption',
                      'url': 'https://private.invalid/signed', 'sha256': 'opaque-digest'}
            row, = self.extract(kind, detail)
            self.assertEqual(row['type'], kind)
            self.assertEqual(row['from'], '919999999999')
            self.assertEqual(row['from_user_id'], 'business-scoped-user')
            data = row['message_data']
            self.assertEqual(data, {'kind': kind, 'media': {key: detail[key] for key in ('id', 'mime_type', 'filename', 'file_size')}, 'caption': 'Local test caption'})
            self.assertEqual(preview(data), 'Local test caption')
        row, = self.extract('document', {'id': '123', 'filename': 'Local fixture.docx'})
        self.assertEqual(preview(row['message_data']), 'Local fixture.docx')

    def test_common_inbound_types(self):
        cases = [
            ('text', {'body': 'Hello'}, 'text'),
            ('location', {'latitude': 12.9, 'longitude': 80.2, 'name': 'Local fixture'}, 'location'),
            ('contacts', [{'name': {'formatted_name': 'Local fixture'}, 'phones': [{'phone': '+919999999999'}]}], 'contacts'),
            ('button', {'text': 'Yes', 'payload': 'yes'}, 'text'),
            ('interactive', {'button_reply': {'id': 'yes', 'title': 'Yes'}}, 'text'),
            ('interactive', {'list_reply': {'id': 'item', 'title': 'Item'}}, 'text'),
            ('interactive', {'nfm_reply': {'body': 'Form submitted', 'response_json': '{"rating":5}'}}, 'text'),
            ('interactive', {'call_permission_reply': {'response': 'accept'}}, 'text'),
            ('interactive', {'type': 'unknown_reply'}, 'unsupported'),
            ('order', {'catalog_id': '123'}, 'unsupported'),
            ('system', {'body': 'Number changed'}, 'unsupported'),
            ('unsupported', {'raw_type': 'poll_creation'}, 'unsupported'),
            ('future_type', {}, 'unsupported'),
        ]
        for kind, detail, normalized in cases:
            with self.subTest(kind=kind, detail=detail):
                row, = self.extract(kind, detail)
                self.assertEqual(row['message_data']['kind'], normalized)
        self.assertEqual(self.extract('reaction', {'message_id': 'wamid.original', 'emoji': '👍'}), [])
