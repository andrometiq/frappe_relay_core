"""Typed AI execution shares the flow journal and never trusts model scope."""
import json
import sys
import types
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from test_ai_skills import Doc, framework, module
from relay_core.flows.action_contracts import ai_contract, ai_inputs


def definition(policy='Required'):
    schema = {'type': 'object', 'required': ['paid_amount'],
              'properties': {'paid_amount': {'type': 'number', 'minimum': 1}}, 'additionalProperties': False}
    return dict(method='relay_core.ai.actions.create_draft', contexts=['flow', 'ai'], replay_safe=True, ai_safe=True,
        effect='create_draft', approval_policy=policy, permissions={'Payment Entry': 'create'},
        parameters=schema, targets={'Payment Entry': schema}, output={'type': 'object',
        'properties': {'doctype': {'type': 'string'}, 'name': {'type': 'string'}}, 'required': ['doctype', 'name']})


class AIContracts(unittest.TestCase):
    def test_ordered_reply_keys_are_distinct_bounded_and_stable(self):
        from relay_core.automation.contracts import action_key
        keys = [action_key('Sim Source', f'event_reply_{step}') for step in range(4)]
        self.assertEqual(len(set(keys)), 4)
        self.assertEqual(keys[0], action_key('Sim Source', 'event_reply_0'))
        self.assertNotIn(action_key('Sim Source', 'reply'), keys)
        for slot in ('event_reply_4', 'event_reply_-1', 'event_reply_0;submit'):
            with self.assertRaises(ValueError): action_key('Sim Source', slot)

    def test_literal_typed_fields_and_target_allowlist(self):
        action = definition()
        declared = dict(action='draft_payment', doctype='Payment Entry', fields=['paid_amount'])
        self.assertEqual(ai_inputs({'paid_amount': 1250}, action, declared), {'paid_amount': 1250})
        for value in ({'paid_amount': True}, {'paid_amount': '1250'}, {'paid_amount': {'var': 'amount'}},
                      {'paid_amount': 1250, 'docstatus': 1}, {'paid_amount': float('nan')}):
            with self.subTest(value=value), self.assertRaises(ValueError): ai_inputs(value, action, declared)
        for change in ({'doctype': 'User'}, {'fields': []}):
            with self.assertRaises(ValueError): ai_inputs({'paid_amount': 1250}, action, declared | change)

    def test_persisted_sequence_rejects_skips_reordering_and_repetition(self):
        from relay_core.flows.actions import validate_sequence
        declared=[{'action':'create_draft'}, {'action':'reply'}]
        steps=[dict(row, parameters={}) for row in declared]
        with patch('relay_core.ai.configuration.action_contracts', return_value=declared):
            self.assertEqual(validate_sequence(Doc(), steps), declared)
            for invalid in (steps[::-1], steps[:1], steps[1:], steps + steps[:1], None):
                with self.subTest(steps=invalid), self.assertRaises(ValueError):
                    validate_sequence(Doc(), invalid)

    def test_unsafe_registrations_fail_closed(self):
        for change in ({'ai_safe': False}, {'contexts': ['flow']}, {'method': 'frappe.client.insert'}, {'effect': 'submit'},
                       {'approval_policy': 'Optional'}, {'permissions': {'Payment Entry': 'submit'}},
                       {'output': {}}, {'parameters': {'type': 'string'}}):
            with self.subTest(change=change), self.assertRaises(ValueError): ai_contract(definition() | change)


    def test_journal_requires_exactly_one_run_owner(self):
        controller = module('relay_core/relay_core/doctype/relay_flow_action/relay_flow_action.py', framework(),
            {'frappe.model.document': types.SimpleNamespace(Document=object)}).RelayFlowAction
        for run, automation in (('Sim Flow', None), (None, 'Sim Automation')):
            controller.validate(Doc(run=run, automation_run=automation))
        for run, automation in ((None, None), ('Sim Flow', 'Sim Automation')):
            with self.assertRaises(ValueError): controller.validate(Doc(run=run, automation_run=automation))


