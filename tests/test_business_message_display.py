"""Business history keeps the same trusted display metadata as contact history."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class Row(dict):
    __getattr__ = dict.get


class Query:
    def __init__(self, rows=()): self.rows = list(rows)
    def __getattr__(self, key): return self
    def __call__(self, *args, **kwargs): return self
    def __eq__(self, other): return self
    def __and__(self, other): return self
    def __or__(self, other): return self
    def run(self, **kwargs): return self.rows


class BusinessMessageDisplayTests(unittest.TestCase):
    def setUp(self):
        self.channel = Mock()
        self.channel.get.side_effect = {'channel':'Email','title':'Support','mailbox_address':'support@example.invalid'}.get
        self.business = Mock()
        self.f = SimpleNamespace(whitelist=lambda **kw: lambda fn: fn, qb=Query(),
            get_doc=Mock(side_effect=lambda dt, name: self.channel if dt == 'Relay Channel' else self.business), PermissionError=PermissionError)
        spec = importlib.util.spec_from_file_location('tested_business_display', Path('relay_core/business_inbox.py'))
        self.api = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe':self.f, 'relay_core.api':SimpleNamespace(validate_reference=Mock())}): spec.loader.exec_module(self.api)
        self.api.check_type = Mock()
        self.api.readable_contact = Mock(return_value=(Row(display_name='Maya',contact='maya'), None))
        self.row = Row(name='RELAY-MSG-0000000001',relay_contact='RELAY-CON-0000000001',channel='Support-001',
            provider_context={'provider':'Email','mailbox_addresses':['forged@example.invalid']})

    def test_page_has_trusted_metadata_and_checks_business_channel_and_contact(self):
        query = Mock(return_value=Query([self.row]))
        with patch.dict(sys.modules, {'relay_core.timeline':SimpleNamespace(page_query=query)}):
            result = self.api.messages('Customer','customer',names=[self.row.name])
        self.assertEqual(result['items'][0]['channel_title'],'Support')
        self.assertEqual(result['items'][0]['provider_context']['mailbox_addresses'],['support@example.invalid'])
        self.assertEqual(result['items'][0]['contact_label'],'Maya')
        self.business.check_permission.assert_called_once_with('read')
        self.channel.check_permission.assert_called_once_with('read')
        self.api.readable_contact.assert_called_once_with(self.row.relay_contact)
        self.business.check_permission.side_effect = PermissionError
        with self.assertRaises(PermissionError): self.api.messages('Customer','customer')

    def test_context_preserves_metadata_on_the_anchor_and_adjacent_pages(self):
        row = dict(self.row, channel_title='Support',provider_context={'mailbox_addresses':['support@example.invalid']})
        self.api.messages = Mock(return_value={'items':[row],'has_more':False})
        result = self.api.message_context('Customer','customer',self.row.name)
        self.assertEqual(result['anchor'],self.row.name)
        self.assertTrue(all(item['channel_title'] == 'Support' for item in result['items']))
        self.api.messages.side_effect = PermissionError
        with self.assertRaises(PermissionError): self.api.message_context('Customer','customer',self.row.name)
