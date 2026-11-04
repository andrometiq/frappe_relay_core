"""Loop assembly: code tools in the reply loop, the turn cap, run records, the provider guard and delivery rechecks."""
import json
import types
import unittest
from typing import Annotated
from unittest.mock import Mock, patch

from test_ai_skills import Doc
from relay_core.ai.registry import ToolContext, relay_tool


@relay_tool(audience='customer', label='Order status', business_doctype='Supplier')
def order_status(order: Annotated[str, 'Order number'], *, ctx: ToolContext) -> dict:
    """The sender's own order status."""
    if order == 'missing':
        raise ValueError('Order PO-NORTHWIND-9 of Northwind Hosiery is not readable')
    if order == 'crash':
        raise RuntimeError('Database is down')
    return {'order': order, 'status': 'Dispatched', 'contact': '919000000101', 'rows': ['x' * 9000]}


@relay_tool(audience='customer', label='Load playbook')
def load_playbook(name: Annotated[str, 'A playbook name'], *, ctx: ToolContext) -> str:
    """A stand-in with the built-in tool's name."""
    return 'Greet Sam Customer by name.'


def answer(reply='Your order is dispatched.', handoff=False, reason=''):
    return dict(reply=reply, handoff=handoff, reason=reason)


class LoopCase(unittest.TestCase):
    from test_ai_skills import SharedAdapterTests
    shared_setup = SharedAdapterTests.setUp
    outcome = SharedAdapterTests.outcome

    def setUp(self):
        self.shared_setup()
        from relay_core.ai.actions import REPLY
        self.skill.update(name='Acme Support', allowed_actions='[{"action":"reply"}]', execution_policy='Execute')
        self.enterContext(patch('relay_core.flows.actions.definitions', return_value={'reply': REPLY}))
        self.tools = [('acme.order_status', order_status)]
        self.enterContext(patch('relay_core.ai.registry.builtin.skill_tools', side_effect=lambda skill: self.tools))
        self.enterContext(patch('relay_core.ai.registry.tool.load',
                                side_effect=lambda key, skill, audience: dict(self.tools)[key]))

    def call(self, name='order_status', **arguments):
        return {'id': 'call-' + name, 'name': name, 'arguments': arguments}

    def complete(self, record=None, text='Where is PO-1?'):
        return self.adapter.complete(self.skill, 'partner', ('Supplier', 'SUP-A'), text, 'RUN-1',
                                     scope={'company': 'Acme Textiles'}, record=record)


class ToolLoopTests(LoopCase):
    def test_turn_cap_stops_at_the_skill_limit_and_the_run_hands_off(self):
        self.skill.max_tool_calls = 2
        self.attempt.side_effect = lambda *args: self.outcome(calls=[self.call(order='PO-1')])
        with self.assertRaisesRegex(ValueError, 'AI provider error: Model called tools after the limit'):
            self.complete()
        # Two tool turns, then one final turn that may not call tools.
        self.assertEqual(self.attempt.call_count, 3)
        provider = Mock()
        self.attempt.call_args.args[2](provider, {}, 'test-model')
        self.assertTrue(provider.build_turn.call_args.args[-1])

    def test_turn_cap_defaults_to_4_and_never_passes_6(self):
        from relay_core.ai.registry.loop import tool_limit
        self.assertEqual([tool_limit(Doc(max_tool_calls=value)) for value in (None, 0, 2, 6, 9)], [4, 4, 2, 6, 6])

    def test_takeover_between_tool_turns_stops_the_run(self):
        self.continuation.side_effect = [None, None, None, ValueError('Taken over')]
        self.attempt.side_effect = [self.outcome(calls=[self.call(order='PO-1')]), self.outcome(answer())]
        with self.assertRaisesRegex(ValueError, 'Taken over'):
            self.complete()
        self.assertEqual(self.attempt.call_count, 1)

    def test_tool_result_is_capped_and_the_record_holds_no_row_data(self):
        from relay_core.ai.registry.builtin import RunRecord
        record = RunRecord()
        seen = []
        self.attempt.side_effect = [self.outcome(calls=[self.call(order='PO-1')]), self.outcome(answer())]
        self.provider.continuation = lambda result, outputs: seen.extend(outputs) or []
        self.complete(record)
        self.assertLessEqual(len(seen[0][1]), 4000)
        self.assertTrue(seen[0][1].endswith('[truncated]'))
        self.assertEqual(len(record.tool_calls), 1)
        row = record.tool_calls[0]
        self.assertEqual(set(row), {'name', 'arguments_sha256', 'status', 'ms'})
        self.assertEqual((row['name'], row['status']), ('order_status', 'ok'))
        self.assertNotIn('PO-1', json.dumps(record.tool_calls))
        self.assertNotIn('Dispatched', json.dumps(record.tool_calls))
        self.assertEqual(record.usage['turns'], 2)

    def test_app_tool_errors_reach_the_model_as_fixed_text_and_hand_off(self):
        seen = []
        self.provider.continuation = lambda result, outputs: seen.extend(outputs) or []
        self.enterContext(patch('relay_core.ai.registry.builtin.frappe'))
        for order in ('missing', 'crash'):
            seen.clear()
            self.attempt.side_effect = [self.outcome(calls=[self.call(order=order)]),
                                        self.outcome(answer('Your order is on its way.'))]
            with self.subTest(order=order), self.assertRaisesRegex(ValueError, 'Business data authorization failed'):
                self.complete()
            self.assertEqual(json.loads(seen[0][1]), {'error': 'This tool is unavailable'})

    def test_app_tool_results_allow_their_contact_values_in_the_reply(self):
        self.attempt.side_effect = [self.outcome(calls=[self.call(order='PO-1')]),
                                    self.outcome(answer('Call 919000000101 about PO-1.'))]
        self.assertFalse(self.complete()['handoff'])
        self.attempt.side_effect = [self.outcome(answer('Call 919000000101 about PO-1.'))]
        self.assertTrue(self.complete()['handoff'])

    def test_unknown_tool_names_fail_the_run(self):
        self.attempt.side_effect = [self.outcome(calls=[self.call('sql', query='select 1')]), self.outcome(answer())]
        with self.assertRaisesRegex(ValueError, 'Invalid search call'):
            self.complete()

    def test_model_arguments_cannot_choose_another_tool(self):
        self.tools.append(('acme.secret', load_playbook))
        self.attempt.side_effect = [self.outcome(calls=[self.call(order='PO-1', key='acme.secret')]),
                                    self.outcome(answer())]
        seen = []
        self.provider.continuation = lambda result, outputs: seen.extend(outputs) or []
        with self.assertRaisesRegex(ValueError, 'Business data authorization failed'):
            self.complete()
        self.assertEqual(json.loads(seen[0][1]), {'error': 'This tool is unavailable'})

    def test_two_tools_with_one_name_fail_closed(self):
        self.tools.append(('other.order_status', order_status))
        with self.assertRaisesRegex(ValueError, 'share a name'):
            self.complete()


