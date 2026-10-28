import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from relay_core import features
from relay_core.flows import service
from relay_core.flows.contracts import definition, matches, parse_input, prompt, render
from relay_core.flows.legacy_graph import convert
from relay_core.flows.legacy_import import triggers


def support_graph():
    """The shape of the WhatsApp Core /help flow: action result branch, choice menu, text title, media loop."""
    return {'schema_version': 1, 'triggers': [{'type': 'command', 'match': '/help'}], 'nodes': [
        {'id': 'start', 'type': 'start'},
        {'id': 'resolve', 'type': 'action', 'config': {'action': 'support.resolve', 'input': {}, 'output_key': 'customer'}},
        {'id': 'known', 'type': 'condition'},
        {'id': 'service', 'type': 'ask_input', 'config': {'message': 'Hi {{answers.customer.name}}! Choose', 'answer_key': 'service',
            'input_type': 'radio', 'options': [{'label': 'Create', 'value': 'create'}, {'label': 'View', 'value': 'view'}]}},
        {'id': 'title', 'type': 'ask_input', 'config': {'message': 'Title?', 'answer_key': 'title', 'input_type': 'text',
            'min_length': 2, 'max_length': 4096, 'validation_message': 'Text only, please.'}},
        {'id': 'create', 'type': 'action', 'config': {'action': 'support.create', 'input': {'title': {'var': 'answers.title'}}, 'output_key': 'ticket'}},
        {'id': 'update', 'type': 'ask_input', 'config': {'message': 'Send an update for #{{actions.ticket.number}}', 'answer_key': 'update',
            'input_type': 'content'}},
        {'id': 'append', 'type': 'action', 'config': {'action': 'support.append', 'input': {'content': {'var': 'last_input.value'}}}},
        {'id': 'more', 'type': 'ask_input', 'config': {'message': 'More?', 'answer_key': 'more', 'input_type': 'radio',
            'options': [{'label': 'Add', 'value': 'add'}, {'label': 'Finish', 'value': 'finish'}]}},
        {'id': 'loop', 'type': 'condition'},
        {'id': 'done', 'type': 'end', 'config': {'message': 'Ticket #{{actions.ticket.number}} is saved.'}},
        {'id': 'stranger', 'type': 'human_handoff', 'config': {'message': 'A person will help you.'}}],
        'edges': [
            {'source': 'start', 'target': 'resolve'}, {'source': 'resolve', 'target': 'known'},
            {'source': 'known', 'target': 'service', 'when': {'op': 'eq', 'left': {'var': 'actions.customer.authorized'}, 'right': True}},
            {'source': 'known', 'target': 'stranger', 'default': True},
            {'source': 'service', 'target': 'title'}, {'source': 'title', 'target': 'create'}, {'source': 'create', 'target': 'update'},
            {'source': 'update', 'target': 'append'}, {'source': 'append', 'target': 'more'}, {'source': 'more', 'target': 'loop'},
            {'source': 'loop', 'target': 'update', 'when': {'op': 'eq', 'left': {'var': 'answers.more'}, 'right': 'add'}, 'max_traversals': 10},
            {'source': 'loop', 'target': 'done', 'default': True}]}


class LegacySupportFlow(unittest.TestCase):
    def test_old_references_become_relay_paths(self):
        steps = {step['id']: step for step in convert(support_graph())['nodes']}
        self.assertEqual(steps['resolve']['variable'], 'customer')
        self.assertEqual((steps['known']['variable'], steps['known']['value']), ('customer.authorized', 'true'))
        self.assertEqual(steps['service']['text'], 'Hi {{customer.name}}! Choose')
        self.assertEqual(steps['create']['arguments'], {'title': {'var': 'title'}})
        self.assertEqual(steps['append']['arguments'], {'content': {'var': 'last_input'}})
        self.assertEqual(steps['done']['text'], 'Ticket #{{ticket.number}} is saved.')

    def test_inputs_keep_their_limits_messages_and_media(self):
        steps = {step['id']: step for step in convert(support_graph())['nodes']}
        self.assertEqual((steps['title']['min_length'], steps['title']['max_length'], steps['title']['error_text']), (2, 4096, 'Text only, please.'))
        self.assertEqual(steps['update']['input_type'], 'content')
        self.assertIn('voice', steps['update']['accept'])
        self.assertEqual(steps['update']['max_visits'], 10)

    def test_a_loop_must_stop_at_a_question(self):
        graph = support_graph()
        graph['nodes'] = [node for node in graph['nodes'] if node['id'] != 'more']
        graph['edges'] = [edge for edge in graph['edges'] if 'more' not in (edge['source'], edge['target'])]
        graph['edges'] += [{'source': 'append', 'target': 'loop'}]
        repeat = next(edge for edge in graph['edges'] if edge['source'] == 'loop' and 'when' in edge)
        repeat.update(target='append', when={'op': 'eq', 'left': {'var': 'answers.title'}, 'right': 'again'})
        with self.assertRaisesRegex(ValueError, 'wait for a reply'):
            convert(graph)


