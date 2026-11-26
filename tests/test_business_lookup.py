"""Agent business lookups: configuration checks and the narrow read, without a site."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe import _dict
from frappe.exceptions import ValidationError
from relay_core import business_lookup


def field(fieldname, fieldtype='Data', **values):
    return _dict(dict(fieldname=fieldname, fieldtype=fieldtype, hidden=0, permlevel=0), **values)


FIELDS = {name: field(name, kind) for name, kind in (
    ('customer_name', 'Data'), ('city', 'Data'), ('territory', 'Link'), ('customer_group', 'Link'),
    ('disabled', 'Check'), ('credit_limit', 'Currency'), ('api_key', 'Data'), ('logo', 'Attach'), ('pin', 'Password'))}
FIELDS['internal'] = field('internal', permlevel=1)


def row(fieldname, search=0, share=0):
    return _dict(fieldname=fieldname, search=search, share=share)


def config(**values):
    return _dict(business_doctype='Customer', lookup_enabled=1, lookup_description='Distributors; search by city',
                 lookup_fields=[row('city', 1, 1), row('territory', 1), row('disabled', 1), row('customer_name', share=1)],
                 lookup_filters='{"disabled": 0, "customer_group": ["Distributor", "Super Stockist"]}', **values)


def throw(message, *args):
    raise ValidationError(message)


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.doc = config()
        self.fake = SimpleNamespace(
            get_meta=lambda doctype: _dict(get_field=FIELDS.get), throw=throw, bold=str,
            get_doc=Mock(side_effect=lambda doctype, name: self.doc),
            get_all=Mock(return_value=[{'customer_name': 'Sri Traders', 'city': 'Madurai'}]),
            db=SimpleNamespace(get_value=Mock(return_value='Customer')))
        self.enterContext(patch.object(business_lookup, 'frappe', self.fake))
        self.enterContext(patch.object(business_lookup, 'require_access'))

    def refused(self, message, **changes):
        self.doc.update(changes)
        with self.assertRaisesRegex(ValidationError, message):
            business_lookup.configuration(self.doc)

    def test_configuration_lists_search_share_and_fixed_filters(self):
        self.assertEqual(business_lookup.configuration(self.doc), {
            'business_type': 'Customer', 'description': 'Distributors; search by city',
            'search_fields': ['city', 'territory', 'disabled'], 'share_fields': ['city', 'customer_name'],
            'fixed_filters': {'disabled': 0, 'customer_group': ['Distributor', 'Super Stockist']}})

    def test_secret_attach_restricted_and_missing_fields_are_refused(self):
        for name in ('api_key', 'logo', 'pin', 'internal', 'missing'):
            with self.subTest(field=name):
                self.refused(f'{name} is not an available lookup field', lookup_fields=[row(name, share=1)])
        self.refused('pin is not an available', lookup_fields=[row('city', share=1)], lookup_filters='{"pin": "1"}')

    def test_bad_filters_duplicates_and_no_share_field_are_refused(self):
        for filters in ('[1]', 'not json', '{"city": {"like": "x"}}', '{"city": []}'):
            with self.subTest(filters=filters):
                self.refused('Fixed lookup filters must be', lookup_filters=filters)
        self.refused('distinct lookup fields', lookup_fields=[row('city', 1, 1), row('city', share=1)], lookup_filters='')
        self.refused('at least one share field', lookup_fields=[row('city', 1)])
        self.doc.update(lookup_enabled=0)
        self.assertEqual(business_lookup.configuration(self.doc)['share_fields'], [])

    def test_lookup_returns_only_share_fields_with_fixed_filters(self):
        result = business_lookup.search('Customer', {'city': 'madu_rai%', 'disabled': 1}, limit=3)
        self.assertEqual(result, {'business_type': 'Customer', 'items': [{'customer_name': 'Sri Traders', 'city': 'Madurai'}]})
        (doctype,), kwargs = self.fake.get_all.call_args
        self.assertEqual(doctype, 'Customer')
        self.assertEqual(kwargs['fields'], ['city', 'customer_name'])
        self.assertEqual(kwargs['filters'], [['city', 'like', '%madu\\_rai\\%%'], ['disabled', '=', 1], ['disabled', '=', 0],
                                             ['customer_group', 'in', ['Distributor', 'Super Stockist']]])
        self.assertIsNone(kwargs['or_filters'])
        self.assertEqual((kwargs['order_by'], kwargs['limit_page_length']), ('city asc', 3))

    def test_query_searches_text_share_fields_and_limit_is_capped(self):
        business_lookup.search('Customer', query='sri', limit=50)
        kwargs = self.fake.get_all.call_args.kwargs
        self.assertEqual(kwargs['or_filters'], [['city', 'like', '%sri%'], ['customer_name', 'like', '%sri%']])
        self.assertEqual(kwargs['limit_page_length'], business_lookup.MAX_LIMIT)

    def test_unconfigured_field_and_bad_values_are_refused(self):
        for filters in ({'customer_group': 'Distributor'}, {'credit_limit': 1}):
            with self.subTest(filters=filters), self.assertRaisesRegex(ValidationError, 'Cannot search Customer by'):
                business_lookup.search('Customer', filters)
        with self.assertRaisesRegex(ValidationError, 'at most 6 filters'):
            business_lookup.search('Customer', {'city': 'x' * 141})
        self.fake.get_all.assert_not_called()

    def test_disabled_or_unknown_lookup_is_refused(self):
        self.fake.db.get_value.return_value = None
        with self.assertRaisesRegex(ValidationError, 'has no agent lookup'):
            business_lookup.search('Supplier', {'city': 'Madurai'})
        self.assertEqual(self.fake.db.get_value.call_args.args,
                         ('Relay Contact Type', {'name': 'Supplier', 'enabled': 1, 'lookup_enabled': 1}))
        self.fake.get_all.assert_not_called()

    def test_types_lists_enabled_lookups_without_fixed_filters(self):
        self.fake.get_all.return_value = ['Customer']
        self.assertEqual(business_lookup.types(), {'items': [{
            'business_type': 'Customer', 'description': 'Distributors; search by city',
            'search_fields': ['city', 'territory', 'disabled'], 'share_fields': ['city', 'customer_name']}]})
        self.assertEqual(self.fake.get_all.call_args.kwargs['filters'], {'enabled': 1, 'lookup_enabled': 1})


if __name__ == '__main__':
    unittest.main()
