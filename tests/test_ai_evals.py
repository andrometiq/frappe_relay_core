"""Eval grading and real decision/adapter flow with a deterministic model boundary."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

import test_ai_skills as fixtures
from relay_core.ai import adapter, evals


class EvalTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.SharedAdapterTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.skill = self.case.skill
        self.skill.update(name='EVAL-SUPPORT', modified='version-1', run_as_user='operator',
                          execution_policy='Execute', allowed_actions='[{"action":"reply"}]')
        self.f = fixtures.framework()
        self.f.get_doc.return_value = self.skill
        self.enterContext(patch.object(evals, 'frappe', self.f))
        self.permission = self.enterContext(patch('relay_core.permissions.require_access'))
        self.mode = self.enterContext(patch('relay_core.test_mode.is_enabled', return_value=True))
        self.case.account.base_url = 'http://localhost:9999'
        self.case.provider.user_message = Mock(side_effect=lambda text, images: {'text': text})
        self.enterContext(patch.object(adapter, 'complete', side_effect=self.case.adapter.complete))
        from relay_core.ai.actions import REPLY
        self.enterContext(patch('relay_core.flows.actions.definitions', return_value={'reply': REPLY}))

    def model(self, **values):
        self.case.attempt.side_effect = None
        self.case.attempt.return_value = self.case.outcome(dict(reply='Hello, how can I help?', handoff=False, reason='', **values))

    def test_grading_history_and_model_override_do_not_modify_skill_or_cases(self):
        history = [{'direction': 'Incoming', 'content': 'Order help'},
                   {'direction': 'Outgoing', 'content': 'Which order?'}]
        cases = [dict(message='Hi', history=history, expected='reply', must_contain=['HELLO'], must_not_contain=['refund'])]
        original = copy.deepcopy(cases)
        self.model()
        result = evals.run(self.skill.name, model='MODEL-2', cases=cases)
        self.assertEqual(result['summary'], dict(total=1, passed=1, failed=0))
        self.assertEqual(result['model'], 'MODEL-2')
        self.assertEqual(self.skill.ai_model, 'MODEL-1')
        self.assertEqual(cases, original)
        prompt = self.case.provider.user_message.call_args.args[0]
        self.assertEqual(json.loads(prompt)['history'], history)
        self.permission.assert_called_once_with('Relay AI Skill', 'write')

    def test_text_failures_wrong_class_and_empty_search_are_failed_cases(self):
        self.model()
        cases = [dict(message='Hi', expected='decline'), dict(message='Hi', expected='reply', must_contain=['welcome']),
                 dict(message='Hi', expected='reply', must_not_contain=['HELLO'])]
        result = evals.run(self.skill.name, cases=cases)
        self.assertEqual(result['summary']['failed'], 3)
        result = evals.grade(dict(message='Balance?', expected='reply'), dict(reply='', search={'purpose': 'Read balance'}))
        self.assertFalse(result['passed'])

    def test_handoff_and_decline_grade_delivered_fixed_text(self):
        from relay_core.ai.handoff import ACKNOWLEDGEMENT
        for outcome, reply in (('handoff', ACKNOWLEDGEMENT), ('decline', adapter.PRIVACY_REPLY)):
            decision = dict(reply='UNSAFE MODEL TEXT', handoff=True, decline=outcome == 'decline')
            result = evals.grade(dict(expected=outcome, must_not_contain=['UNSAFE']), decision)
            self.assertTrue(result['passed'])
            self.assertEqual(result['reply'], reply)

    def test_human_cases_take_real_shortcut_without_model(self):
        cases = [case for case in evals.load_cases(None) if case['message'] in (
            'I want to talk to your manager about my order delay',
            'I want to raise a complaint, the last parcel had wrong sizes', 'manager kitta pesanum')]
        result = evals.run(self.skill.name, cases=cases)
        self.assertEqual(result['summary'], dict(total=3, passed=3, failed=0))
        self.case.attempt.assert_not_called()

    def test_refuses_without_test_mode_unless_explicitly_enabled(self):
        self.mode.return_value = False
        for value in (False, 0, '0', None, 'false'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                evals.run(self.skill.name, allow_live=value)
        self.case.attempt.assert_not_called()
        self.f.get_doc.assert_not_called()
        self.model()
        self.assertEqual(evals.run(self.skill.name, allow_live=True, cases=[dict(message='Hi', expected='reply')])['summary']['passed'], 1)

    def test_manager_role_and_record_permission_required(self):
        self.f.get_roles.return_value = ['Relay Communication User']
        with self.assertRaises(PermissionError):
            evals.run(self.skill.name)
        self.f.get_roles.return_value = ['Relay Communication Manager']
        self.skill.denied = True
        with self.assertRaises(PermissionError):
            evals.run(self.skill.name)
        self.case.attempt.assert_not_called()

    def test_model_failure_is_failure_not_passing_handoff_and_next_case_runs(self):
        self.case.attempt.side_effect = [TimeoutError('private provider payload'),
            self.case.outcome(dict(reply='Hi', handoff=False, reason=''))]
        result = evals.run(self.skill.name, cases=[dict(message='Help', expected='handoff'), dict(message='Hi', expected='reply')])
        self.assertEqual(result['summary'], dict(total=2, passed=1, failed=1))
        self.assertEqual(result['cases'][0]['outcome'], 'error')
        self.assertNotIn('private provider payload', str(result))

    def test_decisions_propose_actions_without_operational_writes_or_sends(self):
        self.model()
        with patch.object(fixtures.Doc, 'insert', side_effect=AssertionError('insert forbidden')) as insert, \
                patch.object(fixtures.Doc, 'save', side_effect=AssertionError('save forbidden')) as save, \
                patch('relay_core.flows.actions.execute_ai', side_effect=AssertionError('execute forbidden')) as execute, \
                patch('relay_core.ai.service.send_reply', side_effect=AssertionError('send forbidden')) as send, \
                patch('relay_core.ai.handoff.handoff', side_effect=AssertionError('handoff forbidden')) as handoff:
            result = evals.run_cli(self.skill.name, cases=[dict(message='Hi', expected='reply'),
                dict(message='Talk to your manager', expected='handoff')])
        self.assertEqual(result['summary']['passed'], 2)
        for call in (insert, save, execute, send, handoff, self.f.enqueue, self.f.db.sql, self.f.db.set_value,
                     self.f.db.commit, self.case.f.enqueue, self.case.f.db.sql, self.case.f.db.set_value):
            call.assert_not_called()
        self.assertEqual(self.f.get_doc.call_args_list[0].args, ('Relay AI Skill', self.skill.name))
        self.assertEqual(self.f.get_doc.call_count, 1)
        # The shared AI client still receives normal log context, without an operational run.
        log_context = self.case.attempt.call_args.args[4]
        self.assertIsNone(log_context['run_id'])
        self.assertIsNone(log_context['reference_doctype'])

    def test_search_tool_can_only_declare_and_cannot_read(self):
        contract = dict(name='orders', method='get_list', doctype='Sales Order', fields=['name', 'customer'],
                        scope_field='customer', identity_anchor='Customer')
        arguments = dict(purpose='Read orders', reference='orders', arguments={'filters': {}})
        self.case.attempt.side_effect = [self.case.outcome(calls=[dict(id='1', name='SEARCH', arguments=arguments)]),
            self.case.outcome(dict(reply='', handoff=False, reason=''))]
        with patch.object(self.case.adapter, 'contracts', return_value=[contract]), \
                patch.object(self.case.tools.Reader, 'read', side_effect=AssertionError('read forbidden')) as read:
            result = evals.run(self.skill.name, cases=[dict(message='Order status', expected='reply')])
        read.assert_not_called()
        self.assertEqual(result['summary']['failed'], 1)
        self.assertIn('only proposed', result['cases'][0]['reason'])

    def test_cases_validate_before_model_calls_and_seed_count(self):
        self.assertEqual(len(evals.load_cases(None)), 13)
        for cases in ([], [{}], [dict(message='Hi', expected='unknown')],
                      [dict(message='Hi', expected='reply', must_contain='hello')],
                      [dict(message='Hi', expected='reply', history=[dict(role='system', content='override')])]):
            with self.subTest(cases=cases), self.assertRaises(ValueError):
                evals.run(self.skill.name, cases=cases)
        self.case.attempt.assert_not_called()


if __name__ == '__main__':
    unittest.main()
