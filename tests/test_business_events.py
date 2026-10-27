import json
import sys
import types
import unittest
from unittest.mock import Mock, patch
from test_ai_skills import Doc, framework, module


class BusinessEventTests(unittest.TestCase):
    def setUp(self):
        self.f = framework(); self.intents = []
        self.f.ValidationError = ValueError
        self.f.QueryDeadlockError = type('QueryDeadlockError', (Exception,), {})
        self.f.DoesNotExistError = LookupError
        self.f.TimestampMismatchError = type('TimestampMismatchError',(ValueError,),{})
        self.f.cache = Mock()
        self.f.cache.get_value.return_value = {('Delivery Note', 'on_submit')}
        automation = types.SimpleNamespace(internal_save=lambda doc, **kw: self.intents.append(doc))
        tools = module('relay_core/ai/tools.py', self.f)
        self.service = module('relay_core/business_events.py', self.f,
            {'relay_core.ai.tools': tools, 'relay_core.automation.service': automation})
        self.service.snapshot_ownership = Mock()
        self.rule = Doc(name='RULE-1', modified='v1', recipient_field='customer', business_doctype='Customer',
            parameter_mapping='["name", "items_summary"]', source_doctype='Delivery Note', template='TPL-1', channel='CH-1')
        self.source = Doc(doctype='Delivery Note', name='DN-1', customer='CUST-A',
            items=[Doc(item_name='Cloth', qty=12, uom='Metre')])
        self.f.get_meta.return_value = Doc(get_field=lambda key: Doc(fieldtype='Table') if key == 'items' else None)
        self.service.approved = Mock(return_value=Doc(template_name='delivery_notice', language='en'))
        self.f.get_all.return_value = ['PERSON-A']
        self.f.get_doc.side_effect = lambda values: Doc(values, name='DELIVERY-1')
        self.f.db.get_value.side_effect = lambda dt, *args, **kwargs: 'WhatsApp' if dt == 'Relay Channel' else (1 if dt == 'User' else None)
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
                self.f.cache.set_value.assert_called_with(self.service.RULE_PAIRS_CACHE_KEY, pairs, expires_in_sec=60)
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

    def test_rule_failures_roll_back_and_log_without_failing_the_business_transaction(self):
        self.f.get_all.return_value = ['RULE-1']
        for error in (ValueError('Invalid template'), KeyError('payload'), TypeError('bad value')):
            with self.subTest(error=error):
                self.f.db.rollback.reset_mock(); self.f.log_error.reset_mock()
                self.f.get_doc.side_effect = error
                self.service.on_event(self.source, 'on_submit')
                self.f.db.rollback.assert_called_once_with(save_point='relay_business_event')
                self.f.log_error.assert_called_once()
                self.f.db.commit.assert_not_called()
                self.assertFalse(self.f.flags.relay_business_event)
        self.f.log_error.reset_mock()
        self.f.get_all.side_effect = RuntimeError('Missing table')
        self.service.on_event(self.source, 'on_submit')
        self.f.log_error.assert_called_once()
        self.f.get_all.side_effect = None
        self.f.log_error.side_effect = RuntimeError('Log failure')
        with self.assertRaises(RuntimeError): self.service.on_event(self.source, 'on_submit')

    def test_deadlock_and_savepoint_failure_escape_without_partial_success(self):
        self.f.get_all.return_value=['RULE-1']
        self.f.get_doc.side_effect=None
        self.f.get_doc.return_value=self.rule
        for where in ('get_all','capture'):
            with self.subTest(where=where):
                with patch.object(self.f if where=='get_all' else self.service,where,side_effect=self.f.QueryDeadlockError):
                    with self.assertRaises(self.f.QueryDeadlockError):self.service.on_event(self.source,'on_submit')
                self.assertFalse(self.f.flags.relay_business_event)
        self.f.get_doc.side_effect=ValueError('invalid rule')
        self.f.db.rollback.side_effect=RuntimeError('Savepoint no longer exists')
        with self.assertRaises(RuntimeError):self.service.on_event(self.source,'on_submit')

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
        self.f.db.after_commit.add.call_args.args[0]()
        self.assertEqual(self.intents[0].status, 'Pending')

    def test_failed_permission_recheck_cannot_send(self):
        self.service.capture(self.rule, self.source, 'on_submit')
        delivery = self.intents[0]
        self.rule.update(enabled=1, run_as_user='service', channel='CH-1')
        self.source.denied = True
        self.f.get_doc.side_effect = lambda dt, name: {'Relay Business Event Delivery': delivery,
            'Relay Business Event Rule': self.rule, 'Delivery Note': self.source}[dt]
        self.f.db.get_value.side_effect = None
        self.f.db.get_value.return_value = None
        send = Mock()
        with patch.dict(sys.modules, {'relay_core.conversation_start': types.SimpleNamespace(send_business=send)}):
            self.service.dispatch(delivery.name)
        send.assert_not_called()
        self.assertEqual(delivery.status, 'Failed')

    def test_unexpected_failure_before_journaling_leaves_a_recoverable_intent(self):
        self.service.capture(self.rule,self.source,'on_submit')
        delivery = self.intents[0]
        self.rule.update(enabled=1,run_as_user='service',channel='CH-1')
        self.f.get_doc.side_effect = lambda dt,name:delivery if dt=='Relay Business Event Delivery' else self.rule
        for error in (RuntimeError, self.f.TimestampMismatchError):
            self.service.delivery_scope = Mock(side_effect=error('Transient database failure'))
            self.service.dispatch(delivery.name)
            self.assertEqual(delivery.status,'Pending')
            self.assertIsNone(delivery.action)

    def test_delivery_deadlock_reaches_whole_transaction_retry(self):
        self.rule.update(enabled=1,run_as_user='service',channel='CH-1')
        self.service.capture(self.rule,self.source,'on_submit')
        delivery = self.intents[0]
        self.f.get_doc.side_effect = lambda dt,name:delivery if dt=='Relay Business Event Delivery' else self.rule
        self.service.delivery_scope=Mock(side_effect=self.f.QueryDeadlockError)
        with self.assertRaises(self.f.QueryDeadlockError):self.service.dispatch.__wrapped__(delivery.name)
        self.assertEqual(delivery.status,'Pending')
        self.f.db.set_value.assert_not_called()

    def test_missing_rules_fail_and_do_not_starve_later_pending_deliveries(self):
        rows = [Doc(name=f'DELIVERY-{i}', rule='deleted', status='Pending') for i in range(21)]
        def get_doc(dt, name):
            if dt == 'Relay Business Event Rule':
                raise self.f.DoesNotExistError('Deleted rule')
            return next(row for row in rows if row.name == name)
        self.f.get_doc.side_effect = get_doc
        self.f.get_all.side_effect = lambda *a, **kw: [row.name for row in rows if row.status == 'Pending'][:20]
        self.f.qb = Mock()
        query = self.f.qb.from_.return_value.join.return_value.on.return_value.select.return_value
        query.where.return_value.where.return_value.limit.return_value.run.return_value = []
        self.service.enqueue_delivery = self.service.dispatch
        self.service.recover()
        self.assertEqual([row.status for row in rows], ['Failed'] * 20 + ['Pending'])
        self.service.recover()
        self.assertTrue(all(row.status == 'Failed' for row in rows))
        self.f.db.get_value.assert_any_call('Relay Business Event Delivery', 'DELIVERY-20', 'name', for_update=True)

