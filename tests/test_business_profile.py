"""Business profile fields: the field whitelist, display values and the record-access gate, without a site."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe import _dict
from relay_core import business_types


def field(fieldname, fieldtype='Data', **values):
    return _dict(dict(fieldname=fieldname, label=fieldname.replace('_', ' ').title(), fieldtype=fieldtype,
                      hidden=0, permlevel=0), **values)


FIELDS = {'territory': field('territory', 'Link'), 'credit_limit': field('credit_limit', 'Currency'),
          'is_frozen': field('is_frozen', 'Check'), 'secret': field('secret', 'Password'),
          'internal': field('internal', permlevel=1), 'items': field('items', 'Table'),
          'notes': field('notes', hidden=1), 'mobile': field('mobile', 'Phone')}


class BusinessProfileTests(unittest.TestCase):
    def setUp(self):
        self.picked = [_dict(fieldname=name, label=None) for name in ('credit_limit', 'territory', 'is_frozen', 'internal', 'missing')]
        self.fake = SimpleNamespace(
            get_meta=lambda doctype: _dict(get_field=FIELDS.get, title_field='territory_name'),
            get_all=Mock(side_effect=lambda *a, **kw: self.picked),
            format_value=lambda value, df, doc: f'₹ {value:,.2f}' if df.fieldtype == 'Currency' else value,
            db=SimpleNamespace(get_value=Mock(return_value='Retailer')))
        self.enterContext(patch.object(business_types, 'frappe', self.fake))

    def test_only_visible_data_fields_can_be_picked(self):
        allowed = {name for name, df in FIELDS.items() if business_types.is_profile_field(df)}
        self.assertEqual(allowed, {'territory', 'credit_limit', 'is_frozen', 'mobile'})
        self.assertFalse(business_types.is_profile_field(None))

    def test_profile_keeps_order_formats_values_and_drops_restricted_fields(self):
        doc = _dict(doctype='YRP Retailer', credit_limit=125000, territory='', is_frozen=0)
        self.assertEqual(business_types.profile(doc), [
            {'label': 'Credit Limit', 'value': '₹ 125,000.00'},
            {'label': 'Territory', 'value': ''},
            {'label': 'Is Frozen', 'value': 'No'}])
        self.picked[1].label = 'Region'
        self.fake.db.get_value.return_value = 'South India'
        doc.territory = 'T-0001'
        self.assertEqual(business_types.profile(doc)[1], {'label': 'Region', 'value': 'South India'},
                         'A label override and a Link shown by its title')
        filters = self.fake.get_all.call_args.kwargs['filters']
        self.assertEqual(filters, {'parent': 'YRP Retailer', 'parenttype': 'Relay Contact Type', 'parentfield': 'profile_fields'})
        self.assertEqual(self.fake.get_all.call_args.kwargs['limit_page_length'], business_types.MAX_PROFILE_FIELDS)

    def test_no_picked_fields_gives_an_empty_profile(self):
        self.picked = []
        self.assertEqual(business_types.profile(_dict(doctype='Customer')), [])

    def test_type_label_uses_the_configured_label(self):
        self.assertEqual(business_types.type_label('YRP Retailer'), 'Retailer')
        self.fake.db.get_value.return_value = None
        self.assertEqual(business_types.type_label('Customer'), 'Customer')


class BusinessContextAccessTests(unittest.TestCase):
    def test_context_reads_the_profile_only_after_the_record_access_check(self):
        from relay_core import business_inbox
        denied = frappe.PermissionError('Business record is not accessible')
        with patch.object(business_inbox, 'check_type'), \
                patch.object(business_inbox, 'business_document', side_effect=denied), \
                patch.object(business_types, 'profile') as profile:
            with self.assertRaises(frappe.PermissionError):
                business_inbox.context('Customer', 'LOCAL-C1')
            profile.assert_not_called()


if __name__ == '__main__':
    unittest.main()