class OfferTests(unittest.TestCase):
    def core(self, skill, run='RUN-1', bound_playbooks=()):
        from relay_core.ai.registry.builtin import CoreTools
        with patch('relay_core.ai.registry.builtin.copy_texts', return_value=tuple(bound_playbooks)):
            core = CoreTools(skill, ('Customer', 'Kestrel Traders'), {'company': 'Acme Textiles'}, Mock(), [], Mock(), None)
        context = ToolContext(run=run, skill=skill, user='sam@example.com', business=('Customer', 'Kestrel Traders'),
                              scope={'company': 'Acme Textiles'})
        agent = types.SimpleNamespace(Tool=lambda *args: args)
        return core, [row[0] for row in core.add_code_tools(agent, context)]

    def setUp(self):
        from relay_core.ai import fact_memory, playbooks
        from relay_core.ai.knowledge_base import retriever
        self.builtins = [('erpnext.search_knowledge', retriever.search_knowledge),
                         ('erpnext.load_playbook', playbooks.load_playbook), ('erpnext.remember', fact_memory.remember)]
        self.enterContext(patch('relay_core.ai.registry.builtin.skill_tools', return_value=self.builtins))
        self.offered = self.enterContext(patch('relay_core.ai.knowledge_base.retriever.is_offered', return_value=True))
        self.enterContext(patch('relay_core.ai.knowledge_base.retriever.description', return_value='Search'))
        self.enterContext(patch('relay_core.ai.registry.builtin.frappe',
                                types.SimpleNamespace(db=types.SimpleNamespace(db_type='mariadb'))))
        self.enterContext(patch('relay_core.ai.fact_memory.frappe',
                                types.SimpleNamespace(db=types.SimpleNamespace(db_type='mariadb'))))

    def test_built_in_tools_need_their_run_conditions(self):
        skill = Doc(memory_enabled=1)
        self.assertEqual(self.core(skill, bound_playbooks=['Greet']),
                         (unittest.mock.ANY, ['search_knowledge', 'load_playbook', 'remember']))
        self.assertEqual(self.core(skill, run=None)[1], ['search_knowledge'])
        self.offered.return_value = False
        self.assertEqual(self.core(Doc())[1], [])

    def test_knowledge_results_are_contact_evidence_only(self):
        core, names = self.core(Doc())
        with patch('relay_core.ai.registry.tool.call', return_value={'results': ['Desk 919000000101']}):
            core.call('erpnext.search_knowledge', self.builtins[0][1], {'query': 'desk'})
        self.assertEqual((core.evidence, core.read_results, core.knowledge), ([{'results': ['Desk 919000000101']}], [], []))

    def test_built_in_tool_errors_keep_their_fixed_text(self):
        core, names = self.core(Doc(memory_enabled=1))
        with patch('relay_core.ai.registry.tool.call', side_effect=ValueError('Memory is full: revise a fact')):
            with self.assertRaisesRegex(ValueError, 'Memory is full'):
                core.call('erpnext.remember', self.builtins[2][1], {'content': 'Prefers Sampleville'})

    def test_no_tool_after_an_execute_proposal(self):
        core, names = self.core(Doc())
        core.actions.append({'action': 'reply'})
        with self.assertRaisesRegex(ValueError, 'before EXECUTE'):
            core.call('erpnext.search_knowledge', self.builtins[0][1], {'query': 'desk'})


