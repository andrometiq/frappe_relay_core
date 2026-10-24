import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class DisplayTitlesTests(unittest.TestCase):
    def setUp(self):
        def throw(message): raise ValueError(message)
        self.f = types.SimpleNamespace(whitelist=lambda **kw: lambda fn: fn, throw=throw,
            has_permission=Mock(return_value=True), get_meta=Mock(return_value=types.SimpleNamespace(title_field='customer_name')),
            get_list=Mock(return_value=[{'name':'CUST-0026', 'customer_name':'Rao Textiles'}]))
        spec = importlib.util.spec_from_file_location('tested_display', Path('relay_core/display.py'))
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, frappe=self.f): spec.loader.exec_module(self.module)
        self.module.require_access = Mock()

    def test_title_field_is_read_through_permission_filtered_query(self):
        result = self.module.titles([{'doctype':'Customer', 'name':'CUST-0026'}])
        self.assertEqual(result, {'items':[{'doctype':'Customer', 'name':'CUST-0026', 'title':'Rao Textiles'}]})
        self.f.get_list.assert_called_once_with('Customer', filters={'name':'CUST-0026'}, fields=['name','customer_name'], page_length=1)

    def test_denied_missing_and_invalid_records(self):
        self.f.has_permission.return_value = False
        self.assertEqual(self.module.titles([{'doctype':'Customer', 'name':'private'}]), {'items':[]})
        self.f.get_list.assert_not_called()
        for invalid in (None, [{}], [{'doctype':'Customer', 'name':'bad\nvalue'}], [{}]*51):
            with self.assertRaises(ValueError): self.module.titles(invalid)
        self.f.has_permission.return_value = True
        self.f.get_list.return_value = []
        self.assertEqual(self.module.titles([{'doctype':'Customer', 'name':'missing'}]), {'items':[]})

    def test_legacy_channel_without_title_uses_safe_configured_identity(self):
        self.f.get_meta.return_value.title_field = 'title'
        self.f.get_list.return_value = [{'name':'RELAY-CH-0000000001','title':'','channel':'Email','account':'Support'}]
        result = self.module.titles([{'doctype':'Relay Channel','name':'RELAY-CH-0000000001'}])
        self.assertEqual(result['items'][0]['title'], 'Email · Support')
        self.assertEqual(self.f.get_list.call_args.kwargs['fields'], ['name','title','channel','account'])