class DeclaredDraftHandler(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.handler = module('relay_core/ai/actions.py', self.f)
        self.declaration = dict(action='create_draft', doctype='Payment Entry', fields=list(self.handler.PAYMENT_FIELDS))
        fields = {name: Doc(fieldname=name, permlevel=0) for name in self.handler.PAYMENT_FIELDS}
        fields.update(company=Doc(fieldname='company', fieldtype='Link', options='Company'),
            party_type=Doc(fieldname='party_type', fieldtype='Link', options='DocType'),
            party=Doc(fieldname='party', fieldtype='Dynamic Link', options='party_type'))
        self.meta = Doc(get_field=fields.get, get_permlevel_access=Mock(return_value=[0]))
        self.doc = Doc(doctype='Payment Entry', name='Sim Payment', meta=self.meta)
        self.doc.set = lambda key, value: self.doc.update({key: value})
        object.__setattr__(self.doc, 'insert', Mock(return_value=self.doc))
        self.doc.submit = Mock()
        self.f.new_doc = Mock(return_value=self.doc)
        self.values = dict(payment_type='Pay', posting_date='2026-10-25', paid_amount=1250,
            received_amount=1250, paid_from='Sim Bank', paid_to='Sim Payable')
        self.context = dict(company='Sim Company', business=['Supplier', 'Sim Supplier'])
        self.patch = patch.dict(sys.modules, {'relay_core.flows.actions': types.SimpleNamespace(
            definitions=lambda: {'create_draft': self.handler.CREATE_DRAFT}),
            'relay_core.realtime': types.SimpleNamespace(changed=Mock())})
        self.patch.start(); self.addCleanup(self.patch.stop)

    def create(self, **overrides):
        return self.handler.create_draft(action_input=self.values | overrides, idempotency_key='source-key',
            automation_run='Sim Run', ticket='Sim Ticket', execution_context=self.context, declaration=self.declaration)

    def test_normal_insert_binds_scope_and_never_submits_or_commits(self):
        self.assertEqual(self.create(), dict(doctype='Payment Entry', name='Sim Payment'))
        self.assertEqual((self.doc.company, self.doc.party_type, self.doc.party, self.doc.docstatus),
                         ('Sim Company', 'Supplier', 'Sim Supplier', 0))
        self.doc.insert.assert_called_once_with()
        self.doc.submit.assert_not_called()
        self.f.db.commit.assert_not_called()

    def test_missing_permission_and_protected_fields_fail_before_insert(self):
        self.doc.denied = True
        with self.assertRaises(PermissionError): self.create()
        self.doc.denied = False
        self.meta.get_permlevel_access.return_value = []
        with self.assertRaises(PermissionError): self.create()
        self.meta.get_permlevel_access.return_value = [0]
        for change in ({'docstatus': 1}, {'company': 'Other'}, {'paid_amount': 0}, {'paid_amount': 'unclear'}):
            with self.subTest(change=change), self.assertRaises(ValueError): self.create(**change)
        self.doc.insert.assert_not_called()

    def test_reply_is_an_intent_without_transport_or_commit(self):
        arguments = dict(idempotency_key='source-key', automation_run='Sim Run', ticket='Sim Ticket',
                         execution_context=self.context, declaration={'action': 'reply'})
        self.assertEqual(self.handler.reply(action_input={'text': 'Thanks'}, **arguments), {'reply': 'Thanks'})
        with self.assertRaises(ValueError): self.handler.reply(action_input={'text': '  '}, **arguments)
        self.f.db.commit.assert_not_called()


class ActionJournal(unittest.TestCase):
    def setUp(self):
        self.f = framework()
        self.f.get_attr = Mock()
        self.actions = module('relay_core/flows/actions.py', self.f,
            {'relay_core.permissions': types.SimpleNamespace(require_access=Mock(), readable_contact=Mock())})
        self.definition = definition()
        self.values = {'paid_amount': 1250}
        self.binding = {'scope': {'company': 'Sim Company'}, 'generation': 1}
        self.run = Doc(name='Sim Run', ticket='Sim Ticket', execution_user='operator')
        self.declaration = dict(action='draft_payment', doctype='Payment Entry', fields=['paid_amount'])
        self.journal = Doc(name='Sim Action', action_key='a'*64, input_hash=self.actions._hash(
            [self.definition['method'], self.values]), scope_fingerprint=self.actions._hash(self.binding),
            status='Awaiting approval', automation_run=self.run.name, step=0, ticket=self.run.ticket)
        self.context = patch.object(self.actions, '_ai_context', return_value=(self.run, self.definition,
            self.declaration, self.values, self.binding)).start()
        self.addCleanup(patch.stopall)
        patch.object(self.actions, '_journal', return_value=self.journal).start()
        patch.dict(sys.modules, {'relay_core.ai.tools': types.SimpleNamespace(as_user=lambda user: nullcontext())}).start()

    def test_approval_blocks_handler_and_binds_exact_evidence(self):
        self.assertEqual(self.actions.execute_ai(self.run.name, 0), {'name': 'Sim Action', 'status': 'Awaiting approval'})
        self.f.get_attr.assert_not_called()
        self.journal.status = 'Approved'
        self.journal.approval_evidence = json.dumps({'input_hash': 'changed', 'scope_fingerprint': self.journal.scope_fingerprint})
        with self.assertRaisesRegex(ValueError, 'Approval'): self.actions.execute_ai(self.run.name, 0)
        self.f.get_attr.assert_not_called()

    def test_stale_generation_and_completed_replay(self):
        self.binding['generation'] = 2
        with self.assertRaisesRegex(ValueError, 'scope'): self.actions.execute_ai(self.run.name, 0)
        self.binding['generation'] = 1
        self.definition['effect'] = 'reply'
        self.journal.status, self.journal.result = 'Completed', '{"name":"Sim Draft"}'
        self.assertEqual(self.actions.execute_ai(self.run.name, 0)['result'], {'name': 'Sim Draft'})
        self.f.get_attr.assert_not_called()

    def test_steps_cannot_skip_their_predecessor(self):
        self.f.db.exists.return_value = False
        with self.assertRaisesRegex(ValueError, 'order'): self.actions.execute_ai(self.run.name, 1)

    def test_handler_failure_rolls_back_even_worker_exit(self):
        self.f.get_attr.return_value.side_effect = SystemExit('Sim worker exit')
        commit = self.f.db.commit
        with self.assertRaises(SystemExit): self.actions._perform(self.journal, self.definition, self.values, {})
        self.f.db.rollback.assert_called_once_with(save_point='relay_action_' + 'a'*16)
        self.assertIs(self.f.db.commit, commit)
        commit.assert_not_called()

    def test_handler_commit_and_invalid_output_are_rolled_back(self):
        self.f.get_attr.return_value.side_effect = lambda **kw: self.f.db.commit()
        with self.assertRaisesRegex(ValueError, 'commit'): self.actions._perform(self.journal, self.definition, self.values, {})
        self.f.get_attr.return_value.side_effect = lambda **kw: {'docstatus': 1}
        with self.assertRaises(ValueError): self.actions._perform(self.journal, self.definition, self.values, {})
        self.assertEqual(self.f.db.rollback.call_count, 2)

    def test_success_records_result_without_committing(self):
        self.f.get_attr.return_value.return_value = {'doctype': 'Payment Entry', 'name': 'Sim Draft'}
        result = self.actions._perform(self.journal, self.definition, self.values, {})
        self.assertEqual(result['name'], 'Sim Draft')
        self.assertEqual(self.journal.status, 'Completed')
        self.f.db.commit.assert_not_called()

    def test_existing_journal_rejects_changed_inputs(self):
        # Exercise the actual shared lookup, independent of executor fixtures.
        self.actions = module('relay_core/flows/actions.py', self.f)
        self.f.db.get_value.return_value = self.journal.name
        self.f.get_doc.return_value = self.journal
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.actions._journal('a'*64, 'changed')


    def test_approval_records_actor_and_exact_hashes_without_execution(self):
        self.f.get_doc.return_value = self.journal
        self.f.utils = types.SimpleNamespace(now_datetime=lambda: '2026-10-25 12:00:00')
        result = self.actions.approve(self.journal.name, self.journal.input_hash, self.journal.scope_fingerprint)
        self.assertEqual(result, {'name': self.journal.name, 'status': 'Approved'})
        evidence = json.loads(self.journal.approval_evidence)
        self.assertEqual(evidence['actor'], 'operator')
        self.assertEqual(evidence['input_hash'], self.journal.input_hash)
        self.assertEqual(evidence['scope_fingerprint'], self.journal.scope_fingerprint)
        self.f.get_attr.assert_not_called()
        self.f.db.commit.assert_not_called()

    def test_approval_rejects_stale_hashes(self):
        self.f.get_doc.return_value = self.journal
        self.f.throw = Mock(side_effect=ValueError('stale approval'))
        with self.assertRaisesRegex(ValueError, 'stale approval'):
            self.actions.approve(self.journal.name, 'changed', self.journal.scope_fingerprint)
        self.assertEqual(self.journal.status, 'Awaiting approval')
        self.f.get_attr.assert_not_called()


class ExecutionAdapter(unittest.TestCase):
    from test_ai_skills import SharedAdapterTests
    setUp = SharedAdapterTests.setUp
    outcome = SharedAdapterTests.outcome

    def allow_reply(self):
        from relay_core.ai.actions import REPLY
        self.skill.allowed_actions = '[{"action":"reply"}]'
        self.skill.execution_policy = 'Execute'
        self.enterContext(patch('relay_core.flows.actions.definitions', return_value={'reply': REPLY}))

    def test_empty_answer_retries_once_and_recovers_reply(self):
        self.allow_reply()
        prompts = []
        responses = iter([self.outcome(dict(reply='  ', handoff=False, reason='')),
                          self.outcome(dict(reply='Thanks, noted.', handoff=False, reason=''))])
        def attempt(account, model, build, *args):
            provider = Mock()
            build(provider, {}, model)
            prompts.append(provider.build_turn.call_args.args[2])
            return next(responses)
        self.attempt.side_effect = attempt
        result = self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Thanks', 'RUN-1')
        self.assertEqual(result['actions'], [dict(action='reply', parameters={'text': 'Thanks, noted.'})])
        self.assertEqual(self.attempt.call_count, 2)
        self.assertIn('ONLY when actions are proposed', prompts[0])
        self.assertIn('Your previous answer was empty', prompts[1])
        self.assertEqual(self.attempt.call_args_list[0].args[5], self.attempt.call_args_list[1].args[5])
        self.assertEqual(self.attempt.call_args.args[4]['reference_name'], 'RUN-1')

    def test_two_empty_answers_fail_for_safe_handoff(self):
        self.attempt.side_effect = lambda *args: self.outcome(dict(reply='', handoff=False, reason=''))
        with self.assertRaisesRegex(ValueError, 'Empty skill decision'):
            self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Thanks')
        self.assertEqual(self.attempt.call_count, 2)

    def test_explicit_handoff_and_invalid_answers_are_not_retried(self):
        for value in (dict(reply='', handoff=True, reason='Staff needed'), dict(reply=None, handoff=False, reason='')):
            self.attempt.reset_mock()
            self.attempt.return_value = self.outcome(value)
            if value['handoff']:
                self.assertTrue(self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Help')['handoff'])
            else:
                with self.assertRaisesRegex(ValueError, 'Invalid skill decision'):
                    self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Help')
            self.attempt.assert_called_once()

    def test_takeover_or_deadline_prevents_empty_answer_retry(self):
        self.attempt.side_effect = lambda *args: self.outcome(dict(reply='', handoff=False, reason=''))
        self.continuation.side_effect = [None, ValueError('Taken over')]
        with self.assertRaisesRegex(ValueError, 'Taken over'):
            self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Thanks')
        self.attempt.assert_called_once()
        self.continuation.side_effect = None
        self.attempt.reset_mock()
        with patch.object(self.adapter.time, 'monotonic', side_effect=[0, 0, 0, 0, 21]):
            with self.assertRaisesRegex(ValueError, 'deadline'):
                self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Thanks', deadline=20)
        self.attempt.assert_called_once()

    def test_inline_image_observation_uses_shared_client_and_bounds(self):
        import io
        from PIL import Image
        raw = io.BytesIO(); Image.new('RGB', (20, 20)).save(raw, format='PNG')
        images = [dict(data=raw.getvalue(), mime='image/png')]
        self.attempt.return_value = self.outcome({'observation': 'INR 1250'})
        self.assertEqual(self.adapter.observe_image(self.skill, images, 'Sim Run'), 'INR 1250')
        args = self.attempt.call_args.args
        provider = types.SimpleNamespace(build_request=Mock())
        args[2](provider, {}, 'Sim Model')
        self.assertTrue(provider.build_request.call_args.args[4][0].startswith('data:image/png;base64,'))
        self.assertEqual(args[3]['attempts'], 1)
        self.assertEqual(args[4]['reference_name'], 'Sim Run')
        for bad in ([], images * 2, [dict(data=b'corrupt', mime='image/png')]):
            with self.assertRaises((ValueError, OSError)): self.adapter.observe_image(self.skill, bad)
        self.attempt.return_value = {'ok': False}
        with self.assertRaises(ValueError): self.adapter.observe_image(self.skill, images)
        self.attempt.return_value = self.outcome({'observation': 'x' * 2001})
        with self.assertRaises(ValueError): self.adapter.observe_image(self.skill, images)

    def prepare(self):
        from relay_core.flows.action_contracts import ai_inputs
        declared = dict(action='draft_payment', doctype='Payment Entry', fields=['paid_amount'])
        self.skill.allowed_actions = json.dumps([declared])
        self.skill.execution_policy = 'Execute'
        contracts = types.SimpleNamespace(action_contracts=lambda skill: [declared])
        from relay_core.flows.actions import validate_sequence
        actions = types.SimpleNamespace(validate_sequence=validate_sequence, definitions=lambda: {'draft_payment': definition()},
            proposal=lambda skill, action, parameters: dict(action=action, parameters=ai_inputs(parameters, definition(), declared)))
        patcher = patch.dict(sys.modules, {'relay_core.ai.configuration': contracts, 'relay_core.flows.actions': actions})
        patcher.start(); self.addCleanup(patcher.stop)

    def test_execute_collects_ordered_typed_proposals_without_writes(self):
        self.prepare()
        self.attempt.side_effect = [self.outcome(calls=[{'id': 'first', 'name': 'EXECUTE',
            'arguments': {'action': 'draft_payment', 'parameters': {'paid_amount': 1250}}}]),
            self.outcome({'reply': '', 'handoff': False, 'reason': ''})]
        result = self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Payment', 'RUN-1')
        self.assertEqual([step['parameters']['paid_amount'] for step in result['actions']], [1250])
        self.f.db.commit.assert_not_called()

    def test_repeated_or_out_of_order_steps_fail_before_execution(self):
        self.prepare()
        for actions in (['draft_payment', 'draft_payment'], ['reply', 'draft_payment']):
            self.attempt.side_effect = [self.outcome(calls=[dict(id=str(i), name='EXECUTE',
                arguments=dict(action=action, parameters={'paid_amount': 1250})) for i, action in enumerate(actions)]),
                self.outcome(dict(reply='', handoff=False, reason=''))]
            with self.assertRaises(ValueError):
                self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Payment', 'RUN-1')
        self.f.db.commit.assert_not_called()

    def test_final_text_requires_a_declared_reply_action(self):
        self.attempt.return_value = self.outcome(dict(reply='Undeclared reply', handoff=False, reason=''))
        with self.assertRaises(ValueError):
            self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Payment', 'RUN-1')
        self.prepare()
        with self.assertRaises(ValueError):
            self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Payment', 'RUN-1')

    def test_vision_denied_before_image_validation_or_provider(self):
        self.model.supports_vision = 0
        with patch('relay_core.automation.multimodal.image_input') as image_input:
            with self.assertRaisesRegex(ValueError, 'vision'):
                self.adapter.observe_image(self.skill, [{'data': b'image', 'mime': 'image/png'}])
            image_input.assert_not_called()
        self.attempt.assert_not_called()

    def test_execute_reply_uses_code_owned_partial_ledger_totals(self):
        from relay_core.ai.actions import REPLY
        from relay_core.ai.ledger import summarize
        self.skill.allowed_actions = '[{"action":"reply"}]'
        self.skill.execution_policy = 'Execute'
        self.enterContext(patch('relay_core.flows.actions.definitions', return_value={'reply': REPLY}))
        ledger = summarize([dict(company='Sim Company', debit='100.10', credit='40.05')], True)
        reader = types.SimpleNamespace(failed=False, evidence=[], ledger_results=[ledger])
        self.attempt.side_effect = [self.outcome(calls=[dict(id='reply', name='EXECUTE',
            arguments=dict(action='reply', parameters={'text': 'Closing balance 999999'}))]),
            self.outcome(dict(reply='', handoff=False, reason=''))]
        with patch.object(self.adapter, 'Reader', return_value=reader):
            result = self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'yes')
        text = result['actions'][0]['parameters']['text']
        self.assertIn('60.05', text)
        self.assertIn('Partial totals', text)
        self.assertNotIn('999999', text)
        self.assertEqual(result['reply'], '')

    def test_wrong_types_and_unknown_tool_arguments_fail_turn(self):
        self.prepare()
        for arguments in ({'action': 'draft_payment', 'parameters': {'paid_amount': True}},
                          {'action': 'draft_payment', 'parameters': {'paid_amount': 1250}, 'destination': 'other'}):
            self.attempt.side_effect = [self.outcome(calls=[{'id': 'first', 'name': 'EXECUTE', 'arguments': arguments}]),
                self.outcome({'reply': 'Done', 'handoff': False, 'reason': ''})]
            with self.assertRaises(ValueError):
                self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Payment', 'RUN-1')

    def test_execute_is_unavailable_without_declared_actions(self):
        self.attempt.side_effect = [self.outcome(calls=[{'id': 'first', 'name': 'EXECUTE',
            'arguments': {'action': 'draft_payment', 'parameters': {'paid_amount': 1250}}}]),
            self.outcome({'reply': 'Done', 'handoff': False, 'reason': ''})]
        with self.assertRaises(ValueError):
            self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), 'Payment', 'RUN-1')


