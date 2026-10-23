import json
import sys
import types
import unittest
from unittest.mock import Mock, patch
from test_ai_skills import Doc, framework, module


class BusinessEventTests(unittest.TestCase):
    def setUp(self):
        self.f = framework(); self.intents = []
        self.f.cache = Mock()
        self.f.cache.get_value.return_value = {('Delivery Note', 'on_submit')}
        automation = types.SimpleNamespace(internal_save=lambda doc, **kw: self.intents.append(doc))
        tools = module('relay_core/ai/tools.py', self.f)
        self.service = module('relay_core/business_events.py', self.f,
            {'relay_core.ai.tools': tools, 'relay_core.automation.service': automation})
        self.rule = Doc(name='RULE-1', modified='v1', recipient_field='customer', business_doctype='Customer',
            parameter_mapping='["name", "items_summary"]', source_doctype='Delivery Note', template='TPL-1')
        self.source = Doc(doctype='Delivery Note', name='DN-1', customer='CUST-A',
            items=[Doc(item_name='Cloth', qty=12, uom='Metre')])
        self.f.get_meta.return_value = Doc(get_field=lambda key: Doc(fieldtype='Table') if key == 'items' else None)
        self.service.approved = Mock(return_value=Doc(template_name='delivery_notice', language='en'))
        self.f.get_all.return_value = ['PERSON-A']
        self.f.get_doc.side_effect = lambda values: Doc(values, name='DELIVERY-1')
        self.f.db.exists.side_effect = lambda dt, filters: any(d.event_key == filters['event_key'] for d in self.intents)

    def test_preview_uses_template_permissions_and_paginated_hub_wording(self):
        self.service.require_access = Mock()
        template = Doc(account='sim-v1', template_id='2')
        self.f.get_doc.side_effect = None
        self.f.get_doc.return_value = template
        execute = Mock(side_effect=[{'data': [{'id': '1'}], 'paging': {'cursors': {'after': 'next'}}},
            {'data': [{'id': '2', 'components': [{'type': 'BODY', 'text': 'Order {{1}}'}]}]}])
        with patch.dict(sys.modules, {'relay_core.whatsapp': types.SimpleNamespace(execute=execute),
                'relay_core.settings': types.SimpleNamespace(value=lambda key: 'sim-v1')}):
            self.assertEqual(self.service.template_preview('TPL-1'), {'body': 'Order {{1}}'})
            self.assertEqual(execute.call_args.args, ('templates.list', {'after': 'next'}))
            template.account = 'other'
            with self.assertRaises(ValueError): self.service.template_preview('TPL-1')
            template.account, template.denied = 'sim-v1', True
            with self.assertRaises(PermissionError): self.service.template_preview('TPL-1')
        self.assertEqual(execute.call_count, 2)
        self.service.require_access.assert_called_with(configure=True)

    def test_missing_template_preview_fails_without_looping_on_repeated_cursor(self):
        self.service.require_access = Mock()
        self.f.get_doc.side_effect = None
        self.f.get_doc.return_value = Doc(account='sim-v1', template_id='2')
        execute = Mock(return_value={'data': [], 'paging': {'cursors': {'after': 'same'}}})
        with patch.dict(sys.modules, {'relay_core.whatsapp': types.SimpleNamespace(execute=execute),
                'relay_core.settings': types.SimpleNamespace(value=lambda key: 'sim-v1')}):
            with self.assertRaisesRegex(ValueError, 'unavailable'): self.service.template_preview('TPL-1')
        self.assertEqual(execute.call_count, 2)

    def test_unmatched_pair_never_queries_database(self):
        for pairs in (set(), {('Sales Order', 'on_submit')}, {('Delivery Note', 'on_cancel')}):
            with self.subTest(pairs=pairs), patch.object(self.f, 'get_all') as get_all, patch.object(self.f, 'db') as db:
                self.f.cache.get_value.return_value = pairs
                self.service.on_event(self.source, 'on_submit')
                get_all.assert_not_called()
                self.assertEqual(db.mock_calls, [])
                self.assertFalse(self.f.flags.relay_business_event)

    def test_cache_miss_builds_enabled_pairs_once_including_empty_set(self):
        for rows in ([], [Doc(source_doctype='Sales Order', event='on_submit')]):
            with self.subTest(rows=rows):
                self.f.cache.get_value.return_value = None
                self.f.get_all.reset_mock()
                self.f.get_all.return_value = rows
                self.service.on_event(self.source, 'on_submit')
                pairs = {(row.source_doctype, row.event) for row in rows}
                self.f.cache.set_value.assert_called_with(self.service.RULE_PAIRS_CACHE_KEY, pairs)
                self.f.cache.get_value.return_value = pairs
                self.service.on_event(self.source, 'on_submit')
                self.f.get_all.assert_called_once_with('Relay Business Event Rule',
                    filters={'enabled': 1}, fields=['source_doctype', 'event'])

    def test_matching_cached_pair_captures_event(self):
        self.f.get_all.return_value = ['RULE-1']
        self.f.get_doc.side_effect = None
        self.f.get_doc.return_value = self.rule
        self.service.capture = Mock()
        self.service.on_event(self.source, 'on_submit')
        self.service.capture.assert_called_once_with(self.rule, self.source, 'on_submit')

    def test_import_migration_install_and_patch_skip_all_work(self):
        for flag in ('in_import', 'in_migrate', 'in_install', 'in_patch'):
            with self.subTest(flag=flag), patch.dict(self.f.flags, {flag: True}):
                for event in self.service.EVENTS:
                    self.service.on_event(self.source, event)
        self.assertEqual(self.f.cache.mock_calls, [])
        self.f.get_all.assert_not_called()
        self.f.get_doc.assert_not_called()
        self.assertEqual(self.f.db.mock_calls, [])

    def test_rule_save_and_trash_clear_cache_immediately_and_after_commit(self):
        controller = module('relay_core/relay_core/doctype/relay_business_event_rule/relay_business_event_rule.py',
            self.f, {'frappe.model.document': types.SimpleNamespace(Document=Doc),
                     'relay_core.business_events': self.service})
        rule = controller.RelayBusinessEventRule()
        for hook in (rule.on_update, rule.on_trash):
            with self.subTest(hook=hook.__name__):
                self.f.cache.reset_mock()
                self.f.db.after_commit.add.reset_mock()
                hook()
                self.f.cache.delete_value.assert_called_once_with(self.service.RULE_PAIRS_CACHE_KEY)
                self.f.db.after_commit.add.assert_called_once()
                self.f.db.after_commit.add.call_args.args[0]()
                self.assertEqual(self.f.cache.delete_value.call_count, 2)

    def test_duplicate_event_has_one_after_commit_intent_with_qty_and_uom(self):
        for _ in range(2): self.service.capture(self.rule, self.source, 'on_submit')
        self.assertEqual(len(self.intents), 1)
        self.assertEqual(self.intents[0].business_name, 'CUST-A')
        payload = json.loads(self.intents[0].payload)
        self.assertEqual(payload['components'][0]['parameters'][1]['text'], 'Cloth: 12 Metre')
        self.f.enqueue.assert_not_called()
        self.f.db.after_commit.add.assert_called_once()
        self.f.db.after_commit.add.call_args.args[0]()
        self.f.enqueue.assert_called_once()
        self.f.db.commit.assert_not_called()

    def test_identity_distinguishes_event_site_rule_and_recipient(self):
        self.service.capture(self.rule, self.source, 'on_submit')
        self.service.capture(self.rule, self.source, 'on_cancel')
        self.f.local.site = 'second.local'; self.service.capture(self.rule, self.source, 'on_submit')
        self.rule.name = 'RULE-2'; self.service.capture(self.rule, self.source, 'on_submit')
        self.f.get_all.return_value = ['PERSON-B']; self.service.capture(self.rule, self.source, 'on_submit')
        self.assertEqual(len({row.event_key for row in self.intents}), 5)

    def test_event_failures_never_escape_business_transaction_even_logging_failure(self):
        self.f.get_all.return_value = ['RULE-1']; self.f.get_doc.side_effect = RuntimeError('Invalid template')
        self.f.log_error.side_effect = RuntimeError('Log failure')
        self.service.on_event(self.source, 'on_submit')
        self.f.db.rollback.assert_called_once_with(save_point='relay_business_event')
        self.f.db.commit.assert_not_called()
        self.assertFalse(self.f.flags.relay_business_event)
        self.f.get_all.side_effect = RuntimeError('Missing table')
        self.service.on_event(self.source, 'on_submit')

    def test_ambiguous_recipient_never_creates_delivery(self):
        self.f.get_all.return_value = ['PERSON-A', 'PERSON-B']
        with self.assertRaises(ValueError): self.service.capture(self.rule, self.source, 'on_submit')
        self.assertFalse(self.intents); self.f.enqueue.assert_not_called()

    def test_dispatch_uses_template_journal_with_original_business(self):
        self.service.capture(self.rule, self.source, 'on_submit')
        delivery = self.intents[0]; self.rule.update(enabled=1, run_as_user='service', channel='CH-1')
        self.f.get_doc.side_effect = lambda dt, name: {'Relay Business Event Delivery': delivery,
            'Relay Business Event Rule': self.rule, 'Delivery Note': self.source}[dt]
        self.service.readable_parameters = Mock()
        send = Mock(return_value={'status': 'Submitted', 'action': 'ACTION-1'})
        with patch.dict(sys.modules, {'relay_core.conversation_start': types.SimpleNamespace(send_business=send)}):
            self.service.dispatch(delivery.name)
        self.assertEqual(send.call_args.args[-2:], ('Customer', 'CUST-A'))
        self.assertEqual(send.call_args.args[2], 'template')
        self.assertEqual(delivery.action, 'ACTION-1')
        self.assertEqual(delivery.status, 'Submitted')


    def test_after_commit_queue_failure_is_recovered_without_raising(self):
        self.service.capture(self.rule, self.source, 'on_submit')
        self.f.enqueue.side_effect = RuntimeError('Redis unavailable')
        self.f.log_error.side_effect = RuntimeError('Logging unavailable')
        self.f.db.after_commit.add.call_args.args[0]()
        self.assertEqual(self.intents[0].status, 'Pending')

    def test_failed_permission_recheck_cannot_send(self):
        self.service.capture(self.rule, self.source, 'on_submit')
        delivery = self.intents[0]
        self.rule.update(enabled=1, run_as_user='service', channel='CH-1')
        self.source.denied = True
        self.f.get_doc.side_effect = lambda dt, name: {'Relay Business Event Delivery': delivery,
            'Relay Business Event Rule': self.rule, 'Delivery Note': self.source}[dt]
        self.f.db.get_value.return_value = None
        send = Mock()
        with patch.dict(sys.modules, {'relay_core.conversation_start': types.SimpleNamespace(send_business=send)}):
            self.service.dispatch(delivery.name)
        send.assert_not_called()
        self.assertEqual(delivery.status, 'Failed')

    def test_samples_are_disabled_and_install_idempotently(self):
        samples = []
        self.f.db.exists.side_effect = lambda dt, key: dt == 'DocType' or any(row.sample_key == key['sample_key'] for row in samples)
        self.f.get_doc.side_effect = lambda values: samples.append(Doc(values)) or samples[-1]
        for _ in range(2): self.service.install_samples()
        self.assertEqual(self.f.cache.delete_value.call_count, 2)
        self.f.cache.delete_value.assert_called_with(self.service.RULE_PAIRS_CACHE_KEY)
        self.assertEqual(len(samples), 2)
        self.assertTrue(all(not row.enabled for row in samples))
        self.assertEqual({row.source_doctype for row in samples}, {'Delivery Note', 'Sales Order'})
