"""Ticket service boundary tests; no site data is created."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class TicketTests(unittest.TestCase):
    def setUp(self):
        def throw(message): raise ValueError(message)
        self.f = types.SimpleNamespace(get_roles=lambda: ['Relay Communication User'], throw=throw, whitelist=lambda **kw: lambda fn: fn, get_doc=Mock())
        spec = importlib.util.spec_from_file_location('tested_tickets', Path('relay_core/tickets.py'))
        self.api = types.ModuleType('relay_core.api')
        def reference(value, prefix):
            import re
            if not isinstance(value, str) or not re.fullmatch('RELAY-'+prefix+'-[0-9]{10}', value):
                throw('Invalid reference')
        self.api.validate_reference = reference
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe':self.f, 'relay_core.api':self.api}):
            spec.loader.exec_module(self.module)
        self.module.require_access = Mock()
        self.module.readable_contact = Mock()
        self.message = types.SimpleNamespace(name='RELAY-MSG-0000000001',relay_contact='RELAY-CON-0000000001',channel='RELAY-CH-0000000001',check_permission=Mock())
        self.contact = types.SimpleNamespace(check_permission=Mock())
        self.f.get_doc.side_effect = lambda doctype, name: self.message if doctype == 'Relay Message' else self.contact
        self.doc = types.SimpleNamespace(subject='Payment query', brief='Review attached evidence',category='Payment evidence',status='Open',messages=[types.SimpleNamespace(message=self.message.name)])

        self.doc.get_doc_before_save=lambda:None
        self.doc.get=lambda key:getattr(self.doc,key,None)

    def test_each_link_requires_message_and_contact_read_permission(self):
        self.module.validate_ticket(self.doc)
        self.message.check_permission.assert_called_once_with('read')
        self.module.readable_contact.assert_called_once_with(self.message.relay_contact)
        self.message.check_permission.side_effect=PermissionError
        with self.assertRaises(PermissionError): self.module.validate_ticket(self.doc)

    def test_duplicate_and_oversize_message_lists_rejected(self):
        self.doc.messages *= 2
        with self.assertRaises(ValueError): self.module.validate_ticket(self.doc)
        self.doc.messages *= 26
        with self.assertRaises(ValueError): self.module.validate_ticket(self.doc)

    def test_invalid_status_or_category_rejected(self):
        self.doc.status='anything'
        with self.assertRaises(ValueError): self.module.validate_ticket(self.doc)
        self.doc.status='Open';self.doc.category='anything'
        with self.assertRaises(ValueError): self.module.validate_ticket(self.doc)

    def test_api_rejects_unbounded_or_malformed_create_before_insert(self):
        for messages in ([], ['x']*51, [{}], True):
            with self.assertRaises(ValueError): self.module.create('subject',messages)
        self.f.get_doc.assert_not_called()

    def test_read_rechecks_access_instead_of_exposing_stale_links(self):
        self.doc.name='RELAY-TKT-0000000001';self.doc.check_permission=Mock()
        self.f.get_doc.side_effect=lambda doctype,name: self.doc if doctype=='Relay Ticket' else self.message if doctype=='Relay Message' else self.contact
        self.doc.creation = '2026-10-24 09:00:00'
        result=self.module.read(self.doc.name)
        self.assertEqual(result['creation'], self.doc.creation)
        self.assertEqual(result['messages'][0]['message'],self.message.name)
        self.module.readable_contact.side_effect=PermissionError
        with self.assertRaises(PermissionError):self.module.read(self.doc.name)


    def test_directory_applies_business_assignee_category_and_status_filters(self):
        self.f.get_list = Mock(return_value=[])
        self.module.directory(business_doctype='Supplier', business_name='SUP-A', assigned_to='agent', category='Support', status='Open')
        self.assertEqual(self.f.get_list.call_args.kwargs['filters'], dict(business_doctype='Supplier',
            business_name='SUP-A', assigned_to='agent', category='Support', status='Open'))

    def test_business_tag_cannot_differ_from_linked_conversation(self):
        self.doc.business_doctype = 'Supplier'; self.doc.business_name = 'SUP-B'
        access = types.SimpleNamespace(reference=lambda doc: ('Supplier', 'SUP-A'))
        with patch.dict(sys.modules, {'relay_core.business_access': access}):
            with self.assertRaises(ValueError): self.module.validate_ticket(self.doc)