class OrderedReplyDelivery(unittest.TestCase):
    from test_ai_skills import SkillDeliveryTests
    setUp = SkillDeliveryTests.setUp

    def test_chat_and_email_receipts_resume_chain_without_reopening_completed_run(self):
        import hashlib
        from relay_core.automation.contracts import action_key
        self.run.decision = json.dumps({'actions': [{'action': 'reply', 'parameters': {'text': 'Thanks'}}]})
        for operation, prefix in (('text', ''), ('email', 'email:')):
            action = Doc(name='Sim Receipt', operation=operation, status='Submitted', source_message=self.run.message,
                payload=json.dumps({'automation_run': self.run.name}), request_key=hashlib.sha256((
                    prefix + self.run.execution_user + ':' + action_key(self.run.message, 'event_reply_0')).encode()).hexdigest())
            self.f.get_doc.side_effect = lambda dt, name: action
            self.run.status = 'Delivering'
            self.service.complete_delivery(action.name)
            self.assertEqual(self.run.status, 'Pending')
            self.assertEqual(self.f.enqueue.call_args.kwargs['name'], self.run.name)
            self.run.status = 'Completed'
            self.f.enqueue.reset_mock()
            self.service.complete_delivery(action.name)
            self.assertEqual(self.run.status, 'Completed')
            self.f.enqueue.assert_not_called()

    def test_uncertain_reply_stops_chain_and_recovery_reuses_step_key(self):
        decision = self.service.decide.return_value | {'reply': '', 'actions': [
            {'action': 'reply', 'parameters': {'text': 'Thanks'}},
            {'action': 'create_draft', 'parameters': {'paid_amount': 1250}}]}
        self.run.decision = json.dumps(decision)
        execute = Mock(side_effect=lambda name, step: dict(status='Completed', result=
            {'reply': 'Thanks'} if step == 0 else {'doctype': 'Payment Entry', 'name': 'Sim Draft'}))
        with patch.dict(sys.modules, {'relay_core.flows.actions': types.SimpleNamespace(execute_ai=execute, validate_sequence=Mock())}):
            self.send.return_value = {'status': 'Uncertain'}
            self.service.process(self.run.name)
            self.assertEqual(self.run.status, 'Delivering')
            execute.assert_called_once_with(self.run.name, 0)
            first_key = self.send.call_args.args[3]
            self.run.status = 'Pending'
            self.send.return_value = {'status': 'Submitted'}
            self.service.process(self.run.name)
            self.assertEqual(self.run.status, 'Completed')
            self.assertEqual(execute.call_args.args, (self.run.name, 1))
            self.assertEqual(self.send.call_args.args[3], first_key)
            self.handoff.assert_not_called()

    def test_draft_only_step_does_not_invent_an_acknowledgement(self):
        self.run.decision = json.dumps(self.service.decide.return_value | {'reply': '', 'actions': [
            {'action': 'create_draft', 'parameters': {'paid_amount': 1250}}]})
        execute = Mock(return_value=dict(status='Completed', result={'doctype': 'Payment Entry', 'name': 'Sim Draft'}))
        with patch.dict(sys.modules, {'relay_core.flows.actions': types.SimpleNamespace(execute_ai=execute, validate_sequence=Mock())}):
            self.service.process(self.run.name)
        self.assertEqual(self.run.status, 'Completed')
        self.send.assert_not_called()


