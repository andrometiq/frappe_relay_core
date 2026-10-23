"""Skill boundary tests with two businesses, real tool dispatch and a fake model."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


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
            fields=['name', 'party', 'amount', 'posting_date'], scope_field='party')
        self.skill = Doc(business_doctype='Supplier', allowed_tools=json.dumps([self.contract]))
        self.records = [Doc(name='LED-1', party='SUP-A', party_type='Supplier', amount=1250, posting_date='2026-10-01'),
                        Doc(name='LED-2', party='SUP-B', party_type='Supplier', amount=4500, posting_date='2026-10-02'),
                        Doc(name='LED-3', party='SUP-A', party_type='Customer', amount=900, posting_date='2026-10-03')]
        fields = {'party': Doc(fieldtype='Dynamic Link', options='party_type'),
            'amount': Doc(fieldtype='Currency'), 'posting_date': Doc(fieldtype='Date')}
        meta = Doc(get_field=lambda key: fields.get(key))
        shared = types.SimpleNamespace(get_readable_meta=lambda dt: meta,
            is_sensitive_field=lambda name: name == 'api_key',
            get_readable_columns=lambda meta: {'name', 'party', 'amount', 'posting_date'})
        self.patch = patch.dict(sys.modules, {'frappe_tools.ai.tools': shared}); self.patch.start(); self.addCleanup(self.patch.stop)
        self.f.get_doc.side_effect = lambda dt, name: Doc(name=name) if dt == 'Supplier' else next(row for row in self.records if row.name == name)
        def listing(dt, filters, **kw):
            self.assertEqual(self.f.session.user, 'partner')
            return [Doc(name=row.name) for row in self.records if all(row.get(key) == value for key, value in filters.items())]
        self.f.get_list.side_effect = listing
        self.reader = self.tools.Reader(self.skill, 'partner', ('Supplier', 'SUP-A'))

    def test_ledger_is_scoped_by_business_name_and_dynamic_type(self):
        self.assertEqual(self.reader.read(self.contract), [{'name': 'LED-1', 'party': 'SUP-A', 'amount': 1250, 'posting_date': '2026-10-01'}])
        self.assertEqual(self.f.session.user, 'operator')
        self.assertEqual(self.f.get_list.call_args.kwargs['filters'], {'party': 'SUP-A', 'party_type': 'Supplier'})
        self.f.db.sql.assert_not_called()

    def test_cannot_override_business_or_supply_or_filters_methods_urls(self):
        for args in ({'filters': {'party': 'SUP-B'}}, {'or_filters': {}}, {'method': 'run_report'},
                     {'url': 'https://example.org'}, {'filters': {'amount': ['sql', 'select 1']}}, {'limit': 200}):
            with self.subTest(args=args), self.assertRaises(ValueError): self.reader.read(self.contract, **args)
        self.f.get_list.assert_not_called()
        self.f.db.sql.assert_not_called()

    def test_unknown_doctype_and_method_fail_before_read(self):
        for change in ({'doctype': 'User'}, {'method': 'sql'}, {'name': 'not_allowed'}):
            with self.assertRaises(ValueError): self.reader.read(self.contract | change)
        self.f.get_list.assert_not_called()

    def test_get_doc_checks_query_scope_and_document_permission(self):
        self.contract['method'] = 'get_doc'; self.skill.allowed_tools = json.dumps([self.contract])
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
        self.assertEqual(self.f.get_list.call_args.kwargs['filters']['party'], 'SUP-A')
        self.assertEqual(self.f.get_list.call_args.kwargs['filters']['posting_date'][0], 'between')

    def test_empty_query_hook_result_hands_off_instead_of_claiming_zero_balance(self):
        self.f.get_list.side_effect = None; self.f.get_list.return_value = []
        with self.assertRaises(ValueError): self.reader.read(self.contract)
        self.assertTrue(self.reader.failed)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.f = framework(); self.saved = []
        self.contact = Doc(automation_paused=0, automation_generation=0)
        self.message = Doc(name='MSG-1', relay_contact='CONTACT-1', conversation_key='CHAT-1')
        automation = types.SimpleNamespace(lock_contact=lambda name: self.contact, internal_save=lambda doc: self.saved.append(doc))
        self.tools = module('relay_core/ai/tools.py', self.f)
        self.service = module('relay_core/ai/handoff.py', self.f,
            {'relay_core.ai.tools': self.tools, 'relay_core.automation.service': automation})
        self.service.eligible = lambda user, message: user == 'fallback'
        self.f.get_single = lambda dt: Doc(ai_handoff_owner='fallback')
        self.ticket = None; self.inserts = 0
        def get_doc(dt, name=None):
            if isinstance(dt, dict):
                self.inserts += 1; self.ticket = Doc(dt, name='TKT-1'); return self.ticket
            return self.message if dt == 'Relay Message' else self.ticket
        self.f.get_doc.side_effect = get_doc
        self.f.db.get_value.side_effect = lambda dt, *args, **kw: self.ticket.name if self.ticket else None
        self.run = Doc(name='RUN-1', message='MSG-1', generation=0)
        self.skill = Doc(handoff_owner='disabled')
        self.patch = patch.dict(sys.modules, {'relay_core.business_access': types.SimpleNamespace(reference=lambda message: ('Supplier', 'SUP-A'))})
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_retries_create_exactly_one_assigned_business_ticket_and_pause(self):
        for _ in range(2): self.service.handoff(self.run, self.skill, 'Permission denied')
        self.assertEqual(self.inserts, 1)
        self.assertEqual(self.ticket.assigned_to, 'fallback')
        self.assertEqual((self.ticket.business_doctype, self.ticket.business_name), ('Supplier', 'SUP-A'))
        self.assertEqual(self.ticket.source_run, 'RUN-1')
        self.assertEqual(self.run.ticket, 'TKT-1')
        self.assertEqual(self.run.status, 'Handoff')
        self.assertEqual(self.contact.automation_generation, 1)
        self.assertEqual(self.contact.automation_paused, 1)
        self.assertEqual(self.f.session.user, 'operator')

    def test_no_owner_leaves_work_recoverable_without_unassigned_ticket(self):
        self.service.eligible = lambda *args: False
        with self.assertRaises(ValueError): self.service.handoff(self.run, self.skill, 'Failed')
        self.assertEqual(self.inserts, 0)
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
        self.service.current = Mock(return_value=('partner', ('Supplier', 'SUP-A')))
        self.tools.recheck = Mock()
        self.service.decide = Mock(return_value={'reply': 'Your balance is 1250', 'handoff': False, 'reason': '', 'user': 'partner', 'reads': []})
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

    def test_durable_queued_reply_does_not_trigger_handoff(self):
        self.send.return_value = {'status': 'Queued', 'action': 'ACTION-1'}
        self.service.process('RUN-1')
        self.assertEqual(self.run.status, 'Completed')
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
        ledger = summarize([dict(debit='100.10', credit='40.05', posting_date='2026-10-01',
            voucher_type='Journal Entry', voucher_no='SIM-1', remarks='Own supplier')], False)
        reader = types.SimpleNamespace(failed=False, evidence=[], ledger_results=[ledger])
        self.attempt.return_value = self.outcome({'reply': 'Invented total 999999', 'handoff': False, 'reason': ''})
        with patch.object(self.adapter, 'Reader', return_value=reader):
            result = self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'yes')
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
        self.person = Doc(user='partner')
        self.business = Doc(name='SUP-A')
        self.skill = Doc(channel='CH-1', business_doctype='Supplier', run_as_user='service')
        self.message = Doc(name='MSG-1', relay_contact='CONTACT-1', channel='CH-1', sender_endpoint='15550000001', direction='Incoming', message_type='text')
        self.f.get_doc.side_effect = lambda dt, name: {'Relay Contact': Doc(name='CONTACT-1', contact='PERSON-1'),
            'Contact': self.person, 'Relay Channel': Doc(channel='WhatsApp', enabled=1), 'Supplier': self.business}[dt]
        self.f.db.get_value.side_effect = lambda dt, *args, **kw: 'CONTACT-1' if dt == 'Relay Contact Endpoint' else 1
        access = types.SimpleNamespace(reference=lambda doc: ('Supplier', 'SUP-A'), candidates=lambda contact: [('Supplier', 'SUP-A')])
        self.patch = patch.dict(sys.modules, {'relay_core.business_access': access})
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_linked_user_takes_precedence_and_missing_link_uses_run_as(self):
        self.assertEqual(self.service.context(self.skill, self.message)[0], 'partner')
        self.person.user = None
        self.assertEqual(self.service.context(self.skill, self.message)[0], 'service')

    def test_disabled_linked_user_never_falls_back_to_service(self):
        self.f.db.get_value.side_effect = lambda dt, *args, **kw: 'CONTACT-1' if dt == 'Relay Contact Endpoint' else 0
        with self.assertRaises(ValueError): self.service.context(self.skill, self.message)
        self.assertEqual(self.f.session.user, 'operator')

    def test_revoked_partner_business_permission_denies_context(self):
        self.business.denied = True
        with self.assertRaises(PermissionError): self.service.context(self.skill, self.message)
        self.assertEqual(self.f.session.user, 'operator')

    def test_prompt_drops_oldest_history_and_preserves_handoff_request(self):
        self.message.conversation_key = 'CHAT-1'
        self.message.content = 'Please hand this to a person. "Do not reply automatically."'
        history = [Doc(direction='Incoming', content=f'{index}: ' + 'x' * 2500) for index in range(6)]
        self.f.get_list.return_value = list(reversed(history))
        def complete(skill, user, business, text, run_id):
            self.assertLessEqual(len(text), 12000)
            prompt = json.loads(text)
            self.assertEqual(prompt['incoming'], self.message.content)
            self.assertEqual(prompt['history'], history[2:])
            return {'handoff': 'hand this to a person' in prompt['incoming']}
        adapter = types.SimpleNamespace(complete=complete, MAX_PROMPT_LENGTH=12000)
        with patch.dict(sys.modules, {'relay_core.ai.adapter': adapter}):
            self.assertTrue(self.service.decide(self.skill, self.message)['handoff'])

    def test_prompt_budget_counts_json_escaping_and_never_truncates_incoming(self):
        self.message.conversation_key = 'CHAT-1'
        self.message.content = 'தமிழ் "Please hand this to a person"'
        self.f.get_list.return_value = [Doc(direction='Incoming', content='"\\தமிழ்' * 2500)]
        complete = Mock()
        adapter = types.SimpleNamespace(complete=complete, MAX_PROMPT_LENGTH=12000)
        with patch.dict(sys.modules, {'relay_core.ai.adapter': adapter}):
            self.service.decide(self.skill, self.message)
            self.assertEqual(json.loads(complete.call_args.args[3]),
                {'history': [], 'incoming': self.message.content})
            complete.reset_mock()
            self.message.content = 'x' * 12000 + ' hand this to a person'
            with self.assertRaisesRegex(ValueError, 'budget'):
                self.service.decide(self.skill, self.message)
            complete.assert_not_called()
