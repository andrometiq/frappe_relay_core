"""Picker authorization and metadata filtering without an installed Frappe bench."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class Row(dict):
    __getattr__ = dict.get


class BusinessEventOptionsTests(unittest.TestCase):
    def setUp(self):
        self.frappe = types.SimpleNamespace(
            whitelist=lambda **kw: lambda fn: fn, PermissionError=PermissionError,
            parse_json=json.loads, has_permission=Mock(return_value=True), get_list=Mock(return_value=[]),
            get_meta=Mock(), throw=Mock(side_effect=PermissionError),
        )
        self.modules = patch.dict(sys.modules, {'frappe': self.frappe})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location('event_options_test', Path(__file__).parents[1] / 'relay_core/business_event_options.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.fields = [Row(fieldname=key, label=label, fieldtype=kind, options=target, hidden=hidden)
            for key, label, kind, target, hidden in [
                ('customer', 'Customer', 'Link', 'Customer', 0),
                ('contact_person', 'Contact person', 'Link', 'Contact', 0),
                ('total', 'Grand total', 'Currency', None, 0),
                ('private_total', 'Private total', 'Currency', None, 0),
                ('secret', 'Password', 'Password', None, 0),
                ('hidden', 'Hidden field', 'Data', None, 1),
                ('items', 'Items', 'Table', 'Sales Invoice Item', 0)]]
        self.frappe.get_meta.return_value = Row(fields=self.fields,
            get_permitted_fieldnames=lambda **kw: [row.fieldname for row in self.fields if row.fieldname != 'private_total'],
            get_field=lambda key: next((row for row in self.fields if row.fieldname == key), None))

    def values(self, kind, **kw):
        return [row['value'] for row in self.module.search(kind, **kw)['items']]

    def test_requires_rule_write_and_source_read_access(self):
        self.frappe.has_permission.return_value = False
        with self.assertRaises(PermissionError): self.module.search('doctype')
        self.frappe.get_list.assert_not_called()
        self.frappe.has_permission.side_effect = lambda name, mode, **kw: name == 'Relay Business Event Rule'
        with self.assertRaises(PermissionError): self.module.search('field', doctype='Sales Invoice')
        self.frappe.get_meta.assert_not_called()

    def test_fields_are_readable_scalar_or_correct_links(self):
        args = dict(doctype='Sales Invoice', business_doctype='Customer')
        self.assertEqual(self.values('recipient_field', **args), ['customer'])
        self.assertEqual(self.values('contact_field', **args), ['contact_person'])
        self.assertEqual(self.values('field', **args), ['name', 'customer', 'contact_person', 'total', 'items_summary'])
        self.assertEqual(self.values('field', query='Grand', **args), ['total'])
        self.assertEqual(self.values('field', selected='["private_total"]', **args), [])
        self.assertEqual(self.values('field'), [])

    def test_record_search_is_bounded_and_permission_filtered(self):
        self.frappe.get_list.return_value = [Row(name='Sales Invoice'), Row(name='Relay Message'), Row(name='Private')]
        self.frappe.has_permission.side_effect = lambda name, *args, **kw: name != 'Private'
        self.assertEqual(self.values('doctype'), ['Sales Invoice'])
        args = self.frappe.get_list.call_args.kwargs
        self.assertEqual(args['page_length'], 30)
        self.assertEqual(args['filters']['istable'], 0)
        self.assertEqual(args['filters']['issingle'], 0)
        self.frappe.get_list.return_value = [Row(name='Guest', full_name='Guest'), Row(name='agent', full_name='Asha')]
        with patch.object(self.module, 'can_manage', return_value=True):
            self.assertEqual(self.module.search('user')['items'], [{'value': 'agent', 'label': 'Asha'}])
        with patch.object(self.module, 'can_manage', return_value=False):
            self.assertEqual(self.values('user'), [])

    def test_print_and_report_are_scoped_to_source(self):
        for kind, key in [('print_format', 'doc_type'), ('report', 'ref_doctype')]:
            self.assertEqual(self.values(kind), [])
            self.module.search(kind, doctype='Sales Invoice', selected='["Invoice"]')
            filters = self.frappe.get_list.call_args.kwargs['filters']
            self.assertEqual(filters[key], 'Sales Invoice')
            self.assertEqual(filters['disabled'], 0)
            self.assertEqual(filters['name'], ['in', ['Invoice']])

    def test_bad_arguments(self):
        for args in [dict(kind='sql'), dict(kind='doctype', query='x' * 81), dict(kind='field', selected='{}'),
                     dict(kind='field', selected=['x'] * 21), dict(kind='field', selected=[1])]:
            with self.assertRaises(ValueError): self.module.search(**args)
        with self.assertRaises(PermissionError): self.module.search('field', doctype='Relay Message')