class VerifiedContactExecution(unittest.TestCase):
    """Run context, execution, journal and dispatch together with a local transport fake."""
    def setUp(self):
        from test_ai_skills import ConversationIdentityTests
        from relay_core.ai.actions import REPLY, reply
        from relay_core import business_access
        ConversationIdentityTests.setUp(self)
        self.skill.update(name='Sim Skill', mode='Automatic', enabled=1, modified='v1',
            execution_policy='Execute', allowed_tools='[]', allowed_actions='[{"action":"reply"}]',
            business_doctype='Customer')
        self.person.update(mobile_no=self.message.sender_endpoint)
        self.business.update(name='Sim Customer', modified='v1')  # No phone field on Customer.
        self.message.update(business_doctype='Customer', business_name=self.business.name)
        self.run = Doc(name='Sim Run', status='Pending', skill=self.skill.name, skill_version='v1',
            execution_user='partner', message=self.message.name, attempts=0, generation=0,
            ticket='Sim Ticket', stage='Event', message_hash='hash')
        self.contact = Doc(name='CONTACT-1', contact=self.person.name, automation_generation=0, automation_paused=0)
        self.ticket = Doc(name='Sim Ticket', ai_disabled=0, company='Sim Company',
            conversation_key=self.message.conversation_key, business_doctype='Customer',
            business_name=self.business.name, generation=0)
        original = self.f.get_doc.side_effect
        docs = {'Relay AI Skill': self.skill, 'Relay Automation Run': self.run, 'Relay Contact': self.contact,
                'Relay Ticket': self.ticket, 'Customer': self.business}
        self.f.get_doc.side_effect = lambda dt, name: docs[dt] if dt in docs else original(dt, name)
        self.linked = True
        self.f.get_all.side_effect = lambda dt, **kw: ['Customer'] if dt == 'Relay Contact Type' else (
            [Doc(link_doctype='Customer', link_name=self.business.name)] if self.linked else [])
        self.f.db.get_value.side_effect = lambda dt, *args, **kw: (self.binding if dt == 'Relay Contact Endpoint'
            else self.person.name if dt == 'Relay Contact' else 1)
        self.f.db.exists.return_value = True
        self.f.has_permission = Mock(return_value=True)
        self.f.get_attr = Mock(return_value=reply)
        self.enterContext(patch.object(business_access, 'frappe', self.f))
        self.service.lock_run = lambda name: self.run
        self.service.lock_contact = lambda name: self.contact
        self.service.message_hash = lambda message: 'hash'
        self.service.latest_message = lambda message: True
        self.enterContext(patch('relay_core.tickets.check_episode'))
        self.actions = module('relay_core/flows/actions.py', self.f)
        self.actions.definitions = lambda **kw: {'reply': REPLY}
        self.journal = Doc(action_key='a' * 64, status='Pending')
        def journal(key, input_hash, **values):
            self.journal.update(name='Sim Action', action_key=key, input_hash=input_hash, **values)
            return self.journal
        self.actions._journal = journal
        self.send, self.handoff = Mock(return_value={'status': 'Submitted'}), Mock()
        automation = types.SimpleNamespace(lock_run=self.service.lock_run, reserve_attempt=Mock())
        self.enterContext(patch.dict(sys.modules, {'relay_core.business_access': business_access,
            'relay_core.ai.service': self.service, 'relay_core.ai.tools': self.tools,
            'relay_core.flows.actions': self.actions, 'relay_core.automation.service': automation,
            'relay_core.messaging': types.SimpleNamespace(send=self.send),
            'relay_core.ai.handoff': types.SimpleNamespace(handoff=self.handoff)}))
        scope = self.service.context(self.skill, self.message)[2]
        self.run.decision = json.dumps(dict(reply='', handoff=False, reason='', user='partner', reads=[],
            scope=self.tools.fingerprint(scope), actions=[dict(action='reply', parameters={'text': 'Noted: 1250 received.'})]))

    def test_contact_only_number_reaches_reply_without_customer_mapping(self):
        self.service.process(self.run.name)
        self.assertEqual(self.run.status, 'Completed')
        self.assertEqual(self.journal.status, 'Completed')
        self.send.assert_called_once()
        self.assertEqual(self.send.call_args.args[2], {'text': 'Noted: 1250 received.'})
        self.handoff.assert_not_called()

    def test_unlinked_contact_or_revoked_endpoint_never_executes_or_replies(self):
        for linked, verified in ((False, 1), (True, 0)):
            with self.subTest(linked=linked, verified=verified):
                self.linked, self.binding.verified = linked, verified
                self.service.process(self.run.name)
                self.send.assert_not_called()
                self.f.get_attr.assert_not_called()
        self.assertEqual(self.handoff.call_count, 2)

    def test_unrelated_read_identity_mapping_does_not_block_reply(self):
        with patch('relay_core.ai.configuration.read_contracts', return_value=[
                dict(doctype='Sales Order', identity_anchor='Customer',
                     identity_fields={'WhatsApp': 'customer_pos_id'})]), \
             patch('relay_core.business_access.scoped_document', side_effect=ValueError('Identity does not match')) as scoped:
            self.service.process(self.run.name)
        scoped.assert_not_called()
        self.assertEqual(self.run.status, 'Completed')
        self.send.assert_called_once()
        self.handoff.assert_not_called()

    def test_only_action_target_identity_mappings_are_enforced(self):
        action = definition('None')
        self.actions.definitions = lambda **kw: {'draft_payment': action}
        self.skill.allowed_actions = json.dumps([dict(action='draft_payment', doctype='Payment Entry', fields=['paid_amount'])])
        plan = json.loads(self.run.decision)
        plan['actions'] = [dict(action='draft_payment', parameters={'paid_amount': 1250})]
        self.run.decision = json.dumps(plan)
        self.f.get_meta.return_value = Doc(get_field=lambda key: Doc(fieldtype='Currency'))
        self.enterContext(patch('relay_core.ai.configuration.frappe', self.f))
        refs = [dict(doctype='Sales Order', identity_anchor='Customer', identity_fields={'WhatsApp': 'customer_pos_id'})]
        with patch('relay_core.ai.configuration.read_contracts', return_value=refs), \
             patch('relay_core.business_access.scoped_document', side_effect=ValueError('Identity does not match')) as scoped:
            self.assertEqual(self.actions._ai_context(self.run.name, 0)[3], {'paid_amount': 1250})
            scoped.assert_not_called()
            refs.append(dict(doctype='Payment Entry', identity_anchor='Customer', identity_fields={'WhatsApp': 'phone'}))
            with self.assertRaisesRegex(ValueError, 'Identity does not match'):
                self.actions._ai_context(self.run.name, 0)
            scoped.assert_called_once_with('Customer', self.business.name, {'phone': self.message.sender_endpoint})

    def test_execution_failure_logs_traceback_and_hands_off_specific_reason(self):
        self.f.get_attr.return_value = Mock(side_effect=ValueError('Local reply handler failed'))
        self.service.process(self.run.name)
        self.send.assert_not_called()
        self.assertEqual(self.handoff.call_args.args[2], 'Local reply handler failed')
        log = self.f.log_error.call_args.kwargs
        self.assertEqual(log['reference_name'], self.run.name)
        self.assertEqual(log['reference_doctype'], 'Relay Automation Run')
        self.assertIn('ValueError: Local reply handler failed', log['message'])


    def test_disabled_contact_user_is_logged_during_matching_and_saved_on_run(self):
        automation = sys.modules['relay_core.automation.service']
        automation.episode = Mock(return_value=self.ticket)
        automation.triage = lambda run, message, reason: run.update(reason=reason, status='Handoff')
        self.f.QueryDeadlockError = type('QueryDeadlockError', (Exception,), {})
        self.f.db.get_value.side_effect = lambda dt, *args, **kw: (self.binding if dt == 'Relay Contact Endpoint'
            else self.person.name if dt == 'Relay Contact' else 0 if dt == 'User' else 1)
        with patch.object(self.service, 'continue_search', return_value=False), \
             patch('relay_core.ai.matching.candidates', return_value=[self.skill]):
            self.service.admit(self.run)
        self.assertEqual(self.run.reason, 'Contact is linked to a disabled portal user')
        self.assertEqual(json.loads(self.run.match_result)['reason'], self.run.reason)
        self.assertIn(self.run.reason, self.f.log_error.call_args.kwargs['message'])
        self.assertEqual(self.f.log_error.call_args.kwargs['reference_name'], self.run.name)
        self.send.assert_not_called()

    def test_failed_decision_and_matching_preserve_call_logs_and_failure_record(self):
        for phase in ('decision', 'matching'):
            with self.subTest(phase=phase):
                pending, durable = [], []
                self.f.db.commit.side_effect = lambda: (durable.extend(pending), pending.clear())
                self.f.db.rollback.side_effect = lambda **kw: pending.clear()
                self.f.log_error.side_effect = lambda **kw: pending.append(('traceback', kw['message']))
                def fail(*args, **kwargs):
                    pending.append(('Document AI Call Log', phase))
                    raise ValueError('Provider returned no answer')
                def handoff(run, skill, reason):
                    run.update(status='Handoff', reason=reason)
                    pending.append(('failure', reason))
                self.run.update(status='Pending', decision=None, attempts=0)
                self.handoff.side_effect = handoff
                if phase == 'decision':
                    with patch.object(self.service, 'decide', side_effect=fail):
                        self.service.process(self.run.name)
                else:
                    automation = sys.modules['relay_core.automation.service']
                    automation.episode = Mock(return_value=self.ticket)
                    automation.triage = handoff
                    self.f.QueryDeadlockError = type('QueryDeadlockError', (Exception,), {})
                    with patch.object(self.service, 'continue_search', return_value=False), \
                         patch('relay_core.ai.matching.candidates', return_value=[self.skill]), \
                         patch.object(self.service, 'conversation_history', return_value=[]), \
                         patch('relay_core.ai.matching.select', side_effect=fail):
                        self.service.admit(self.run)
                self.assertIn(('Document AI Call Log', phase), durable)
                self.assertIn(('failure', 'Provider returned no answer'), durable)
                self.assertTrue(any(kind == 'traceback' and 'ValueError: Provider returned no answer' in value
                                    for kind, value in durable))
                self.assertEqual(self.run.status, 'Handoff')
                self.send.assert_not_called()

    def test_failure_logging_rolls_back_only_if_commit_fails(self):
        self.f.db.commit.side_effect = RuntimeError('Transaction unavailable')
        try:
            raise ValueError('Original provider failure')
        except ValueError as exc:
            reason = self.service.log_failure(self.run, exc)
        self.assertEqual(reason, 'Original provider failure')
        self.f.db.rollback.assert_called_once_with()
        self.assertIn('ValueError: Original provider failure', self.f.log_error.call_args.kwargs['message'])

    def test_link_removed_during_handler_prevents_delivery(self):
        def reply(**kwargs):
            self.linked = False
            return {'reply': 'Noted.'}
        self.f.get_attr.return_value = reply
        self.service.process(self.run.name)
        self.send.assert_not_called()
        self.f.db.rollback.assert_any_call(save_point='relay_action_' + self.journal.action_key[:16])
        self.handoff.assert_called_once()
