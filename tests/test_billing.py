"""WhatsApp billing: Meta pricing parsing, idempotent month rows, margin math and access."""
import json
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe import _dict
from relay_core import billing
from relay_core.hub import HubError
from relay_core.relay_core.doctype.relay_settings.relay_settings import RelaySettings


def thrown(message, exc=frappe.ValidationError, *args, **kwargs):
    raise exc(message)


def utc(*parts):
    return int(datetime(*parts, tzinfo=timezone.utc).timestamp())


class Store:
    """Billing month rows keyed by name, standing in for the database."""
    def __init__(self):
        self.rows, self.inserts, self.updates = {}, 0, 0

    def exists(self, doctype, name):
        return name in self.rows

    def insert(self, values):
        self.inserts += 1
        self.rows[values['record_key']] = dict(values)

    def set_value(self, doctype, name, fields):
        self.updates += 1
        self.rows[name].update(fields)


class BillingTests(unittest.TestCase):
    def setUp(self):
        self.zone = 'Asia/Kolkata'
        self.roles = ['WhatsApp Manager']
        self.store = Store()
        self.sql = Mock(return_value=[])
        self.frappe = Mock()
        self.frappe.throw.side_effect = thrown
        self.frappe.PermissionError, self.frappe.ValidationError = frappe.PermissionError, frappe.ValidationError
        self.frappe.DuplicateEntryError = frappe.DuplicateEntryError
        self.frappe.utils = SimpleNamespace(get_system_timezone=lambda: self.zone,
                                            getdate=lambda value=None: frappe.utils.getdate(value or '2026-01-03'),
                                            now_datetime=lambda: 'now')
        self.frappe.db = SimpleNamespace(exists=self.store.exists, set_value=self.store.set_value, sql=self.sql,
                                         commit=Mock(), rollback=Mock())
        self.frappe.flags = SimpleNamespace()
        patcher = patch.object(billing, 'frappe', self.frappe)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, value in (('get_roles', lambda user=None: self.roles), ('throw', thrown),
                            ('session', SimpleNamespace(user='manager@example.com'))):
            patcher = patch.object(frappe, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        insert = patch.object(billing, 'insert', side_effect=self.store.insert)
        insert.start()
        self.addCleanup(insert.stop)
        account = patch.object(billing, 'connection_value', return_value='acct-1')
        account.start()
        self.addCleanup(account.stop)

    def point(self, category='MARKETING', pricing_type='REGULAR', volume=10, cost=2.5, start=None, end=None):
        return {'start': start or utc(2026, 1, 31, 18, 30), 'end': end or utc(2026, 2, 28, 18, 30),
                'volume': volume, 'cost': cost, 'pricing_category': category, 'pricing_type': pricing_type, 'country': 'IN'}

    def hub(self, points):
        hub = Mock()
        hub.execute.return_value = {'data_points': points}
        return patch('relay_core.whatsapp.checked_client', return_value=(hub, {})), hub

    def test_margin_defaults_to_30_until_a_value_is_saved(self):
        self.assertEqual(billing.margin_percent(), 30.0)
        self.sql.return_value = [('0',)]
        self.assertEqual(billing.margin_percent(), 0.0)
        self.sql.return_value = [('12.5',)]
        self.assertEqual(billing.margin_percent(), 12.5)
        with open(billing.__file__.replace('billing.py', 'relay_core/doctype/relay_settings/relay_settings.json')) as file:
            fields = {field['fieldname']: field for field in json.load(file)['fields']}
        self.assertEqual(fields['whatsapp_margin_percent']['default'], '30')

    def test_only_system_manager_can_save_the_margin(self):
        settings = SimpleNamespace(hub_url='', hub_account='', transcription_provider='', whatsapp_margin_percent=40,
                                   get=lambda field: None)
        with self.assertRaises(frappe.PermissionError):
            RelaySettings.validate(settings)
        self.roles = ['System Manager']
        RelaySettings.validate(settings)
        settings.whatsapp_margin_percent = 5000
        with self.assertRaisesRegex(frappe.ValidationError, 'between 0 and 1000'):
            RelaySettings.validate(settings)

    def test_non_managers_are_denied_billing(self):
        self.roles = ['WhatsApp User']
        with self.assertRaises(frappe.PermissionError):
            billing.get_billing('acct-1', 2026)
        with self.assertRaises(frappe.PermissionError):
            billing.refresh_billing('acct-1', 2026)
        self.roles = ['WhatsApp Manager']
        self.frappe.get_list.return_value = []
        with self.assertRaisesRegex(frappe.PermissionError, 'not accessible'):
            billing.get_billing('other-account', 2026)

    def test_upsert_is_idempotent_per_account_month_category_and_type(self):
        rows = billing.parse([self.point(), self.point('UTILITY', volume=3, cost=0.3)])
        for _ in range(2):
            for key, values in rows.items():
                billing.upsert('acct-1', key, values, 'now')
        self.assertEqual((len(self.store.rows), self.store.inserts, self.store.updates), (2, 2, 2))
        row = next(row for row in self.store.rows.values() if row.get('category') == 'MARKETING')
        self.assertEqual((row['period'], row['volume'], row['meta_cost']), (date(2026, 2, 1), 10, 2.5))
        self.assertEqual(json.loads(row['raw_data'])[0]['country'], 'IN')

    def test_a_concurrent_insert_turns_into_an_update(self):
        key, values = next(iter(billing.parse([self.point()]).items()))
        billing.insert.side_effect = frappe.DuplicateEntryError
        name = billing.record_key({'account': 'acct-1', 'period': key[0], 'category': key[1], 'pricing_type': key[2]})
        self.store.rows[name] = {}
        self.store.exists = lambda doctype, name: False
        self.frappe.db.exists = self.store.exists
        billing.upsert('acct-1', key, values, 'now')
        self.assertEqual(self.store.rows[name]['volume'], 10)

    def test_parse_sums_points_and_reads_missing_fields_defensively(self):
        rows = billing.parse([self.point(volume='4', cost='1.25'), self.point(volume=6, cost=None),
                              {'start': utc(2026, 3, 1), 'end': utc(2026, 4, 1)}, {'volume': 9}, 'bad'])
        self.assertEqual(rows[(date(2026, 2, 1), 'MARKETING', 'REGULAR')]['volume'], 10)
        self.assertEqual(rows[(date(2026, 2, 1), 'MARKETING', 'REGULAR')]['meta_cost'], 1.25)
        self.assertEqual(rows[(date(2026, 3, 1), 'UNKNOWN', 'UNKNOWN')]['volume'], 0)
        self.assertEqual(len(rows), 2)

    def test_margin_math_includes_zero_volume(self):
        self.assertEqual(billing.priced(0, 0, 30), {'volume': 0, 'meta_cost': 0.0, 'margin_amount': 0.0, 'total': 0.0})
        self.assertEqual(billing.priced(10, 2.5, 30), {'volume': 10, 'meta_cost': 2.5, 'margin_amount': 0.75, 'total': 3.25})
        self.assertEqual(billing.priced(10, 2.5, 0)['total'], 2.5)
        rows = [_dict(period=date(2026, 2, 1), category='MARKETING', pricing_type='REGULAR', volume=10, meta_cost=2.5),
                _dict(period=date(2026, 2, 1), category='SERVICE', pricing_type='FREE_CUSTOMER_SERVICE', volume=0, meta_cost=0)]
        months, categories, total = billing.summarise(2026, rows, {2: 7}, 30)
        self.assertEqual(len(months), 12)
        self.assertEqual((months[1]['period'], months[1]['messages_sent'], months[1]['total']), ('2026-02-01', 7, 3.25))
        self.assertEqual(months[0]['total'], 0.0)
        self.assertEqual([item['category'] for item in categories], ['MARKETING', 'SERVICE'])
        self.assertEqual((total['meta_cost'], total['margin_amount'], total['total'], total['messages_sent']), (2.5, 0.75, 3.25, 7))

    def test_months_follow_the_site_timezone(self):
        self.assertEqual(billing.period_of({'start': utc(2026, 1, 31, 18, 30), 'end': utc(2026, 2, 28, 18, 30)}), date(2026, 2, 1))
        self.assertEqual(billing.period_of({'start': utc(2026, 1, 31, 20, 0)}), date(2026, 2, 1))
        self.zone = 'America/New_York'
        self.assertEqual(billing.period_of({'start': utc(2026, 2, 1), 'end': utc(2026, 3, 1)}), date(2026, 2, 1))
        self.assertEqual(billing.period_of({'start': utc(2026, 2, 1, 2, 0)}), date(2026, 1, 1))
        self.zone = 'Asia/Kolkata'
        self.assertEqual(billing.year_bounds(2026, datetime(2027, 6, 1, tzinfo=timezone.utc)),
                         (utc(2025, 12, 31, 18, 30), utc(2026, 12, 31, 18, 30)))
        self.assertEqual(billing.year_bounds(2026, datetime(2026, 3, 1, tzinfo=timezone.utc))[1], utc(2026, 3, 1))

    def test_refresh_reads_monthly_pricing_through_the_hub(self):
        client, hub = self.hub([self.point(), self.point('SERVICE', 'FREE_CUSTOMER_SERVICE', 4, 0)])
        with client, patch.object(billing, 'year_bounds', return_value=(100, 200)):
            self.assertEqual(billing.refresh('acct-1', '2026'), {'rows': 2, 'data_points': 2})
        hub.execute.assert_called_once_with({'operation': 'billing.pricing', 'start': 100, 'end': 200, 'granularity': 'MONTHLY',
                                             'dimensions': ['PRICING_CATEGORY', 'PRICING_TYPE']})
        self.assertEqual(self.store.inserts, 2)

    def test_refresh_rejects_bad_input_and_responses(self):
        with self.assertRaisesRegex(frappe.ValidationError, 'configured Hub account'):
            billing.refresh('other-account', 2026)
        with self.assertRaisesRegex(frappe.ValidationError, 'between 2020'):
            billing.refresh('acct-1', 1999)
        client, hub = self.hub(None)
        hub.execute.return_value = {'unexpected': []}
        with client, self.assertRaises(HubError):
            billing.refresh('acct-1', 2026)
        self.assertEqual(self.store.inserts, 0)

    def test_daily_refresh_logs_hub_failures(self):
        self.frappe.db.exists = lambda doctype, filters: doctype == 'Relay Channel'
        with patch.object(billing, 'refresh', side_effect=HubError('down')) as refresh:
            billing.refresh_configured()
        self.assertEqual([call.args for call in refresh.call_args_list], [('acct-1', 2025), ('acct-1', 2026)])
        self.frappe.log_error.assert_called()
        self.frappe.db.rollback.assert_called()

    def test_get_billing_returns_months_categories_and_templates(self):
        self.frappe.get_list.return_value = ['CH-WA']
        self.frappe.get_all.side_effect = lambda doctype, **kwargs: (
            [_dict(period=date(2026, 3, 1), category='UTILITY', pricing_type='REGULAR', volume=5, meta_cost=1.0,
                   currency='INR', fetched_at='2026-10-26 10:00:00')] if doctype == billing.DOCTYPE
            else [_dict(template_name='order_ready', category='UTILITY')])
        with patch.object(billing, 'message_counts', return_value=({3: 9}, [('order_ready', 3, 4)])):
            result = billing.get_billing('acct-1', 2026)
        self.assertEqual((result['margin_percent'], result['currency']), (30.0, 'INR'))
        self.assertEqual(result['months'][2]['total'], 1.3)
        self.assertEqual(result['templates'], [{'template': 'order_ready', 'category': 'UTILITY', 'period': '2026-03-01', 'messages_sent': 4}])
        self.assertEqual(result['total']['messages_sent'], 9)


if __name__ == '__main__':
    unittest.main()
