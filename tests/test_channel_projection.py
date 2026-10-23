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