class FlowContracts(unittest.TestCase):
    def test_dotted_results_render_and_branch(self):
        values = {'customer': {'name': 'Asha', 'authorized': True}}
        self.assertEqual(render('Hi {{customer.name}}', values), 'Hi Asha')
        self.assertTrue(matches({'variable': 'customer.authorized', 'operator': 'eq', 'value': 'true'}, values))
        self.assertFalse(matches({'variable': 'customer.missing', 'operator': 'is_set'}, values))

    def test_choices_are_numbered_and_accept_the_number(self):
        node = {'input_type': 'choice', 'text': 'Pick', 'choices': [{'label': 'Create', 'value': 'create'}, {'label': 'View', 'value': 'view'}]}
        self.assertEqual(prompt(node, {}), 'Pick\n1. Create\n2. View')
        self.assertEqual(parse_input(node, '2'), 'view')

    def test_text_answers_check_length_and_message_type(self):
        node = {'input_type': 'text', 'min_length': 2, 'max_length': 5, 'error_text': 'Text only.'}
        for value, message in (('x', None), ('too long', None), ('', {'message_type': 'image', 'name': 'MSG-1'})):
            with self.assertRaisesRegex(ValueError, 'Text only.'):
                parse_input(node, value, message)
        self.assertEqual(parse_input(node, 'ok'), 'ok')

    def test_content_answers_take_only_accepted_types(self):
        node = {'input_type': 'content', 'accept': ['image', 'text']}
        self.assertEqual(parse_input(node, '', {'message_type': 'image', 'name': 'MSG-1'})['type'], 'image')
        self.assertEqual(parse_input(node, 'hello', {'message_type': 'text', 'name': 'MSG-2'})['text'], 'hello')
        with self.assertRaises(ValueError):
            parse_input(node, '', {'message_type': 'video', 'name': 'MSG-3'})

    def test_last_input_holds_the_latest_answer(self):
        nodes = [{'id': 'ask', 'kind': 'input', 'text': 'Name?', 'variable': 'name', 'input_type': 'text'},
                 {'id': 'echo', 'kind': 'reply', 'text': 'Got {{last_input}}'}]
        self.assertEqual(len(definition(nodes)), 2)


class FlowTriggers(unittest.TestCase):
    def test_old_triggers_map_to_command_keywords_and_button(self):
        rows = [{'type': 'command', 'match': '/help'}, {'type': 'inbound_pattern', 'match': 'need help'},
                {'type': 'template_button', 'match': 'feedback_start'}]
        self.assertEqual(triggers(rows), {'command': '/help', 'keywords': 'need help', 'template_button': 'feedback_start'})

    def test_patterns_and_unknown_triggers_need_manual_setup(self):
        for rows in ([{'type': 'inbound_pattern', 'match': 'help*'}], [{'type': 'schedule', 'match': 'daily'}],
                     [{'type': 'command', 'match': '/a'}, {'type': 'command', 'match': '/b'}]):
            with self.assertRaises(ValueError):
                triggers(rows)

    def test_keywords_ignore_case_and_spacing(self):
        self.assertEqual(service.keywords('  Need   HELP \nsupport\n\nSUPPORT'), ['Need HELP', 'support'])

    def test_repeat_limit_stops_a_loop(self):
        run = SimpleNamespace()
        nodes = [{'id': 'ask', 'kind': 'input', 'max_visits': 2}]
        values = {}
        service.visit(run, nodes, values, 0)
        service.visit(run, nodes, values, 0)
        with self.assertRaisesRegex(service.StepLimit, 'repeated more than 2 times'):
            service.visit(run, nodes, values, 0)
        self.assertEqual(json.loads(run.values)['_visits'], {'ask': 2})


class FlowSwitch(unittest.TestCase):
    def test_a_switch_the_site_does_not_have_yet_is_off(self):
        site = Mock(ValidationError=frappe.ValidationError)
        site.db.get_single_value.side_effect = frappe.ValidationError('missing field')
        with patch.object(features, 'frappe', site):
            self.assertFalse(features.is_enabled('flows'))
        site.clear_last_message.assert_called_once_with()
