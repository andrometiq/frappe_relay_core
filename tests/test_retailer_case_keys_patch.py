"""Retailer case key patch: old business prefixes move to the neutral Relay prefix once. No site data is touched."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch

from frappe import _dict

from relay_core.flows import retailer

PATCH = 'relay_core.patches.v1_0.use_neutral_retailer_case_keys'


class RetailerCaseKeysPatchTests(unittest.TestCase):
    def run_patch(self, rows):
        updates = []

        def set_value(doctype, name, field, value, update_modified=True):
            updates.append((name, value, update_modified))
            next(row for row in rows if row.name == name).type_key = value

        def exists(doctype, filters):
            return any(row.type_key == filters['type_key'] for row in rows)

        def get_all(doctype, filters=None, fields=None):
            marker = filters['type_key'][1].strip('%')
            return [_dict(row) for row in rows if marker in row.type_key]

        fake = types.SimpleNamespace(get_all=get_all, db=types.SimpleNamespace(set_value=set_value, exists=exists))
        with patch.dict(sys.modules, frappe=fake):
            sys.modules.pop(PATCH, None)
            importlib.import_module(PATCH).execute()
        sys.modules.pop(PATCH, None)
        return updates

    def test_old_prefix_moves_once_and_keeps_modified(self):
        rows = [_dict(name='Callback-001', type_key='acme.retailer_connect.callback'),
                _dict(name='Catalogue-001', type_key=retailer.TYPE_PREFIX + 'catalogue'),
                _dict(name='Other-001', type_key='acme.other.callback')]
        self.assertEqual(self.run_patch(rows), [('Callback-001', retailer.TYPE_PREFIX + 'callback', False)])
        self.assertEqual(self.run_patch(rows), [], 'A second run changes nothing')

    def test_unknown_suffix_and_existing_target_stay(self):
        rows = [_dict(name='Odd-001', type_key='acme.retailer_connect.unknown'),
                _dict(name='Old-001', type_key='acme.retailer_connect.complaint'),
                _dict(name='New-001', type_key=retailer.TYPE_PREFIX + 'complaint')]
        self.assertEqual(self.run_patch(rows), [])
        self.assertEqual(rows[1].type_key, 'acme.retailer_connect.complaint')


if __name__ == '__main__':
    unittest.main()