class SkillToolTests(unittest.TestCase):
    def test_skill_offers_wanted_built_ins_and_app_read_tools_only(self):
        from relay_core.ai.registry import builtin
        loaded = {}
        def load(key, skill, audience):
            loaded[key] = audience
            return {'erpnext.search_knowledge': builtin.retriever.search_knowledge,
                    'erpnext.remember': builtin.remember, 'erpnext.my_tickets': builtin.my_tickets}[key]
        drafts = Mock(kind='action', function=Mock())
        with patch('relay_core.ai.registry.tool.load', side_effect=load), \
                patch('relay_core.ai.registry.sync.tool_key', side_effect=lambda app, tool: 'erpnext.' + tool.name), \
                patch('relay_core.ai.registry.tool.offered', return_value=[
                    ('acme.order_status', order_status), ('acme.drafts', drafts),
                    ('erpnext.load_playbook', builtin.load_playbook)]):
            found = builtin.skill_tools(Doc(knowledge_bases=[Doc(knowledge_base='KB-1')], memory_enabled=1))
        self.assertEqual([key for key, tool in found],
                         ['erpnext.search_knowledge', 'erpnext.remember', 'erpnext.my_tickets', 'acme.order_status'])
        self.assertEqual(set(loaded.values()), {'customer'})


class ProviderGuardTests(LoopCase):
    def test_only_allowed_auth_types_reach_a_provider(self):
        self.account.auth_type = 'API Key'
        for setting in (None, '', 'ChatGPT Login'):
            self.f.db.get_single_value.return_value = setting
            with self.assertRaisesRegex(ValueError, 'auth type is not allowed'):
                self.adapter.route('MODEL-1')
        self.f.db.get_single_value.return_value = 'ChatGPT Login\nAPI Key'
        self.assertEqual(self.adapter.route('MODEL-1')[0], self.account)

    def test_refused_model_never_calls_the_provider(self):
        self.account.auth_type = 'Setup Token'
        with self.assertRaisesRegex(ValueError, 'auth type is not allowed'):
            self.complete()
        self.attempt.assert_not_called()


class DeliveryTests(unittest.TestCase):
    def test_a_knowledge_source_that_left_the_scope_stops_delivery(self):
        from relay_core.ai.knowledge_base import retriever
        skill = Doc(knowledge_bases=[Doc(knowledge_base='KB-1')])
        with patch.object(retriever, 'enabled_bases', return_value=['KB-1']), \
                patch.object(retriever, 'sources', return_value=['SRC-1']):
            retriever.check_sources(skill, ('Customer', 'Kestrel Traders'), 'Acme Textiles', ['SRC-1'])
            with self.assertRaisesRegex(ValueError, 'knowledge source'):
                retriever.check_sources(skill, ('Customer', 'Kestrel Traders'), 'Acme Textiles', ['SRC-1', 'SRC-2'])

    def test_tool_hashes_join_the_capability_hashes(self):
        from relay_core.ai import service
        with patch('relay_core.ai.tools.contracts', return_value=[]), \
                patch('relay_core.ai.registry.builtin.skill_tools', return_value=[('acme.order_status', order_status)]):
            hashes = service.capability_hashes(Doc(allowed_actions='[]'))
        self.assertEqual(hashes, {'acme.order_status': order_status.code_hash})


class EpisodeFoldTests(unittest.TestCase):
    def test_long_episodes_queue_one_fold(self):
        from relay_core.ai import memory
        record = memory.Memory.__new__(memory.Memory)
        record.key = {'business_doctype': 'Customer', 'business_name': 'Kestrel Traders', 'address': '919999999999',
                      'company': 'Acme Textiles', 'provider': 'WhatsApp'}
        record.get_cursor = Mock(return_value='MSG-1')
        with patch.object(memory, 'memory_model', return_value='Memory Model'), \
                patch.object(memory, 'window_start', return_value='2026-11-01'), \
                patch.object(memory, 'queue') as queue:
            for count, queued in ((40, False), (41, True)):
                record.messages = Mock(return_value=[{}] * count)
                memory.fold_long_episode(record)
                self.assertEqual(queue.called, queued)
            queue.assert_called_once_with('fold', ('Customer', 'Kestrel Traders', '919999999999', 'Acme Textiles',
                                                   'WhatsApp'))
            self.assertEqual(record.messages.call_args.kwargs, {'after': 'MSG-1', 'limit': 41})

    def test_no_memory_model_queues_nothing(self):
        from relay_core.ai import memory
        with patch.object(memory, 'memory_model', return_value=None), patch.object(memory, 'queue') as queue:
            memory.fold_long_episode(Mock())
        queue.assert_not_called()


if __name__ == '__main__':
    unittest.main()
