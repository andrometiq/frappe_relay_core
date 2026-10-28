import json
import unittest
from unittest.mock import Mock, patch
from frappe import _dict
from relay_core.flows import service as flows
from relay_core.flows.contracts import definition
from relay_core import messaging, email
from relay_core.ai import service as ai
from relay_core.automation import service


class FlowV1Tests(unittest.TestCase):
    def test_new_nodes_validate_links_and_terminal_paths(self):
        self.assertEqual(len(definition([dict(id='assign', kind='assign', team='Support'),
            dict(id='skill', kind='ai_skill', ai_skill='Support skill', on_reply='Continue'), dict(id='end', kind='end')])), 3)
        for node in [dict(id='assign', kind='assign'), dict(id='ai', kind='ai_skill'),
                     dict(id='ai', kind='ai_skill', ai_skill='skill', on_reply='Other')]:
            with self.assertRaises(ValueError): definition([node])
        with self.assertRaisesRegex(ValueError, 'reachable'):
            definition([dict(id='ai', kind='ai_skill', ai_skill='skill', on_reply='Stop'), dict(id='end', kind='end')])

    def test_telegram_and_email_can_start_flows(self):
        fake = Mock(); fake.db.get_value.return_value = 'flow'
        for provider in ('WhatsApp', 'Telegram', 'Email'):
            source = _dict(direction='Incoming', message_type='text', channel='channel', content='/support',
                           provider_context=json.dumps({'provider': provider}))
            with patch.object(flows, 'frappe', fake):
                self.assertEqual(flows.matching(source), 'flow')

    def test_template_buttons_and_email_only_media_questions_fail_publication(self):
        fake = Mock(); fake.get_doc.return_value = _dict(channel='Email')
        fake.throw.side_effect = lambda message: (_ for _ in ()).throw(ValueError(message))
        with patch.object(flows, 'frappe', fake), patch('relay_core.flows.actions.definitions', return_value={}):
            with self.assertRaisesRegex(ValueError, 'Template button'):
                flows.validate_compatibility(_dict(channel='email', template_button='start'), [])
            with self.assertRaisesRegex(ValueError, 'accept text'):
                flows.validate_compatibility(_dict(channel='email'), [dict(kind='input', input_type='content', accept=['location'])])
            flows.validate_compatibility(_dict(channel='email'), [dict(kind='input', input_type='choice')])

    def test_old_published_version_remains_active_but_disabled_flow_does_not(self):
        flow = _dict(name='flow', enabled=1, published_version='new')
        version = _dict(name='old', flow='flow', execution_user='manager', channel='channel', business_doctype='Customer')
        source = _dict(name='message', direction='Incoming', relay_contact='contact', channel='channel',
                       business_doctype='Customer', business_name='customer')
        run = _dict(flow='flow', version='old', status='Waiting', generation=2, conversation_key='route')
        fake = Mock(); fake.get_doc.side_effect = lambda dt, name: {'Relay Flow': flow, 'Relay Flow Version': version}.get(dt, Mock())
        with patch.object(flows, 'frappe', fake), patch.object(flows, 'check_actor'), \
             patch.object(flows, 'route', return_value='route'), patch.object(flows, 'readable_contact', return_value=(_dict(automation_paused=0, automation_generation=2), None)), \
             patch('relay_core.messaging.readable_source', return_value=(source, _dict(name='channel', channel='Email'), {'provider':'Email'})), \
             patch('relay_core.business_access.reference', return_value=('Customer','customer')), patch('relay_core.business_access.candidates', return_value=[('Customer','customer')]):
            self.assertEqual(flows.scope(run, source)[0], version)
            flow.enabled = 0
            with self.assertRaisesRegex(ValueError, 'disabled'): flows.scope(run, source)

    def test_email_sends_keep_flow_provenance_for_recovery(self):
        run = _dict(name='flow-run', version='v1', generation=2)
        def send(*args, **kwargs):
            self.assertEqual(messaging.outgoing_flow.get(), dict(name='flow-run', version='v1', generation=2))
            self.assertEqual(kwargs['auto_submitted'], 1)
            return {'status':'Submitted'}
        with patch.object(email, 'send', side_effect=send):
            flows.send(run, None, _dict(name='message', sender_endpoint='local@example.test'), _dict(channel='Email'), 'Hello', 'key')
        self.assertIsNone(messaging.outgoing_flow.get())

    def test_interactive_buttons_and_lists_use_existing_hub_path(self):
        source = _dict(sender_endpoint='15550000001', provider_id='provider-id')
        channel = _dict(channel='WhatsApp')
        for count, kind in [(3, 'button'), (4, 'list'), (10, 'list')]:
            tool, args, content = messaging.prepare_choices(source, channel, {'provider':'WhatsApp'},
                dict(body='Choose', choices=[dict(label='Choice '+str(i), value=str(i)) for i in range(count)]))
            self.assertEqual(tool, 'whatsapp.execute'); self.assertEqual(args['operation'], 'messages.interactive')
            self.assertEqual(args['interactive']['type'], kind)
            self.assertEqual(len(content['choices']), count)

    def test_supported_interactive_mode_is_pinned_and_fallback_is_numbered(self):
        node = dict(input_type='choice', text='Choose', choices=['Yes','No'])
        for supports in (True, False):
            values = {}; run = _dict(); source = _dict()
            with patch('relay_core.whatsapp.checked_client', return_value=(None, {'operations':['messages.interactive'] if supports else []})) as capabilities, \
                 patch.object(flows, 'send') as send, patch.object(flows, 'internal_save'):
                flows.send_prompt(run, None, source, _dict(channel='WhatsApp'), node, values, 'key')
                flows.send_prompt(run, None, source, _dict(channel='WhatsApp'), node, values, 'key')
            capabilities.assert_called_once()
            self.assertEqual(bool(send.call_args.kwargs['choices']), supports)
            self.assertEqual(send.call_args.args[4], 'Choose\n1. Yes\n2. No')
        with patch('relay_core.whatsapp.checked_client') as capabilities, patch.object(flows, 'send') as send:
            flows.send_prompt(_dict(), None, _dict(), _dict(channel='Telegram'), node, {}, 'key')
        capabilities.assert_not_called(); self.assertIsNone(send.call_args.kwargs['choices'])

    def test_interactive_reply_uses_stable_value_for_branching(self):
        message = _dict(content='Yes, please', message_data=json.dumps({'selection_id':'yes'}),
                        provider_context=json.dumps({'provider':'WhatsApp','original_message_type':'interactive'}))
        self.assertEqual(flows.input_value(message, {'input_type':'choice'}), 'yes')
        self.assertEqual(flows.input_value(message, {'input_type':'text'}), 'Yes, please')

    def test_skill_replies_have_per_visit_keys_but_legacy_keys_are_unchanged(self):
        from relay_core.automation.contracts import action_key
        first = _dict(name='ai-one', flow_run='flow'); second = _dict(name='ai-two', flow_run='flow')
        self.assertNotEqual(ai.reply_key('message','reply',first), ai.reply_key('message','reply',second))
        self.assertEqual(ai.reply_key('message','reply'), action_key('message','reply'))

    def test_ai_node_waits_for_its_existing_run_and_never_recreates_it(self):
        fake = Mock(conf={'relay_automation_enabled': 1}); fake.db.get_value.return_value = 'child'
        child = _dict(name='child', status='Delivering')
        fake.get_doc.return_value = child
        event = _dict(); run = _dict(name='flow')
        with patch.object(flows,'frappe',fake), patch('relay_core.ai_features.is_enabled',return_value=True), \
             patch.object(flows,'internal_save') as save:
            self.assertFalse(flows.run_skill(run,event,_dict(), {'ai_skill':'skill'},'key'))
            child.status = 'Completed'
            self.assertTrue(flows.run_skill(run,event,_dict(), {'ai_skill':'skill'},'key'))
        fake.enqueue.assert_called_once()
        self.assertFalse(any(call.kwargs.get('new') for call in save.call_args_list))

    def test_handoff_sends_message_before_holding_ticket(self):
        nodes = [dict(id='handoff', kind='handoff', text='A person will help you.')]
        source = _dict(name='message', content='help')
        run = _dict(name='flow', status='Running', step=0, values='{}')
        event = _dict(name='event', message='message', message_hash='hash', run='flow', input_applied=1)
        fake = Mock(); fake.get_doc.side_effect = lambda dt, name: source if dt == 'Relay Message' else run
        calls = []
        with patch.object(flows,'frappe',fake), patch.object(flows,'message_hash',return_value='hash'), \
             patch.object(flows,'scope',return_value=(_dict(nodes=json.dumps(nodes)), source, _dict(channel='Telegram'))), \
             patch.object(flows,'send',side_effect=lambda *args: calls.append('send')), \
             patch.object(flows,'flow_ticket',return_value=_dict(name='ticket')), \
             patch('relay_core.tickets.hold_episode',side_effect=lambda *args: calls.append('hold')), \
             patch.object(flows,'internal_save'), patch.object(flows,'finish'):
            flows._process(event)
        self.assertEqual(calls, ['send','hold']); self.assertEqual(run.status, 'Handoff')
