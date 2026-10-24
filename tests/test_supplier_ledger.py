"""Code-owned arithmetic, truncation, sample installation and tool scoping."""
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch
from test_ai_skills import Doc, framework, module
import test_ai_skills
from relay_core.ai.ledger import summarize, reply


class LedgerTests(unittest.TestCase):
    def test_decimal_totals_partial_note_and_bounded_reply(self):
        rows = [dict(company='Local Company', posting_date='2026-10-01', voucher_type='Journal Entry', voucher_no='SIM-1', debit=.1, credit=0, remarks='fixture'),
                dict(company='Local Company', posting_date='2026-10-02', voucher_type='Journal Entry', voucher_no='SIM-2', debit=.2, credit=.05, remarks='fixture')]
        result = summarize(rows, False)
        self.assertEqual(result['totals'], dict(debit='0.3', credit='0.05', net_debit='0.25'))
        self.assertIn('not an opening or closing balance', reply(result))
        partial = summarize(rows, True)
        self.assertIn('Partial totals', reply(partial))
        self.assertEqual(partial['totals'], result['totals'])
        rows[0]['remarks'] = 'x' * 3000
        self.assertLessEqual(len(reply(summarize(rows, False))), 2000)
        self.assertIn('omitted', reply(summarize(rows, False)))

    def test_non_finite_amounts_are_rejected(self):
        for value in ('NaN', 'Infinity', '-Infinity'):
            with self.assertRaises(ValueError): summarize([dict(company='Local Company', debit=value, credit=0)], False)

    def test_installer_is_disabled_idempotent_and_preserves_existing_sample(self):
        f = framework()
        f.db.exists.side_effect = lambda dt, name: dt == 'DocType'
        sample = module('relay_core/ai/samples.py', f)
        sample.install_samples()
        values = f.get_doc.call_args.args[0]
        self.assertEqual(values['enabled'], 0)
        self.assertEqual(values['mode'], 'Shadow')
        self.assertNotIn('ai_model', values)
        self.assertEqual(json.loads(values['allowed_tools']), [sample.LEDGER_TOOL])
        f.get_doc.reset_mock()
        f.db.exists.return_value = True
        f.db.exists.side_effect = None
        sample.install_samples()
        f.get_doc.assert_not_called()


class LedgerContractTests(unittest.TestCase):
    def setUp(self):
        test_ai_skills.ScopedToolTests.setUp(self)
        self.contract.update(doctype='GL Entry', fields=['name', 'company', 'debit', 'credit', 'posting_date'])
        self.skill.allowed_tools = json.dumps([self.contract])
        for row in self.records:
            row.debit, row.credit, row.is_cancelled, row.company = row.amount, 0, 0, 'Local Company'
        self.records.append(Doc(name='LED-4', company='Local Company', party='SUP-A', party_type='Supplier', debit=50, credit=10, is_cancelled=0))
        fields = {'company': Doc(fieldtype='Link'), 'party': Doc(fieldtype='Dynamic Link', options='party_type'),
            'debit': Doc(fieldtype='Currency'), 'credit': Doc(fieldtype='Currency'), 'posting_date': Doc(fieldtype='Date')}
        meta = Doc(get_field=lambda key: fields.get(key))
        shared = types.SimpleNamespace(get_readable_meta=lambda dt: meta, is_sensitive_field=lambda name: False,
            get_readable_columns=lambda meta: {'name', *fields})
        self.patch.stop()
        self.patch = patch.dict(sys.modules, {'frappe_tools.ai.tools': shared})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        listing = self.f.get_list.side_effect
        self.f.get_list.side_effect = lambda dt, filters, **kw: listing(dt, filters, **kw)[:kw['page_length']]

    def test_gl_contract_fetches_extra_row_and_totals_only_returned_supplier_rows(self):
        result = self.reader.read(self.contract, limit=1)
        self.assertEqual(result['totals'], dict(debit='1250', credit='0', net_debit='1250'))
        self.assertTrue(result['truncated'])
        self.assertEqual([row['name'] for row in result['rows']], ['LED-1'])
        self.assertEqual(self.f.get_list.call_args.kwargs['page_length'], 2)
        self.assertEqual(self.f.get_list.call_args.kwargs['filters'], {'party': 'SUP-A', 'party_type': 'Supplier', 'is_cancelled': 0})
        self.assertEqual(self.reader.ledger_results, [result])
        self.assertEqual(len(self.reader.evidence), 1)

    def test_cancelled_rows_do_not_consume_limit_or_inflate_totals_or_truncation(self):
        self.records[0].is_cancelled = 1  # Previously contributed 1,250 before the limit.
        result = self.reader.read(self.contract, limit=1)
        self.assertEqual([row['name'] for row in result['rows']], ['LED-4'])
        self.assertEqual(result['totals'], dict(debit='50', credit='10', net_debit='40'))
        self.assertFalse(result['truncated'])
        self.records.append(Doc(name='LED-5', company='Local Company', party='SUP-A', party_type='Supplier', debit=100, credit=0, is_cancelled=0))
        partial = self.reader.read(self.contract, limit=1)
        self.assertTrue(partial['truncated'])
        self.assertEqual(partial['totals'], result['totals'])
        self.assertIn('Partial totals', reply(partial))

    def test_old_persisted_contract_gets_permission_checked_company(self):
        self.contract['fields'].remove('company')
        self.skill.allowed_tools = json.dumps([self.contract])
        result = self.reader.read(self.contract, limit=1)
        self.assertEqual(result['totals']['debit'], '1250')
        self.assertEqual(result['rows'][0]['company'], 'Local Company')
        self.assertNotIn('company', json.loads(self.skill.allowed_tools)[0]['fields'])
        shared = sys.modules['frappe_tools.ai.tools']
        with patch.object(shared, 'get_readable_columns', return_value=set(self.contract['fields'])):
            with self.assertRaises(ValueError): self.reader.read(self.contract)

    def test_model_cannot_include_cancelled_entries(self):
        self.contract['fields'].append('is_cancelled')
        self.skill.allowed_tools = json.dumps([self.contract])
        shared = sys.modules['frappe_tools.ai.tools']
        original = shared.get_readable_meta('GL Entry').get_field
        with patch.object(shared, 'get_readable_meta', return_value=Doc(get_field=lambda key: Doc(fieldtype='Check') if key == 'is_cancelled' else original(key))), \
                patch.object(shared, 'get_readable_columns', return_value=set(self.contract['fields'])):
            with self.assertRaises(ValueError):
                self.reader.read(self.contract, filters={'is_cancelled': '1'})
        self.f.get_list.assert_not_called()


class DisabledSkillTests(unittest.TestCase):
    def test_disabled_sample_can_be_saved_without_operational_configuration(self):
        f = framework()
        tools = types.SimpleNamespace(contracts=Mock(), as_user=Mock(side_effect=AssertionError('No identity configured')))
        require = Mock()
        with patch.dict(sys.modules, {'relay_core.permissions': types.SimpleNamespace(require_access=require), 'relay_core.ai.tools': tools}):
            config = module('relay_core/ai/configuration.py', f)
            config.validate_skill(Doc(instructions='Supplier support', daily_limit=100, mode='Shadow', enabled=0))
        tools.contracts.assert_called_once()
        f.get_doc.assert_not_called()
