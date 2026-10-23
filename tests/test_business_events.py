import json
import sys
import types
import unittest
from unittest.mock import Mock, patch
from test_ai_skills import Doc, framework, module


class BusinessEventTests(unittest.TestCase):
    def setUp(self):
        self.f = framework(); self.intents = []
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
        self.assertEqual(len(samples), 2)
        self.assertTrue(all(not row.enabled for row in samples))
        self.assertEqual({row.source_doctype for row in samples}, {'Delivery Note', 'Sales Order'})