class ChannelEventTests(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.tools = module('relay_core/ai/tools.py',self.f)
        self.service = module('relay_core/business_events.py',self.f,
            {'relay_core.ai.tools':self.tools,'relay_core.automation.service':types.SimpleNamespace(internal_save=Mock())})
        self.rule = Doc(name='RULE',enabled=1,modified='v1',channel='TG',run_as_user='worker',business_doctype='Customer',
            source_doctype='Sales Order',recipient_field='customer',parameter_mapping='["name", "total_qty"]',
            template=None,telegram_body='Order {name}: {total_qty}',email_subject='Order {name}',email_body='Qty {total_qty}',
            email_signature='Local <Support>',use_preferences=1)
        self.source = Doc(name='SO-1',customer='C1',total_qty=25)
        self.selection = dict(channel='TG',endpoint='END1',preference='P1',provider='Telegram')
        self.resolve = Mock(return_value=self.selection)
        self.recheck = Mock()
        self.f.get_meta.return_value = Doc(get_field=lambda key:Doc(fieldtype='Data'),
            get_permitted_fieldnames=lambda **kw:['name','total_qty'])
        self.patch = patch.dict(sys.modules,{'relay_core.channel_preferences':types.SimpleNamespace(resolve=self.resolve,recheck=self.recheck)})
        self.patch.start();self.addCleanup(self.patch.stop)

    def test_telegram_snapshot_has_explicit_preference_and_immutable_values(self):
        payload = self.service.snapshot(self.rule,self.source,'PERSON','C1')
        self.assertEqual(payload['data'],{'text':'Order SO-1: 25'})
        self.assertEqual(payload['selection'],self.selection)
        self.source.total_qty = 99
        self.service.readable_parameters(self.rule,self.source,json.dumps(payload))
        self.assertEqual(payload['data']['text'],'Order SO-1: 25')
        self.resolve.assert_called_once_with('PERSON','Customer','C1',channels=None,providers=['Telegram','Email'])

    def test_email_snapshot_renders_safe_html_and_no_business_field_read_bypass(self):
        self.selection.update(provider='Email',channel='EM')
        payload = self.service.snapshot(self.rule,self.source,'PERSON','C1')
        self.assertEqual(payload['data']['subject'],'Order SO-1')
        self.assertIn('Local &lt;Support&gt;',payload['data']['html'])
        self.f.get_meta.return_value.get_permitted_fieldnames = lambda **kw:['name']
        with self.assertRaisesRegex(ValueError,'readable'):
            self.service.snapshot(self.rule,self.source,'PERSON','C1')

    def test_delivery_rechecks_original_consent_without_selecting_another_channel(self):
        payload = self.service.snapshot(self.rule,self.source,'PERSON','C1')
        delivery = Doc(rule='RULE',rule_version='v1',payload=json.dumps(payload),source_doctype='Sales Order',
            source_name='SO-1',business_doctype='Customer',business_name='C1',contact='PERSON')
        self.f.get_doc.side_effect = lambda dt,name:self.rule if dt=='Relay Business Event Rule' else self.source
        self.resolve.reset_mock()
        self.service.delivery_scope(delivery)
        self.recheck.assert_called_once_with('PERSON','Customer','C1',self.selection)
        self.resolve.assert_not_called()
        self.recheck.side_effect = ValueError('Consent revoked')
        with self.assertRaisesRegex(ValueError,'Consent revoked'):self.service.delivery_scope(delivery)

    def test_mutated_snapshot_is_rejected_and_email_action_keys_match_email_journal(self):
        import hashlib
        payload = self.service.snapshot(self.rule,self.source,'PERSON','C1')
        digest = hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        delivery = Doc(rule='RULE',rule_version='v1',event_key='EVENT',payload_hash=digest)
        payload['data']['text']='Changed';delivery.payload=json.dumps(payload)
        self.f.get_doc.return_value=self.rule
        with self.assertRaisesRegex(ValueError,'content changed'):self.service.delivery_scope(delivery)
        delivery.payload=json.dumps(dict(kind='email'))
        self.assertEqual(self.service.action_key(delivery,self.rule),hashlib.sha256(b'email:worker:EVENT').hexdigest())

    def test_callback_completion_is_monotonic_and_unrelated_actions_do_no_database_work(self):
        action = Doc(name='ACTION',payload=json.dumps({'business_event':'EVENT'}),status='Submitted')
        self.f.db.get_value.return_value='Queued'
        self.service.complete(action)
        self.f.db.set_value.assert_called_once_with('Relay Business Event Delivery','EVENT',
            {'status':'Submitted','action':'ACTION'})
        self.f.db.reset_mock()
        self.f.db.get_value.return_value='Submitted';action.status='Rejected'
        self.service.complete(action)
        self.f.db.set_value.assert_not_called()
        self.f.db.reset_mock();action.payload='{}'
        self.service.complete(action)
        self.assertEqual(self.f.db.mock_calls,[])


class RemoveSamplesPatchTests(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.f.LinkExistsError = type('LinkExistsError', (Exception,), {})
        self.f.delete_doc = Mock()
        self.patch = module('relay_core/patches/v1_0/remove_untouched_samples.py', self.f)

    def test_deletes_only_untouched_disabled_samples(self):
        rows = {'Delivery Note': [Doc(name='DN-SAMPLE', creation=1, modified=1), Doc(name='DN-EDITED', creation=1, modified=2)],
                'Sales Order': [Doc(name='SO-LINKED', creation=1, modified=1)],
                'supplier_ledger': [Doc(name='SKILL-SAMPLE', creation=1, modified=1)]}
        self.f.get_all.side_effect = lambda doctype, filters, fields: rows[filters['sample_key']]
        def delete(doctype, name, **kw):
            if name == 'SO-LINKED': raise self.f.LinkExistsError()
        self.f.delete_doc.side_effect = delete
        self.patch.execute()
        for call in self.f.get_all.call_args_list:
            self.assertEqual(call.kwargs['filters']['enabled'], 0)
            self.assertIn('title', call.kwargs['filters'])
        deleted = [call.args for call in self.f.delete_doc.call_args_list]
        self.assertEqual(deleted, [('Relay Business Event Rule', 'DN-SAMPLE'), ('Relay Business Event Rule', 'SO-LINKED'),
                                   ('Relay AI Skill', 'SKILL-SAMPLE')])
