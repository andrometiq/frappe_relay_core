"""Code-owned arithmetic, truncation and tool scoping."""
import sys
import types
import unittest
from unittest.mock import Mock, patch
from test_ai_skills import Doc, framework, module
import test_ai_skills
from relay_core.ai.ledger import render, supplier, totals


ROWS = [dict(posting_date='2026-10-01', voucher_type='Journal Entry', voucher_no='SIM-1', debit=.1, credit=0),
        dict(posting_date='2026-10-02', voucher_type='Journal Entry', voucher_no='SIM-2', debit=.2, credit=.05)]


class LedgerTests(unittest.TestCase):
    def test_decimal_totals_partial_note_and_bounded_reply(self):
        rows = [dict(row) for row in ROWS]
        self.assertEqual(totals(rows), dict(debit='0.3', credit='0.05', net_debit='0.25'))
        self.assertIn('not an opening or closing balance', render(rows, 'English', False))
        self.assertIn('Partial totals', render(rows, 'English', True))
        self.assertTrue(render(rows, 'English', False).startswith('Customer ledger'))
        self.assertTrue(supplier(rows, 'English', False).startswith('Supplier ledger'))
        many = [dict(rows[0], voucher_no='SIM-' + 'x' * 120) for _ in range(20)]
        self.assertLessEqual(len(render(many, 'English', False)), 1850)
        self.assertIn('omitted', render(many, 'English', False))
        self.assertLessEqual(len(render(many, 'Tamil', False)), 1850)

    def test_remarks_appear_only_when_the_pack_shows_them(self):
        self.assertNotIn('fixture', render(ROWS, 'English', False))
        self.assertIn('fixture', render([dict(row, remarks='fixture') for row in ROWS], 'English', False))

    def test_non_finite_amounts_are_rejected(self):
        for value in ('NaN', 'Infinity', '-Infinity'):
            with self.assertRaises(ValueError): totals([dict(debit=value, credit=0)])


class LedgerContractTests(unittest.TestCase):
    def setUp(self):
        test_ai_skills.ScopedToolTests.setUp(self)
        self.contract.update(doctype='GL Entry', fields=[dict(name=name, model=True, customer=True)
            for name in ('name', 'company', 'debit', 'credit', 'posting_date')], limit=1)
        self.contract['scope']['fixed'] = {'party_type': 'Supplier', 'is_cancelled': 0}
        for row in self.records:
            row.debit, row.credit, row.is_cancelled = row.amount, 0, 0
        self.records.append(Doc(name='LED-5', company='Sim Company', party='SUP-A', party_type='Supplier', debit=50, credit=10, is_cancelled=0))
        fields = {'company': Doc(fieldtype='Link', options='Company'), 'phone': Doc(fieldtype='Data'),
            'party_type': Doc(fieldtype='Link', options='DocType'), 'is_cancelled': Doc(fieldtype='Check'), 'party': Doc(fieldtype='Dynamic Link', options='party_type'),
            'debit': Doc(fieldtype='Currency'), 'credit': Doc(fieldtype='Currency'), 'posting_date': Doc(fieldtype='Date')}
        meta = Doc(get_field=lambda key: fields.get(key))
        shared = types.SimpleNamespace(get_readable_meta=lambda dt: meta, is_sensitive_field=lambda name: False,
            get_readable_columns=lambda meta: {'name', *fields})
        extra = patch.dict(sys.modules, {'frappe_tools.ai.tools': shared})
        extra.start(); self.addCleanup(extra.stop)
        listing = self.f.get_list.side_effect
        self.f.get_list.side_effect = lambda dt, filters, **kw: listing(dt, filters, **kw)[:kw['page_length']]

    def test_gl_contract_fetches_extra_row_to_report_truncation(self):
        result = self.reader.read(self.contract)
        self.assertTrue(result['truncated'])
        self.assertEqual([row['name'] for row in result['rows']], ['LED-1'])
        self.assertEqual(self.f.get_list.call_args_list[0].kwargs['page_length'], 2)
        self.assertEqual(self.f.get_list.call_args_list[0].kwargs['filters'], {'party': 'SUP-A', 'party_type': 'Supplier', 'is_cancelled': 0, 'company': 'Sim Company'})
        self.assertEqual(self.reader.results['erpnext.ledger'], result)
        self.assertEqual(len(self.reader.evidence), 1)

    def test_cancelled_rows_do_not_consume_limit_or_inflate_totals_or_truncation(self):
        self.records[0].is_cancelled = 1  # Previously contributed 1,250 before the limit.
        result = self.reader.read(self.contract)
        self.assertEqual([row['name'] for row in result['rows']], ['LED-5'])
        self.assertEqual(totals(result['rows']), dict(debit='50', credit='10', net_debit='40'))
        self.assertFalse(result['truncated'])
        self.records.append(Doc(name='LED-6', company='Sim Company', party='SUP-A', party_type='Supplier', debit=100, credit=0, is_cancelled=0))
        partial = self.reader.read(self.contract)
        self.assertTrue(partial['truncated'])
        self.assertIn('Partial totals', render(partial['rows'], 'English', partial['truncated']))

    def test_model_cannot_include_cancelled_entries(self):
        self.contract['filters'] = {'is_cancelled': {'type': 'number', 'operators': ['=']}}
        with self.assertRaises(ValueError):
            self.reader.read(self.contract, filters={'is_cancelled': 1})
        self.f.get_list.assert_not_called()


class DisabledSkillTests(unittest.TestCase):
    def test_disabled_sample_can_be_saved_without_operational_configuration(self):
        f = framework()
        tools = types.SimpleNamespace(contracts=Mock(), is_company_scoped=Mock(), as_user=Mock(side_effect=AssertionError('No identity configured')))
        require = Mock()
        with patch.dict(sys.modules, {'relay_core.permissions': types.SimpleNamespace(require_access=require), 'relay_core.ai.tools': tools}):
            config = module('relay_core/ai/configuration.py', f)
            config.validate_skill(Doc(instructions='Supplier support', daily_limit=100, mode='Shadow', enabled=0))
        tools.contracts.assert_called_once()
        f.get_doc.assert_not_called()
