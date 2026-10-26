"""WhatsApp billing: Meta pricing parsing, idempotent month rows, billed rates, totals and access."""
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

    def test_only_system_managers_read_and_save_the_margin(self):
        settings = Mock(whatsapp_margin_percent=30)
        self.frappe.get_single.return_value = settings
        with self.assertRaises(frappe.PermissionError):
            billing.get_margin()
        with self.assertRaises(frappe.PermissionError):
            billing.save_margin('25')
        settings.save.assert_not_called()
        self.roles = ['System Manager']
        self.assertEqual(billing.get_margin(), {'margin_percent': 30.0})
        self.sql.return_value = [('25',)]
        self.assertEqual(billing.save_margin('25'), {'margin_percent': 25.0})
        self.assertEqual(settings.whatsapp_margin_percent, 25.0)
        settings.save.assert_called_once()
        with self.assertRaisesRegex(frappe.ValidationError, 'must be a number'):
            billing.save_margin('ten')
        self.roles = ['WhatsApp User']
        with self.assertRaises(frappe.PermissionError):
            billing.get_margin()

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

    def test_billed_rate_adds_the_service_charge_to_the_meta_rate(self):
        self.assertEqual(billing.billed_rate(10, 2.5, 30), 0.325)
        self.assertEqual(billing.billed_rate(3, 1, 30), 0.4333)
        self.assertEqual(billing.billed_rate(0, 0, 30), 0.0)
        self.assertEqual(billing.billed_rate(5, 0, 30), 0.0)
        self.assertEqual(billing.bill_line('UTILITY', 1231, 141.565, 30),
                         {'category': 'UTILITY', 'messages': 1231, 'rate': 0.1495, 'amount': 184.03})

    def test_months_and_year_total_the_billed_lines(self):
        row = lambda month, category, pricing_type, volume, cost: _dict(
            period=date(2026, month, 1), category=category, pricing_type=pricing_type, volume=volume, meta_cost=cost)
        rows = [row(2, 'SERVICE', 'FREE_CUSTOMER_SERVICE', 20, 0), row(2, 'MARKETING', 'REGULAR', 10, 2.5),
                row(2, 'UTILITY', 'FREE_ENTRY_POINT', 3, 0), row(2, 'UTILITY', 'REGULAR', 4, 0.4),
                row(3, 'MARKETING', 'REGULAR', 30, 9.0)]
        months, total = billing.summarise(2026, rows, 30)
        self.assertEqual(len(months), 12)
        self.assertEqual(months[0], {'period': '2026-01-01', 'lines': [], 'messages': 0, 'amount': 0})
        self.assertEqual(months[1]['lines'], [
            {'category': 'MARKETING', 'messages': 10, 'rate': 0.325, 'amount': 3.25},
            {'category': 'UTILITY', 'messages': 4, 'rate': 0.13, 'amount': 0.52},
            {'category': 'SERVICE', 'messages': 23, 'rate': 0.0, 'amount': 0.0}])
        self.assertEqual((months[1]['messages'], months[1]['amount']), (37, 3.77))
        self.assertEqual((months[2]['messages'], months[2]['amount']), (30, 11.7))
        self.assertEqual((total['messages'], total['amount']), (67, 15.47))
        self.assertEqual(total['lines'][0], {'category': 'MARKETING', 'messages': 40, 'amount': 14.95, 'rate': 0.3737})
        self.assertEqual(total['lines'][-1]['category'], 'SERVICE')

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
        hub.execute.return_value['currency'] = 'INR'
        with client, patch.object(billing, 'year_bounds', return_value=(100, 200)):
            self.assertEqual(billing.refresh('acct-1', '2026'), {'rows': 2, 'data_points': 2})
        hub.execute.assert_called_once_with({'operation': 'billing.pricing', 'start': 100, 'end': 200, 'granularity': 'MONTHLY',
                                             'dimensions': ['PRICING_CATEGORY', 'PRICING_TYPE']})
        self.assertEqual(self.store.inserts, 2)
        self.assertEqual({row['currency'] for row in self.store.rows.values()}, {'INR'})

    def test_a_point_currency_wins_and_an_older_hub_leaves_it_empty(self):
        self.assertEqual(billing.parse([dict(self.point(), currency='USD')], 'INR')[(date(2026, 2, 1), 'MARKETING', 'REGULAR')]['currency'], 'USD')
        client, hub = self.hub([self.point()])
        with client, patch.object(billing, 'year_bounds', return_value=(100, 200)):
            billing.refresh('acct-1', 2026)
        self.assertEqual({row['currency'] for row in self.store.rows.values()}, {''})

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

    def billing_for(self, roles):
        self.roles = roles
        self.frappe.get_roles = lambda user=None: self.roles
        self.frappe.get_list.return_value = ['CH-WA']
        self.frappe.get_all.side_effect = lambda doctype, **kwargs: (
            [_dict(period=date(2026, 3, 1), category='UTILITY', pricing_type='REGULAR', volume=5, meta_cost=1.0,
                   currency='INR', fetched_at='2026-10-26 10:00:00', raw_data='[{"cost": 1}]')] if doctype == billing.DOCTYPE
            else [_dict(template_name='order_ready', category='UTILITY')])
        with patch.object(billing, 'template_counts', return_value=[('order_ready', 3, 4)]):
            return billing.get_billing('acct-1', 2026)

    def test_get_billing_returns_the_bill_and_template_counts(self):
        result = self.billing_for(['WhatsApp Manager'])
        self.assertEqual(result['currency'], 'INR')
        self.assertEqual(result['months'][2]['lines'], [{'category': 'UTILITY', 'messages': 5, 'rate': 0.26, 'amount': 1.3}])
        self.assertEqual((result['total']['messages'], result['total']['amount']), (5, 1.3))
        self.assertEqual(result['templates'], [{'template': 'order_ready', 'category': 'UTILITY', 'period': '2026-03-01', 'messages': 4}])

    def test_the_bill_never_shows_meta_cost_or_the_service_charge_to_managers(self):
        def keys(value):
            if isinstance(value, dict):
                return set(value) | {key for item in value.values() for key in keys(item)}
            if isinstance(value, list):
                return {key for item in value for key in keys(item)}
            return set()
        leaked = {'internal', 'meta_cost', 'margin_percent', 'margin_amount', 'raw_data', 'pricing_type'}
        self.assertFalse(keys(self.billing_for(['WhatsApp Manager'])) & leaked)
        self.assertFalse(keys(self.billing_for(['Relay Communication Manager'])) & leaked)
        internal = self.billing_for(['System Manager'])['internal']
        self.assertEqual((internal['margin_percent'], internal['meta_cost'], internal['margin_amount']), (30.0, 1.0, 0.3))
        self.assertEqual(internal['months'][2], {'period': '2026-03-01', 'meta_cost': 1.0, 'margin_amount': 0.3})

if __name__ == '__main__':
    unittest.main()
