"""Skill boundary tests with two businesses, real tool dispatch and a fake model."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

# Load native framework dependencies outside temporary sys.modules replacements.
try:
    import frappe.utils
    import relay_core.automation.queue
except ImportError:
    pass


class Doc(dict):
    def __getattr__(self, key): return self.get(key)
    def __setattr__(self, key, value): self[key] = value
    def check_permission(self, *args):
        if self.get('denied'): raise PermissionError('private record')
    def apply_fieldlevel_read_permissions(self): pass
    def save(self, **kw): return self
    def insert(self, **kw): return self
    def reload(self): return self


def module(path, f, extra=None):
    spec = importlib.util.spec_from_file_location('tested_' + path.replace('/', '_'), Path(path))
    result = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'frappe': f, **(extra or {})}): spec.loader.exec_module(result)
    return result


def framework():
    f = types.SimpleNamespace(session=Doc(user='operator'), flags=Doc(), local=Doc(site='test.local'),
        whitelist=lambda **kw: lambda fn: fn, db=Mock(), get_doc=Mock(), get_all=Mock(), get_list=Mock(),
        get_meta=Mock(), get_roles=Mock(return_value=['System Manager']),
        enqueue=Mock(), log_error=Mock(), PermissionError=PermissionError)
    f.set_user = lambda user: setattr(f.session, 'user', user)
    f.db.get_value.return_value = 1
    return f


class ScopedToolTests(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.tools = module('relay_core/ai/tools.py', self.f)
        self.contract = dict(name='ledger', method='get_list', doctype='Payment Ledger Entry',
            fields=['name', 'party', 'amount', 'posting_date'], scope_field='party',
            identity_anchor='Supplier', identity_fields={'WhatsApp': 'phone'}, company_field='company')
        self.skill = Doc(enabled=1, business_doctype='Supplier', allowed_tools=json.dumps([self.contract]))
        self.records = [Doc(name='LED-1', party='SUP-A', party_type='Supplier', amount=1250, posting_date='2026-10-01'),
                        Doc(name='LED-2', party='SUP-B', party_type='Supplier', amount=4500, posting_date='2026-10-02'),
                        Doc(name='LED-3', party='SUP-A', party_type='Customer', amount=900, posting_date='2026-10-03')]
        for record in self.records: record.company = 'Sim Company'
        self.records.append(Doc(self.records[0], name='LED-4', company='Sim Other Company', amount=7500))
        self.anchor = Doc(name='SUP-A', phone='15550000001')
        fields = {'phone': Doc(fieldtype='Data'), 'company': Doc(fieldtype='Link', options='Company'),
            'party_type': Doc(fieldtype='Link', options='DocType'), 'party': Doc(fieldtype='Dynamic Link', options='party_type'),
            'amount': Doc(fieldtype='Currency'), 'posting_date': Doc(fieldtype='Date')}
        meta = Doc(get_field=lambda key: fields.get(key))
        shared = types.SimpleNamespace(get_readable_meta=lambda dt: meta,
            is_sensitive_field=lambda name: name == 'api_key',
            get_readable_columns=lambda meta: {'name', *fields})
        config = module('relay_core/ai/configuration.py', self.f, {'relay_core.ai.tools': self.tools})
        access = module('relay_core/business_access.py', self.f)
        self.scope = dict(provider='WhatsApp', endpoint='15550000001', company='Sim Company', message='MSG-1')
        self.current_scope = dict(self.scope)
        self.patch = patch.dict(sys.modules, {'frappe_tools.ai.tools': shared, 'relay_core.ai.configuration': config,
            'relay_core.business_access': access, 'relay_core.ai.service': types.SimpleNamespace(
                context=lambda *args: ('partner', ('Supplier', 'SUP-A'), self.current_scope))}); self.patch.start(); self.addCleanup(self.patch.stop)
        self.f.get_doc.side_effect = lambda dt, name: self.anchor if dt == 'Supplier' else Doc(name=name) if dt == 'Relay Message' else next(row for row in self.records if row.name == name)
        def listing(dt, filters, **kw):
            self.assertEqual(self.f.session.user, 'partner')
            rows = [self.anchor] if dt == 'Supplier' else self.records
            return [Doc(name=row.name) for row in rows if all(row.get(key) == value for key, value in filters.items())]
        self.f.get_list.side_effect = listing
        self.reader = self.tools.Reader(self.skill, 'partner', ('Supplier', 'SUP-A'), self.scope)

    def test_ledger_is_scoped_by_business_name_and_dynamic_type(self):
        self.assertEqual(self.reader.read(self.contract), [{'name': 'LED-1', 'party': 'SUP-A', 'amount': 1250, 'posting_date': '2026-10-01'}])
        self.assertEqual(self.f.session.user, 'operator')
        self.assertEqual(self.f.get_list.call_args_list[1].kwargs['filters'],
            {'party': 'SUP-A', 'party_type': 'Supplier', 'company': 'Sim Company'})
        self.f.db.sql.assert_not_called()

    def test_cannot_override_business_or_supply_or_filters_methods_urls(self):
        for args in ({'filters': {'party': 'SUP-B'}}, {'or_filters': {}}, {'method': 'run_report'},
                     {'url': 'https://example.org'}, {'filters': {'amount': ['sql', 'select 1']}}, {'limit': 200}):
            with self.subTest(args=args), self.assertRaises(ValueError): self.reader.read(self.contract, **args)
        self.assertFalse(any(call.args[0] != 'Supplier' for call in self.f.get_list.call_args_list))
        self.f.db.sql.assert_not_called()

    def test_unknown_doctype_and_method_fail_before_read(self):
        for change in ({'doctype': 'User'}, {'method': 'sql'}, {'name': 'not_allowed'}):
            with self.assertRaises(ValueError): self.reader.read(self.contract | change)
        self.f.get_list.assert_not_called()

    def test_get_doc_checks_query_scope_and_document_permission(self):
        self.contract['method'] = 'get_doc'; self.skill.allowed_tools = json.dumps([self.contract])
        for name in ('', 'x' * 141):
            with self.assertRaises(ValueError): self.reader.read(self.contract, name=name)
        with self.assertRaises(ValueError): self.reader.read(self.contract, name='LED-2')
        self.records[0].denied = True
        with self.assertRaisesRegex(ValueError, 'unavailable'): self.reader.read(self.contract, name='LED-1')
        self.assertTrue(self.reader.failed)
        self.assertEqual(self.f.session.user, 'operator')

    def test_query_hook_denial_never_falls_back_to_get_all(self):
        self.f.get_list.side_effect = PermissionError('YRP denied')
        with self.assertRaises(ValueError): self.reader.read(self.contract)
        self.assertTrue(self.reader.failed)
        self.f.get_all.assert_not_called()
        self.f.db.sql.assert_not_called()

    def test_disabled_linked_user_cannot_read(self):
        self.f.db.get_value.return_value = 0
        with self.assertRaises(ValueError): self.reader.read(self.contract)
        self.f.get_list.assert_not_called()
        self.assertEqual(self.f.session.user, 'operator')

    def test_date_range_is_a_bound_filter_and_cannot_replace_party(self):
        self.f.get_list.side_effect = None; self.f.get_list.return_value = [Doc(name='LED-1')]
        self.reader.read(self.contract, filters={'posting_date': ['between', ['2026-10-01', '2026-10-20']]})
        self.assertEqual(self.f.get_list.call_args_list[1].kwargs['filters']['party'], 'SUP-A')
        self.assertEqual(self.f.get_list.call_args_list[1].kwargs['filters']['posting_date'][0], 'between')

    def test_empty_query_hook_result_hands_off_instead_of_claiming_zero_balance(self):
        self.f.get_list.side_effect = None; self.f.get_list.return_value = []
        with self.assertRaises(ValueError): self.reader.read(self.contract)
        self.assertTrue(self.reader.failed)

    def test_identity_is_canonical_and_cannot_come_from_a_typed_number(self):
        self.anchor.phone = '15550000002'
        with self.assertRaises(ValueError): self.reader.read(self.contract)
        self.anchor.phone = '+1 (555) 000-0001'
        with self.assertRaises(ValueError): self.reader.read(self.contract)
        self.f.get_all.assert_not_called()

    def test_missing_scope_or_legacy_contract_never_grants_access(self):
        with self.assertRaises(ValueError):
            self.tools.Reader(self.skill, 'partner', ('Supplier', 'SUP-A')).read(self.contract)
        self.contract.pop('identity_fields'); self.skill.allowed_tools = json.dumps([self.contract])
        with self.assertRaises(ValueError): self.reader.read(self.contract)
        self.f.get_list.assert_not_called()

    def test_loaded_record_company_and_type_are_rechecked(self):
        # Simulate a changed record after the query selected its name.
        self.f.get_list.side_effect = None; self.f.get_list.return_value = [Doc(name='LED-1')]
        for changes in ({'company': 'Sim Other Company'}, {'party_type': 'Customer'}, {'party': 'SUP-B'}):
            original = dict(self.records[0]); self.records[0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.reader.read(self.contract)
            self.records[0].update(original)

    def test_revoked_scope_and_changed_data_block_recovery(self):
        self.reader.read(self.contract)
        self.tools.recheck(self.skill, 'partner', ('Supplier', 'SUP-A'), self.reader.evidence, self.scope)
        self.records[0].amount = 2500
        with self.assertRaises(ValueError):
            self.tools.recheck(self.skill, 'partner', ('Supplier', 'SUP-A'), self.reader.evidence, self.scope)
        self.current_scope['company'] = 'Sim Other Company'
        with self.assertRaises(ValueError): self.reader.read(self.contract)

    def test_fields_denied_before_and_after_loading(self):
        shared = sys.modules['frappe_tools.ai.tools']
        original = shared.get_readable_columns
        shared.get_readable_columns = lambda meta: original(meta) - {'amount'}
        with self.assertRaises(ValueError): self.reader.read(self.contract)
        self.f.get_list.assert_not_called()
        denied = set()
        shared.get_readable_columns = lambda meta: original(meta) - denied
        def get_doc(dt, name):
            if dt == 'Relay Message': return Doc(name=name)
            if dt == 'Supplier': return self.anchor
            denied.add('amount')
            return self.records[0]
        self.f.get_doc.side_effect = get_doc
        with self.assertRaises(ValueError): self.reader.read(self.contract)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.f = framework(); self.saved = []
        self.contact = Doc(automation_paused=0, automation_generation=0)
        self.message = Doc(name='MSG-1', relay_contact='CONTACT-1', conversation_key='CHAT-1')
        automation = types.SimpleNamespace(lock_contact=lambda name: self.contact, internal_save=lambda doc: self.saved.append(doc))
        self.ticket = Doc(name='TKT-1')
        self.ensure = Mock(return_value=self.ticket)
        tickets = types.SimpleNamespace(ensure_episode=self.ensure, episode_owner_allowed=lambda user, message: user == 'fallback')
        self.service = module('relay_core/ai/handoff.py', self.f,
            {'relay_core.tickets': tickets, 'relay_core.automation.service': automation})
        self.f.get_single = lambda dt: Doc(ai_handoff_owner='fallback')
        self.f.get_doc.return_value = self.message
        self.run = Doc(name='RUN-1', message='MSG-1', generation=0)
        self.skill = Doc(handoff_owner='disabled')

    def test_retries_delegate_to_shared_episode_and_preserve_legacy_pause(self):
        for _ in range(2): self.service.handoff(self.run, self.skill, 'Permission denied')
        self.assertEqual(self.ensure.call_count, 2)
        self.ensure.assert_called_with(self.message, owner='fallback', skill=self.skill, run=self.run,
            subject='Conversation needs a person', reason='Permission denied')
        self.assertEqual(self.run.ticket, 'TKT-1')
        self.assertEqual(self.run.status, 'Handoff')
        self.assertEqual(self.contact.automation_generation, 1)
        self.assertEqual(self.contact.automation_paused, 1)
        self.assertEqual(self.f.session.user, 'operator')

    def test_no_owner_leaves_work_recoverable_without_unassigned_ticket(self):
        self.service.eligible = lambda *args: False
        with self.assertRaises(ValueError): self.service.handoff(self.run, self.skill, 'Failed')
        self.ensure.assert_not_called()
        self.assertEqual(self.f.session.user, 'operator')


class SkillDeliveryTests(unittest.TestCase):
    def setUp(self):
        from contextvars import ContextVar
        self.f = framework()
        self.run = Doc(name='RUN-1', status='Pending', skill='SKILL-1', execution_user='service', message='MSG-1', attempts=0)
        self.skill = Doc(name='SKILL-1', mode='Automatic', enabled=1)
        self.message = Doc(name='MSG-1')
        self.saved = []
        self.automation = types.SimpleNamespace(internal_save=lambda doc, **kw: self.saved.append(dict(doc)),
            lock_run=lambda name: self.run, lock_contact=Mock(), message_hash=Mock(), latest_message=Mock(),
            outgoing_run=ContextVar('test_run', default=None), reserve_attempt=Mock())
        self.tools = module('relay_core/ai/tools.py', self.f)
        self.service = module('relay_core/ai/service.py', self.f,
            {'relay_core.ai.tools': self.tools, 'relay_core.automation.service': self.automation})
        self.f.get_doc.side_effect = lambda dt, name: self.skill if dt == 'Relay AI Skill' else self.message
        self.scope = {'company': 'Sim Company', 'binding': 'Sim Sender'}
        self.service.current = Mock(return_value=('partner', ('Supplier', 'SUP-A'), self.scope))
        self.tools.recheck = Mock()
        self.service.decide = Mock(return_value={'reply': 'Your balance is 1250', 'handoff': False, 'reason': '', 'user': 'partner', 'reads': [], 'scope': self.tools.fingerprint(self.scope)})
        self.send = Mock(return_value={'status': 'Submitted', 'action': 'ACTION-1'})
        self.handoff = Mock()
        self.patch = patch.dict(sys.modules, {'relay_core.messaging': types.SimpleNamespace(send=self.send),
            'relay_core.ai.handoff': types.SimpleNamespace(handoff=self.handoff), 'relay_core.automation.service': self.automation, 'relay_core.ai.tools': self.tools})
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_reply_uses_durable_journal_and_persists_decision_first(self):
        def send(*args, **kw):
            self.assertEqual(self.automation.outgoing_run.get(), 'RUN-1')
            self.assertTrue(any(row.get('decision') for row in self.saved))
            return {'status': 'Submitted'}
        self.send.side_effect = send
        self.service.process('RUN-1')
        self.send.assert_called_once()
        self.assertEqual(self.send.call_args.args[:3], ('MSG-1', 'text', {'text': 'Your balance is 1250'}))
        self.assertEqual(self.run.status, 'Completed')
        self.assertIsNone(self.automation.outgoing_run.get())

    def test_recovery_reuses_persisted_decision_and_stable_key(self):
        self.run.decision = json.dumps(self.service.decide.return_value)
        self.service.process('RUN-1')
        self.service.decide.assert_not_called()
        first_key = self.send.call_args.args[3]
        self.run.status = 'Deciding'; self.service.process('RUN-1')
        self.assertEqual(self.send.call_args.args[3], first_key)

    def test_shadow_never_sends_or_hands_off_even_on_failure(self):
        self.skill.mode = 'Shadow'; self.service.process('RUN-1')
        self.send.assert_not_called(); self.handoff.assert_not_called()
        self.run.status = 'Pending'; self.run.decision = None
        self.service.decide.side_effect = PermissionError
        self.service.process('RUN-1')
        self.send.assert_not_called(); self.handoff.assert_not_called()
        self.assertEqual(self.run.status, 'Shadow')

    def test_permission_and_model_failure_share_handoff(self):
        for failure in (PermissionError, TimeoutError):
            self.run.status = 'Pending'; self.run.decision = None; self.run.attempts = 0
            self.service.decide.side_effect = failure
            self.service.process('RUN-1')
        self.assertEqual(self.handoff.call_count, 2)
        self.send.assert_not_called()

    def test_takeover_prevents_delivery(self):
        self.service.current.side_effect = self.service.Superseded('Conversation changed')
        self.service.process('RUN-1')
        self.send.assert_not_called()


    def test_revoked_tool_permission_after_inference_hands_off_without_sending(self):
        self.tools.recheck.side_effect = PermissionError
        self.service.process('RUN-1')
        self.send.assert_not_called()
        self.handoff.assert_called_once()

    def test_changed_linked_user_cannot_receive_previous_decision(self):
        self.run.decision = json.dumps(self.service.decide.return_value | {'user': 'old-partner'})
        self.service.process('RUN-1')
        self.send.assert_not_called()
        self.handoff.assert_called_once()

    def test_scope_change_blocks_delivery_even_without_reads(self):
        self.run.decision = json.dumps(self.service.decide.return_value)
        self.scope['company'] = 'Sim Other Company'
        self.service.process('RUN-1')
        self.send.assert_not_called()
        self.handoff.assert_called_once()

    def test_durable_queued_reply_does_not_trigger_handoff(self):
        self.send.return_value = {'status': 'Queued', 'action': 'ACTION-1'}
        self.service.process('RUN-1')
        self.assertEqual(self.run.status, 'Delivering')
        self.handoff.assert_not_called()


class SharedAdapterTests(unittest.TestCase):
    def setUp(self):
        try:
            from frappe_tools.ai import agent, client
            from frappe_tools.utils import llm
        except ImportError:
            self.skipTest('Requires the bench Python environment with frappe_tools')
        self.agent, self.client, self.llm = agent, client, llm
        self.f = framework()
        self.tools = module('relay_core/ai/tools.py', self.f)
        self.adapter = module('relay_core/ai/adapter.py', self.f, {'relay_core.ai.tools': self.tools})
        self.skill = Doc(ai_model='MODEL-1', allowed_tools='[]', instructions='Supplier support only.', business_doctype='Supplier')
        self.model = Doc(enabled=1, account='ACCOUNT-1', model_id='test-model', max_tokens=1200, temperature=0)
        self.account = Doc(enabled=1, provider='Test')
        self.f.get_doc.side_effect = lambda dt, name: self.model if dt == 'AI Model' else self.account
        self.provider = types.SimpleNamespace(user_message=lambda text, images: {'text': text}, continuation=lambda result, output: [])
        self.patches = [patch.object(agent, 'get_known_secrets', return_value=[]),
            patch.dict(client.PROVIDERS, Test=self.provider), patch.object(client, 'try_model')]
        self.attempt = None
        for item in self.patches:
            value = item.start(); self.addCleanup(item.stop)
            if isinstance(value, Mock): self.attempt = value

    def outcome(self, data=None, calls=None):
        return {'ok': True, 'result': {'data': data, 'tool_calls': calls or [], 'response': {}}}

    def test_uses_shared_engine_with_model_deadline_no_extraction_task_alias(self):
        self.attempt.return_value = self.outcome({'reply': 'I can ask a person to help.', 'handoff': True, 'reason': 'Unsupported intent'})
        result = self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Question', 'RUN-1')
        self.assertTrue(result['handoff'])
        args = self.attempt.call_args.args
        self.assertEqual(args[1], 'test-model')
        self.assertEqual(args[3]['timeout'], 20)
        self.assertEqual(args[3]['attempts'], 1)
        self.assertIsNone(args[4]['phase'])
        self.assertEqual(args[4]['reference_doctype'], 'Relay Automation Run')
        self.assertEqual(args[4]['reference_name'], 'RUN-1')
        self.assertIsInstance(args[5], float)

    def test_unregistered_tool_forces_handoff_even_if_model_returns_reply(self):
        self.attempt.side_effect = [self.outcome(calls=[{'name': 'run_sql', 'arguments': '{}', 'id': '1'}]),
            self.outcome({'reply': 'Made up answer', 'handoff': False, 'reason': ''})]
        with self.assertRaises(ValueError): self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Question')
        self.f.db.sql.assert_not_called()

    def test_malformed_response_and_disabled_model_fail_closed(self):
        self.attempt.return_value = self.outcome({'reply': 'hello', 'handoff': 'false', 'reason': ''})
        with self.assertRaises(ValueError): self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Question')
        self.model.enabled = 0
        with self.assertRaises(ValueError): self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Question')

    def test_ledger_reply_ignores_model_arithmetic(self):
        from relay_core.ai.ledger import summarize
        ledger = summarize([dict(company='Local Company', debit='100.10', credit='40.05', posting_date='2026-10-01',
            voucher_type='Journal Entry', voucher_no='SIM-1', remarks='Own supplier')], False)
        reader = types.SimpleNamespace(failed=False, evidence=[], ledger_results=[ledger])
        self.attempt.return_value = self.outcome({'reply': 'Invented total 999999', 'handoff': False, 'reason': ''})
        scope = {'company': 'Local Company', 'binding': 'Sim Sender'}
        with patch.object(self.adapter, 'Reader', return_value=reader) as constructor:
            result = self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'yes', scope=scope)
            constructor.assert_called_once_with(self.skill, 'partner', ('Supplier', 'SUP-A'), scope)
        self.assertIn('Net debit: 60.05', result['reply'])
        self.assertNotIn('999999', result['reply'])

    def test_non_tool_compatibility_uses_same_engine(self):
        self.attempt.return_value = self.outcome({'instructions': 'Support knowledge'})
        self.assertEqual(self.adapter.complete_json('MODEL-1', 'Draft knowledge'), {'instructions': 'Support knowledge'})

    def test_adapter_rejects_oversized_input_without_calling_model(self):
        with self.assertRaisesRegex(ValueError, 'budget'):
            self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'x' * 12001)
        self.attempt.assert_not_called()


class ConversationIdentityTests(unittest.TestCase):
    def setUp(self):
        from contextvars import ContextVar
        self.f = framework()
        self.tools = module('relay_core/ai/tools.py', self.f)
        automation = types.SimpleNamespace(internal_save=Mock(), lock_run=Mock(), lock_contact=Mock(),
            message_hash=Mock(), latest_message=Mock(), outgoing_run=ContextVar('identity_run'))
        self.service = module('relay_core/ai/service.py', self.f,
            {'relay_core.ai.tools': self.tools, 'relay_core.automation.service': automation})
        self.person = Doc(name='PERSON-1', user='partner')
        self.business = Doc(name='SUP-A')
        self.skill = Doc(channel='CH-1', business_doctype='Supplier', run_as_user='service')
        self.message = Doc(name='MSG-1', relay_contact='CONTACT-1', channel='CH-1', sender_endpoint='15550000001', direction='Incoming', message_type='text')
        from relay_core.automation.provenance import conversation_key
        self.message.provider_context = {'provider': 'WhatsApp', 'participant_id': '15550000001'}
        self.message.conversation_key = conversation_key('CH-1', self.message.sender_endpoint, self.message.provider_context)
        self.binding = Doc(name='Sim Binding', channel='CH-1', endpoint='15550000001', relay_contact='CONTACT-1', verified=1)
        self.f.get_doc.side_effect = lambda dt, name: {'Relay Contact': Doc(name='CONTACT-1', contact='PERSON-1'),
            'Contact': self.person, 'Relay Channel': Doc(channel='WhatsApp', enabled=1, company='Sim Company'), 'Company': Doc(), 'Supplier': self.business}[dt]
        self.f.db.get_value.side_effect = lambda dt, *args, **kw: self.binding if dt == 'Relay Contact Endpoint' else 1
        access = types.SimpleNamespace(reference=lambda doc: ('Supplier', 'SUP-A'), candidates=lambda contact: [('Supplier', 'SUP-A')])
        self.company_allowed = self.enterContext(patch('relay_core.permissions.company_allowed', return_value=True))
        self.patch = patch.dict(sys.modules, {'relay_core.business_access': access, 'frappe': self.f})
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_linked_user_takes_precedence_and_missing_link_uses_run_as(self):
        self.assertEqual(self.service.context(self.skill, self.message)[0], 'partner')
        self.person.user = None
        self.assertEqual(self.service.context(self.skill, self.message)[0], 'service')

    def test_disabled_linked_user_never_falls_back_to_service(self):
        self.f.db.get_value.side_effect = lambda dt, *args, **kw: self.binding if dt == 'Relay Contact Endpoint' else 0
        with self.assertRaises(ValueError): self.service.context(self.skill, self.message)
        self.assertEqual(self.f.session.user, 'operator')

    def test_revoked_partner_business_permission_denies_context(self):
        self.business.denied = True
        with self.assertRaises(PermissionError): self.service.context(self.skill, self.message)

    def test_company_query_denial_uses_effective_user_and_never_falls_back(self):
        users = []
        self.company_allowed.side_effect = lambda company: users.append(self.f.session.user) or False
        with self.assertRaises(PermissionError): self.service.context(self.skill, self.message)
        self.assertEqual(users, ['partner'])
        self.assertEqual(self.f.session.user, 'operator')
        self.assertEqual(self.f.session.user, 'operator')

    def test_revoked_endpoint_and_group_destination_deny_context(self):
        self.binding.verified = 0
        with self.assertRaises(ValueError): self.service.context(self.skill, self.message)
        self.binding.verified = 1
        self.message.provider_context['group_id'] = self.message.sender_endpoint
        with self.assertRaises(ValueError): self.service.context(self.skill, self.message)
        self.f.get_all.assert_not_called()

    def test_provider_mismatch_or_missing_provenance_cannot_use_typed_identity(self):
        self.message.content = 'My number is 15550000001'
        for evidence in ({}, {'provider': 'Telegram'}, {'provider': 'WhatsApp', 'participant_id': '15550000002'}):
            self.message.provider_context = evidence
            with self.subTest(evidence=evidence), self.assertRaises(ValueError): self.service.context(self.skill, self.message)

    def test_history_requires_matching_scope_and_never_replays_business_results(self):
        user, business, scope = self.service.context(self.skill, self.message)
        source = Doc(name='MSG-EARLIER', content='Show my October ledger')
        decision = dict(user=user, handoff=False, reads=[], reply='May I search October?',
            scope=self.tools.fingerprint(dict(scope, message=source.name)))
        self.f.get_doc.side_effect = lambda *args: source
        self.f.get_list.return_value = [source]
        self.f.db.get_value.side_effect = lambda dt, *args, **kw: json.dumps(decision) if dt == 'Relay Automation Run' else 1
        history = lambda: self.service.conversation_history(self.skill, self.message, user, business, scope)
        self.assertEqual(history(), [{'direction': 'Incoming', 'content': source.content},
            {'direction': 'Outgoing', 'content': decision['reply']}])
        for changes in ({'reads': [{'tool': 'ledger'}]}, {'scope': 'old-company'}, {'user': 'old-user'}, {'handoff': True}):
            original = dict(decision); decision.update(changes)
            self.assertEqual(history(), [])
            decision.update(original)
        self.f.get_list.side_effect = PermissionError('Audit history is restricted')
        self.assertEqual(history(), [])
        self.assertEqual(self.f.session.user, 'operator')

    def test_prompt_drops_oldest_history_and_preserves_handoff_request(self):
        self.message.content = 'Please hand this to a person. "Do not reply automatically."'
        history = [Doc(direction='Incoming', content=f'{index}: ' + 'x' * 2500) for index in range(6)]
        self.service.conversation_history = Mock(return_value=history)
        def complete(skill, user, business, text, run_id, *, scope):
            self.assertLessEqual(len(text), 12000)
            prompt = json.loads(text)
            self.assertEqual(prompt['incoming'], self.message.content)
            self.assertEqual(prompt['history'], history[2:])
            return {'handoff': 'hand this to a person' in prompt['incoming']}
        adapter = types.SimpleNamespace(complete=complete, MAX_PROMPT_LENGTH=12000)
        with patch.dict(sys.modules, {'relay_core.ai.adapter': adapter}):
            self.assertTrue(self.service.decide(self.skill, self.message)['handoff'])

    def test_prompt_budget_counts_json_escaping_and_never_truncates_incoming(self):
        self.message.content = 'தமிழ் "Please show my balance"'
        self.service.conversation_history = Mock(return_value=[Doc(direction='Incoming', content='"\\தமிழ்' * 2500)])
        complete = Mock(return_value={'handoff': False, 'reply': 'Scoped reply'})
        adapter = types.SimpleNamespace(complete=complete, MAX_PROMPT_LENGTH=12000)
        with patch.dict(sys.modules, {'relay_core.ai.adapter': adapter}):
            self.service.decide(self.skill, self.message)
            self.assertEqual(json.loads(complete.call_args.args[3]),
                {'history': [], 'incoming': self.message.content})
            complete.reset_mock()
            self.message.content = 'x' * 12000 + ' show my balance'
            with self.assertRaisesRegex(ValueError, 'budget'):
                self.service.decide(self.skill, self.message)
            complete.assert_not_called()


class ChannelAutomationTests(unittest.TestCase):
    def setUp(self):
        from contextvars import ContextVar
        self.f = framework()
        self.f.conf = Doc(relay_automation_enabled=1)
        automation = types.SimpleNamespace(internal_save=Mock(), lock_run=Mock(), lock_contact=Mock(),
            message_hash=Mock(), latest_message=Mock(), outgoing_run=ContextVar('channel_run',default=None))
        self.tools = module('relay_core/ai/tools.py', self.f)
        self.service = module('relay_core/ai/service.py',self.f,
            {'relay_core.ai.tools':self.tools,'relay_core.automation.service':automation})
        self.email_rules = module('relay_core/email_preferences.py',self.f)
        self.message = Doc(name='MSG-CHANNEL',sender_endpoint='person@example.invalid',
            provider_context=json.dumps(dict(provider='Email',subject='Order 25',message_id='<one@example.invalid>',
                authentication={'status':'pass'},auto_submitted=False)))

    def test_email_reply_is_durable_sender_only_with_original_subject(self):
        send = Mock(return_value={'status':'Queued'})
        with patch.dict(sys.modules,{'relay_core.email':types.SimpleNamespace(send=send)}):
            self.service.send_reply(self.message,'Quantity 25')
            first = send.call_args
            self.service.send_reply(self.message,'Quantity 25')
        self.assertEqual(first,send.call_args)
        self.assertEqual(first.args,(['person@example.invalid'],'Re: Order 25','Quantity 25'))
        self.assertEqual(first.kwargs['message'],'MSG-CHANNEL')
        self.assertEqual(first.kwargs['auto_submitted'],1)
        self.assertNotIn('cc',first.kwargs)

    def test_email_suppresses_automatic_mail_unverified_authentication_and_missing_ids(self):
        context = json.loads(self.message.provider_context)
        self.assertTrue(self.email_rules.automatic_allowed(context))
        for changes in ({'auto_submitted':True},{'authentication':{'status':'unverified'}},
                        {'authentication':{'status':'fail'}},{'message_id':None}):
            with self.subTest(changes=changes):
                self.assertFalse(self.email_rules.automatic_allowed(context | changes))
        self.assertTrue(self.email_rules.automatic_allowed({'provider':'Telegram'}))

    def test_disabled_or_paused_skill_does_not_fall_through_after_claim(self):
        self.f.db.exists.return_value = True
        self.f.conf.relay_automation_enabled = 0
        with patch.dict(sys.modules,{'relay_core.ai.service':types.SimpleNamespace(skill_for=Mock())}):
            self.assertTrue(self.email_rules.skill_claims(self.message))

    def test_telegram_reply_preserves_channel_routing_and_stable_journal_key(self):
        self.message.provider_context = json.dumps(dict(provider='Telegram',chat_id=-123,message_id=12,message_thread_id=7))
        send = Mock(return_value={'status':'Uncertain'})
        with patch.dict(sys.modules,{'relay_core.messaging':types.SimpleNamespace(send=send)}):
            self.service.send_reply(self.message,'Quantity 25')
        self.assertEqual(send.call_args.args[:3],('MSG-CHANNEL','text',{'text':'Quantity 25'}))

    def test_no_matching_skill_avoids_channel_document_contact_lock_and_journal_work(self):
        service = module('relay_core/automation/service.py',self.f,
            {'frappe.utils':types.SimpleNamespace(now_datetime=Mock(),add_to_date=Mock())})
        access = module('relay_core/business_access.py', self.f)
        self.f.db.exists.return_value = False
        self.f.get_all.return_value = [Doc(link_doctype='Customer', link_name=str(i)) for i in range(50)]
        create = Mock()
        self.message.direction = 'Incoming'
        with patch.dict(sys.modules,{'relay_core.ai.service':types.SimpleNamespace(skill_for=self.service.skill_for,create_run=create),
                                     'relay_core.business_access':access}):
            for _ in range(100):
                self.assertEqual(service.create_run(self.message),{'status':'Disabled'})
        self.f.get_doc.assert_not_called()
        self.f.db.get_value.assert_not_called()
        create.assert_not_called()
        self.f.get_all.assert_not_called()
        self.assertEqual(self.f.db.exists.call_count, 100)
        self.f.db.exists.assert_called_with('Relay AI Skill', {'channel':self.message.channel,'enabled':1})

    def test_business_destination_and_topic_changes_invalidate_a_pending_decision(self):
        service = module('relay_core/automation/service.py',self.f,
            {'frappe.utils':types.SimpleNamespace(now_datetime=Mock(),add_to_date=Mock())})
        self.message.update(content='Order 25',message_type='text',business_doctype='Customer',business_name='C1',
                            channel='CH',relay_contact='PERSON',conversation_key='TOPIC1')
        original = service.message_hash(self.message)
        for field,value in [('business_name','C2'),('business_doctype','Supplier'),('sender_endpoint','other@example.invalid'),
                            ('channel','OTHER'),('conversation_key','TOPIC2')]:
            with self.subTest(field=field):
                changed=Doc(self.message);changed[field]=value
                self.assertNotEqual(service.message_hash(changed),original)


class EventContractTests(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.f.db.exists.return_value = True
        self.channel = Doc(enabled=1, channel='WhatsApp', company='Sim Company', triage_owner='triage')
        self.f.get_doc.side_effect = lambda dt, name: self.channel if dt == 'Relay Channel' else Doc(enabled=1, account='account')
        self.tools = module('relay_core/ai/tools.py', self.f)
        self.access = Mock()
        self.config = module('relay_core/ai/configuration.py', self.f,
            {'relay_core.ai.tools': self.tools, 'relay_core.permissions': types.SimpleNamespace(require_access=self.access)})
        self.fields = {'phone': Doc(fieldtype='Data'), 'email': Doc(fieldtype='Data'),
            'company': Doc(fieldtype='Link', options='Company'), 'party': Doc(fieldtype='Dynamic Link', options='party_type'),
            'amount': Doc(fieldtype='Currency'), 'password': Doc(fieldtype='Password')}
        self.meta = Doc(get_field=lambda key: self.fields.get(key), issingle=0, istable=0)
        self.f.get_meta.return_value = self.meta
        self.shared = types.SimpleNamespace(get_readable_meta=lambda dt: self.meta,
            is_sensitive_field=lambda name: name in ('api_key', 'password'))
        self.registered = {}
        self.modules = patch.dict(sys.modules, {'frappe_tools.ai.tools': self.shared,
            'relay_core.flows.actions': types.SimpleNamespace(definitions=lambda: self.registered)})
        self.modules.start(); self.addCleanup(self.modules.stop)
        self.doc = Doc(name='Sim Ledger', title='Sim Ledger', enabled=0, business_doctype='Supplier',
            instructions='Read only this sender’s ledger after date confirmation.', mode='Shadow', daily_limit=25,
            allowed_tools='[]', allowed_actions='[]')
        self.read = dict(name='ledger', method='get_list', doctype='GL Entry', fields=['amount'], scope_field='party',
            identity_anchor='Supplier', identity_fields={'WhatsApp': 'phone'}, company_field='company')

    def enable(self):
        self.doc.update(enabled=1, target='Help this supplier understand their ledger', channel='Sim Channel',
            ai_model='Sim Model', run_as_user='operator', handoff_owner='owner')

    def test_disabled_drafts_do_not_need_channel_model_identity_or_owner(self):
        self.config.validate_skill(self.doc)
        self.assertIsNone(self.doc.active_key)
        self.assertEqual((self.doc.search_confirmation, self.doc.execution_policy), ('Always', 'Ticket only'))
        self.f.get_doc.assert_not_called()

    def test_multiple_targets_share_channel_and_business_without_scope_reservation(self):
        self.enable()
        for name, target in [('Sim Ledger', 'Explain ledger'), ('Sim Payment', 'Review payment evidence')]:
            self.doc.update(name=name, target=target, active_key='legacy-scope')
            self.config.validate_skill(self.doc)
            self.assertIsNone(self.doc.active_key)
        self.f.get_all.assert_not_called()

    def test_activation_requires_target_company_triage_and_live_model(self):
        self.enable()
        for field in ('target', 'channel', 'ai_model', 'run_as_user', 'handoff_owner'):
            value = self.doc[field]; self.doc[field] = None
            with self.subTest(field=field), self.assertRaises(ValueError): self.config.validate_skill(self.doc)
            self.doc[field] = value
        for field in ('company', 'triage_owner', 'enabled'):
            value = self.channel[field]; self.channel[field] = None
            with self.subTest(field=field), self.assertRaises(ValueError): self.config.validate_skill(self.doc)
            self.channel[field] = value
        self.f.db.get_value.return_value = 0
        with self.assertRaises(ValueError): self.config.validate_skill(self.doc)
        self.f.db.get_value.return_value = 1
        self.f.get_doc.side_effect = lambda dt, name: self.channel if dt == 'Relay Channel' else Doc(enabled=0)
        with self.assertRaises(ValueError): self.config.validate_skill(self.doc)

    def test_declared_identity_and_company_mappings_are_checked_against_metadata(self):
        self.enable(); self.doc.allowed_tools = json.dumps([self.read])
        self.config.validate_skill(self.doc)
        for changes in ({'identity_anchor': 'Customer'}, {'identity_fields': {'WhatsApp': 'missing'}},
                {'identity_fields': {'WhatsApp': 'password'}}, {'identity_fields': {'WhatsApp': 'company'}},
                {'identity_fields': {'Telegram': 'phone'}}, {'identity_fields': {'SMS': 'phone'}},
                {'company_field': 'phone'}, {'company_field': 'missing'}, {'method': 'sql'}, {'extra': 'anything'}):
            self.doc.allowed_tools = json.dumps([self.read | changes])
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.config.validate_skill(self.doc)
        self.doc.allowed_tools = json.dumps([{key: value for key, value in self.read.items() if key not in self.config.SCOPE_FIELDS}])
        with self.assertRaises(ValueError): self.config.validate_skill(self.doc)
        self.doc.enabled = 0
        self.config.validate_skill(self.doc)  # Legacy references remain editable as drafts.

    def test_owner_text_and_contracts_are_bounded_and_plain_text_preserved(self):
        self.doc.instructions = 'Owner says <review> & check 1250; never submit.'
        self.config.validate_skill(self.doc)
        self.assertIn('<review>', self.doc.instructions)
        for field, value in [('instructions', 'x'*8001), ('target', 'x'*2001), ('reply_style', 'x'*2001),
                ('exact_trigger', 'x'*141), ('allowed_tools', '[{}]'*5000), ('allowed_actions', '{}'),
                ('search_confirmation', 'Never'), ('execution_policy', 'Submit')]:
            original = self.doc.get(field); self.doc[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): self.config.validate_skill(self.doc)
            self.doc[field] = original

    def test_actions_use_only_explicit_safe_core_registrations(self):
        self.doc.execution_policy = 'Execute'
        declared = json.dumps([{'action': 'draft_payment', 'doctype': 'Payment Entry', 'fields': ['amount']}])
        self.doc.allowed_actions = declared
        schema = {'type': 'object', 'properties': {'amount': {'type': 'number'}}, 'additionalProperties': False}
        definition = dict(ai_safe=True, method='relay_core.ai.actions.create_draft', effect='create_draft',
            approval_policy='Required', permissions={'Payment Entry': 'create'}, parameters=schema,
            targets={'Payment Entry': schema}, output={'type': 'object'})
        self.registered['draft_payment'] = definition
        self.config.validate_skill(self.doc)
        for changes in ({'ai_safe': False}, {'method': 'erpnext.submit'}, {'effect': 'submit'},
                {'permissions': []}, {'approval_policy': 'anything'}, {'targets': {}}, {'output': {}},
                {'targets': {'Payment Entry': {'type': 'object', 'properties': {'docstatus': {'type': 'integer'}}}}}):
            self.registered['draft_payment'] = definition | changes
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.config.validate_skill(self.doc)
        self.registered['draft_payment'] = definition
        for value in ('[{"action":"unknown"}]', json.dumps(json.loads(declared)*2), '[{"method":"frappe.client.insert"}]'):
            self.doc.allowed_actions = value
            with self.assertRaises(ValueError): self.config.validate_skill(self.doc)
        self.doc.allowed_actions = declared; self.doc.execution_policy = 'Ticket only'
        with self.assertRaises(ValueError): self.config.validate_skill(self.doc)
        self.doc.execution_policy = 'Execute'
        self.registered['reply'] = definition | {'effect': 'reply', 'permissions': {'Relay Message': 'create'}}
        self.doc.allowed_actions = '[{"action":"reply"}]'
        self.config.validate_skill(self.doc)
        self.doc.allowed_actions = '[{"action":"reply","destination":"another-person"}]'
        with self.assertRaises(ValueError): self.config.validate_skill(self.doc)
        for row in ({'action': 'draft_payment', 'doctype': 'User', 'fields': ['amount']},
                {'action': 'draft_payment', 'doctype': 'Payment Entry', 'fields': ['undeclared']},
                {'action': 'draft_payment', 'doctype': 'Payment Entry', 'fields': []}):
            self.doc.allowed_actions = json.dumps([row])
            with self.subTest(row=row), self.assertRaises(ValueError): self.config.validate_skill(self.doc)

    def test_save_directory_shape_and_configure_denial(self):
        self.f.new_doc = Mock(return_value=self.doc)
        self.assertEqual(self.config.save({'target': 'Review payment', 'allowed_actions': '[]'}), {'name': 'Sim Ledger'})
        self.f.get_list.return_value = [self.doc]
        result = self.config.directory()
        self.assertEqual(set(result), {'items', 'next'})
        self.assertEqual(result['items'][0].target, 'Review payment')
        self.assertTrue(set(self.config.FIELDS) <= set(self.f.get_list.call_args.kwargs['fields']))
        with self.assertRaises(ValueError): self.config.save({'active_key': 'client-scope'})
        self.access.side_effect = PermissionError('Denied')
        for call in (lambda: self.config.save({'target': 'Denied'}), self.config.directory,
                     lambda: self.config.validate_skill(self.doc)):
            with self.assertRaises(PermissionError): call()

    def test_new_sample_has_event_defaults_and_no_assumed_identity_mapping(self):
        samples = module('relay_core/ai/samples.py', self.f)
        self.f.db.exists.side_effect = lambda dt, value: dt == 'DocType'
        self.f.get_doc.side_effect = lambda values: Doc(values)
        samples.install_samples()
        values = self.f.get_doc.call_args.args[0]
        self.assertEqual(values['target'], samples.TARGET)
        self.assertEqual(values['execution_policy'], 'Execute')
        self.assertEqual(values['allowed_actions'], '[]')
        self.assertFalse(values['enabled'])
        self.assertNotIn('identity_fields', json.loads(values['allowed_tools'])[0])


def site_tests():
    """yrp.site configuration/HTTP acceptance, with local fixtures and no delivery.

    Run: PYTHONPATH=<worktree> <bench-python> -B tests/test_ai_skills.py --site
    """
    import os
    import secrets
    from contextlib import ExitStack
    from datetime import datetime
    from integration_ai_permissions_site import confine_writes
    sys.addaudithook(confine_writes)
    sites = '/home/sakthi/development/pilot/benches/version_16/sites'
    root = Path(__file__).resolve().parents[1]
    os.environ['FRAPPE_STREAM_LOGGING'] = '1'
    os.environ['SITES_PATH'] = sites
    import frappe
    import frappe.app
    import relay_core
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    from relay_core.ai import configuration
    assert Path(relay_core.__file__).resolve().is_relative_to(root)
    stamp = datetime.now().strftime('R%m%d-%H%M')
    created = []

    def connect():
        frappe.init(site='yrp.site', sites_path=sites)
        frappe.connect(); frappe.set_user('Administrator')
        frappe.flags.mute_emails = True
        frappe.conf.relay_automation_enabled = 0

    def insert(doctype, label, **values):
        doc = frappe.get_doc(dict(doctype=doctype, **values)).insert()
        created.append((doctype, doc.name))
        return doc

    with ExitStack() as stack:
        for method in ('enqueue', 'sendmail', 'publish_realtime'):
            stack.enter_context(patch.object(frappe, method))
        stack.enter_context(patch('relay_core.whatsapp.client', side_effect=AssertionError('No external delivery')))
        stack.enter_context(patch('frappe.core.doctype.user.user.throttle_user_creation'))
        connect()
        try:
            for dt, fields in [('Relay AI Skill', configuration.FIELDS), ('Relay Channel', ('company', 'triage_owner'))]:
                assert all(frappe.get_meta(dt).has_field(field) for field in fields), 'Reload changed Relay JSON first'
            actor = insert('User', 'Sim Event Owner', email=f'sim-event-owner-{stamp.lower()}@example.invalid',
                first_name='Sim Event Owner ' + stamp, send_welcome_email=0, roles=[{'role': 'System Manager'}])
            reader = insert('User', 'Sim Event Reader', email=f'sim-event-reader-{stamp.lower()}@example.invalid',
                first_name='Sim Event Reader ' + stamp, send_welcome_email=0, roles=[{'role': 'Relay Communication User'}])
            credentials = {}
            for user in (actor, reader):
                user.api_key, user.api_secret = secrets.token_hex(12), secrets.token_hex(24)
                credentials[user.name] = 'token ' + user.api_key + ':' + user.api_secret
                user.save()
            company = frappe.db.get_value('Company', {}, 'name')
            assert company, 'A local company is required'
            channel = insert('Relay Channel', 'Sim Event Channel', title='Sim Event Channel ' + stamp,
                account='Sim Event Account ' + stamp, channel='Email', enabled=1, company=company, triage_owner=actor.name)
            # Local provider/model metadata is real; no credentials or model calls are needed for configuration.
            account = insert('AI Provider Account', 'Sim Event Account', account_name='Sim Event Account ' + stamp,
                provider='OpenRouter', auth_type='API Key', enabled=1)
            model = insert('AI Model', 'Sim Event Model', model_label='Sim Event Model ' + stamp,
                account=account.name, provider='OpenRouter', model_id='sim-local-no-network', enabled=1)
            contract = dict(name='receipt', method='get_doc', doctype='Payment Entry', scope_field='name',
                fields=['company', 'paid_amount'], identity_anchor='Payment Entry',
                identity_fields={'Email': 'contact_email'}, company_field='company')
            values = dict(title='Sim Receipt Event ' + stamp, business_doctype='Payment Entry', enabled=0,
                mode='Shadow', daily_limit=25, instructions='Explain the sender’s own payment of 1250. Never submit.',
                allowed_tools=json.dumps([contract]), allowed_actions='[]')
            name = configuration.save(values)['name']; created.append(('Relay AI Skill', name))
            assert not frappe.get_doc('Relay AI Skill', name).enabled
            activation = dict(enabled=1, target='Explain my receipt', channel=channel.name, ai_model=model.name,
                run_as_user=actor.name, handoff_owner=actor.name, reply_style='Brief and clear',
                search_confirmation='Always', exact_trigger='/receipt', execution_policy='Execute')
            configuration.save(activation, name=name)
            second = configuration.save(values | activation | {'title': 'Sim Receipt Review ' + stamp,
                'target': 'Ask staff to review a receipt', 'execution_policy': 'Ticket only'})['name']
            created.append(('Relay AI Skill', second))
            assert all(frappe.get_doc('Relay AI Skill', key).active_key is None for key in (name, second))
            for invalid in ({'target': ''}, {'allowed_tools': json.dumps([contract | {'identity_fields': {'Email': 'api_secret'}}])},
                    {'allowed_tools': json.dumps([contract | {'company_field': 'paid_amount'}])},
                    {'allowed_actions': '[{"action":"retailer.create_follow_up"}]'}, {'allowed_actions': '[{"action":"frappe.client.submit"}]'}):
                try:
                    configuration.save(invalid, name=name)
                except (ValueError, frappe.ValidationError):
                    pass
                else:
                    raise AssertionError('Invalid activation was accepted')
            assert frappe.get_doc('Relay AI Skill', name).target == activation['target']
            # Exercise the actual after_migrate hook against an enabled pre-event
            # sample, without running migrate or touching the installed sample.
            from relay_core.ai import samples
            legacy = frappe.get_doc(dict(doctype='Relay AI Skill', name='Sim Legacy Ledger ' + stamp,
                title='Sim Legacy Ledger ' + stamp, sample_key='Sim Legacy Ledger ' + stamp,
                business_doctype='Supplier', instructions=samples.INSTRUCTIONS,
                allowed_tools=json.dumps([samples.LEGACY_LEDGER_TOOL]), enabled=1,
                mode='Automatic', daily_limit=25, channel=channel.name, ai_model=model.name,
                run_as_user=actor.name, handoff_owner=actor.name))
            legacy.db_insert(); created.append(('Relay AI Skill', legacy.name))
            original_exists = frappe.db.exists
            def sample_exists(doctype, filters=None, *args, **kwargs):
                if doctype == 'Relay AI Skill' and filters == {'sample_key': 'supplier_ledger'}:
                    return legacy.name
                return original_exists(doctype, filters, *args, **kwargs)
            assert 'relay_core.ai.samples.install_samples' in frappe.get_hooks('after_migrate')
            with patch.object(frappe.db, 'exists', side_effect=sample_exists):
                samples.install_samples()
                samples.install_samples()
            legacy.reload()
            assert legacy.enabled == 0 and legacy.mode == 'Automatic'
            assert json.loads(legacy.allowed_tools) == [samples.LEDGER_TOOL]
            assert not legacy.target and 'identity_fields' not in legacy.allowed_tools
            print('PASS enabled legacy sample after_migrate hook: disabled editable draft, no invented identity, idempotent upgrade')
            print('PASS yrp.site disabled draft, activation, two targets, invalid identity/company/actions and stored version')
            frappe.db.commit(); frappe.destroy()

            original_init = frappe.app.init_request
            def init_request(request):
                original_init(request)
                frappe.flags.mute_emails = True
                frappe.conf.relay_automation_enabled = 0
            stack.enter_context(patch.object(frappe.app, 'init_request', init_request))
            def application(environ, start_response):
                environ['HTTP_X_FRAPPE_SITE_NAME'] = 'yrp.site'
                return frappe.app.application(environ, start_response)
            client = Client(application, Response)
            prefix = '/api/method/relay_core.ai.configuration.'
            def request(method, path, user=actor.name, **kwargs):
                response = client.open(prefix + path, method=method,
                    headers={'Authorization': credentials[user]} if user else {}, **kwargs)
                response.close()
                return response
            response = request('POST', 'save', json={'name': name, 'values': {'reply_style': 'Use <plain> words & exact amounts.'}})
            assert response.status_code == 200, ('save', response.status_code)
            assert response.json['message'] == {'name': name}
            response = request('GET', 'directory', query_string={'after': name})
            assert response.status_code == 200
            assert set(response.json['message']) == {'items', 'next'}
            assert any(row['name'] == second and row['target'] == 'Ask staff to review a receipt'
                and row['allowed_actions'] == '[]' for row in response.json['message']['items'])
            for method, path, kwargs in [('GET', 'directory', {}), ('POST', 'save', {'json': {'name': name, 'values': {'target': 'Denied'}}})]:
                for user in (reader.name, None):
                    response = request(method, path, user=user, **kwargs)
                    assert response.status_code in (401, 403), (path, response.status_code)
                    assert response.json.get('exc_type') == 'PermissionError'
            response = request('GET', 'save', query_string={'name': name, 'values': '{}'})
            assert response.status_code == 403
            response = request('POST', 'save', json={'name':legacy.name, 'values':{'enabled':1, 'target':samples.TARGET}})
            assert response.status_code == 500 and response.json['exc_type'] == 'ValueError', ('legacy enable', response.status_code, response.json.get('exc_type'))
            response = client.post('/api/method/relay_core.ai.samples.install_samples',
                headers={'Authorization': credentials[actor.name]})
            assert response.status_code == 403 and response.json['exc_type'] == 'PermissionError'
            connect()
            stored = frappe.get_doc('Relay AI Skill', name)
            assert stored.reply_style == 'Use <plain> words & exact amounts.' and stored.target == activation['target']
            print('PASS HTTP save/directory status and shape, authenticated staff and guest denial, method restriction, plain text persistence')
        finally:
            if not getattr(frappe.local, 'db', None):
                connect()
            frappe.set_user('Administrator')
            frappe.db.rollback()
            for doctype, name in reversed(created):
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, delete_permanently=True)
            frappe.db.commit()
            assert not any(frappe.db.exists(dt, key) for dt, key in created)
            frappe.destroy()
            print('CLEANED local Sim event fixtures')


if __name__ == '__main__':
    if sys.argv[1:] == ['--site']:
        site_tests()
    else:
        unittest.main()
