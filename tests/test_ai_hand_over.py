import json
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from frappe import _dict
from frappe_tools.ai import conversation
from relay_core.ai import hand_over
from relay_core.automation import queue, service

AGENT = _dict(name='Agent skill', mode='Automatic', ai_model='Agent Model', run_as_user='agent@relay.test')


def message(**values):
    return _dict({'name': 'RELAY-MSG-0000000001', 'direction': 'Incoming', 'relay_contact': 'RELAY-CON-0000000001',
                  'channel': 'RELAY-CH-1', 'content': 'Where is my order?', 'message_type': 'text',
                  'creation': datetime(2026, 11, 25, 16, 20, 52), **values})


def fake_frappe():
    fake = Mock()
    fake.db.get_value.side_effect = lambda doctype, name, field=None, **kwargs: (0, 3) if doctype == 'Relay Contact' else None
    fake.cache.hget.return_value = None
    fake.get_all.return_value = []
    fake.local.site = 'relay.test'
    return fake


class HandOverTests(unittest.TestCase):
    def setUp(self):
        self.frappe = fake_frappe()
        self.enterContext(patch.object(hand_over, 'frappe', self.frappe))
        self.enabled = self.enterContext(patch.object(hand_over.ai_features, 'is_enabled', return_value=True))
        self.allowed = self.enterContext(patch.object(hand_over.features, 'is_automation_allowed', return_value=True))
        self.enterContext(patch('relay_core.opt_out.keywords', return_value={'stop', 'start'}))
        self.enterContext(patch.object(hand_over, 'held_ticket', return_value=None))
        self.skills = self.enterContext(patch('relay_core.ai.matching.candidates', return_value=[AGENT]))
        self.agents = self.enterContext(patch.object(conversation, 'is_conversation_agent',
                                                     side_effect=lambda model: model == 'Agent Model'))

    def test_payload_has_the_contract_shape_and_no_contact_details(self):
        values = {('Relay Contact', 'display_name'): '+91 98765 43210', ('Relay Channel', 'channel'): 'WhatsApp'}
        self.frappe.db.get_value.side_effect = lambda doctype, name, field: values[(doctype, field)]
        doc = message(business_doctype='Customer', business_name='CUST-0001',
                      message_data=json.dumps({'kind': 'image', 'media': {'id': 'm1'}}), message_type='image')
        with patch.object(hand_over, 'get_system_timezone', return_value='Asia/Kolkata'), \
             patch('relay_core.business_types.type_label', return_value='Retailer'):
            body = hand_over.payload(doc)
        self.assertEqual(body, {'version': 1, 'site': 'relay.test', 'message_id': doc.name, 'chat': doc.relay_contact,
                                'contact': doc.relay_contact, 'contact_name': '', 'channel': 'WhatsApp',
                                'text': 'Where is my order?', 'transcript': '', 'transcript_status': '',
                                'message_type': 'image', 'has_media': True,
                                'business': {'doctype': 'Customer', 'doctype_label': 'Retailer', 'name': 'CUST-0001'},
                                'timestamp': '2026-11-25T10:50:52Z'})

    def test_voice_transcript_is_the_text_and_a_missing_business_is_null(self):
        self.frappe.db.get_value.side_effect = None
        self.frappe.db.get_value.return_value = 'Asha'
        with patch.object(hand_over, 'get_system_timezone', return_value='UTC'):
            body = hand_over.payload(message(transcript='Send the bill', content='', message_type='audio'))
        self.assertEqual((body['text'], body['transcript'], body['transcript_status'], body['business'], body['contact_name'],
                          body['has_media']), ('Send the bill', 'Send the bill', '', None, 'Asha', False))

    def test_only_real_customer_messages_go_while_ai_features_are_on(self):
        self.assertTrue(hand_over.handles(message()))
        for doc in (message(direction='Outgoing'), message(legacy_source='old'), message(message_type='system'),
                    message(content='STOP'), message(provider_context=json.dumps({'provider': 'WhatsApp', 'group_id': 'g1'})),
                    message(provider_context=json.dumps({'provider': 'Telegram', 'chat_type': 'supergroup'})),
                    message(provider_context=json.dumps({'provider': 'Email', 'auto_submitted': True}))):
            self.assertFalse(hand_over.handles(doc), doc)
        self.enabled.return_value = False
        self.assertFalse(hand_over.handles(message()))

    def test_only_automation_test_contacts_go_while_the_list_is_set(self):
        self.allowed.side_effect = lambda contact: contact == 'RELAY-CON-0000000002'
        self.assertFalse(hand_over.handles(message()))
        self.assertTrue(hand_over.handles(message(relay_contact='RELAY-CON-0000000002')))

    def test_the_first_live_agent_skill_of_relay_ais_candidates_answers(self):
        doc = message(business_doctype='Customer')
        shadow, model = _dict(AGENT, name='Shadow', mode='Shadow'), _dict(AGENT, name='Model', ai_model='Chat Model')
        second = _dict(AGENT, name='Second', run_as_user='other@relay.test')
        self.skills.return_value = [shadow, model, _dict(AGENT, ai_model=None), AGENT, second]
        self.assertIs(hand_over.agent_skill(doc), AGENT)
        self.skills.assert_called_with(doc)  # The skill's business type and channel come from Relay AI's matching.
        self.skills.return_value = [shadow, model]
        self.assertIsNone(hand_over.agent_skill(doc))  # The normal Relay AI path answers.
        self.skills.return_value = []
        self.assertFalse(hand_over.handles(doc))

    def test_a_message_with_no_business_record_falls_back_to_the_channels_default_skill(self):
        self.skills.return_value = []
        self.frappe.get_all.return_value = ['Default skill']
        self.frappe.get_doc.return_value = AGENT
        self.assertIs(hand_over.agent_skill(message()), AGENT)
        self.frappe.get_all.assert_called_once_with(
            'Relay AI Skill', filters={'channel': 'RELAY-CH-1', 'enabled': 1, 'sample_key': 'relay-default-skill'},
            pluck='name', order_by='name asc')
        self.frappe.get_doc.assert_called_once_with('Relay AI Skill', 'Default skill')
        for skill in (_dict(AGENT, mode='Shadow'), _dict(AGENT, ai_model='Chat Model')):
            self.frappe.get_doc.return_value = skill
            self.assertIsNone(hand_over.agent_skill(message()))  # Automatic mode and a conversation agent still apply.
        self.frappe.get_all.return_value = []
        self.assertIsNone(hand_over.agent_skill(message()))
        self.frappe.get_all.reset_mock()
        self.skills.return_value = [AGENT]
        self.assertIs(hand_over.agent_skill(message()), AGENT)
        self.frappe.get_all.assert_not_called()  # Relay AI's candidates win when the message has a business record.

    def test_hook_enqueues_one_deduplicated_job_after_commit(self):
        hand_over.on_message(message())
        self.frappe.enqueue.assert_called_once_with(
            'relay_core.ai.hand_over.deliver', message='RELAY-MSG-0000000001', queue='default', timeout=30,
            job_id='relay-ai-hand-over:RELAY-MSG-0000000001', deduplicate=True, enqueue_after_commit=True)
        self.frappe.enqueue.reset_mock()
        hand_over.on_message(message(direction='Outgoing'))
        self.skills.return_value = []
        hand_over.on_message(message())
        self.frappe.enqueue.assert_not_called()

    def test_hook_logs_instead_of_raising_into_inbound_work(self):
        self.frappe.enqueue.side_effect = ConnectionError
        hand_over.on_message(message())
        self.assertEqual(self.frappe.log_error.call_args.kwargs['title'], 'Relay AI hand-over enqueue failed')

    def test_a_chat_staff_took_over_is_not_handed_over(self):
        contact = {'paused': 1, 'generation': 4}
        self.frappe.db.get_value.side_effect = lambda doctype, name, field=None, **kwargs: (contact['paused'], contact['generation'])
        self.assertFalse(hand_over.handles(message()))
        hand_over.on_message(message())
        self.frappe.enqueue.assert_not_called()
        # A pause made by an active MCP claim (the agent's own claim during its turn) is not a takeover.
        claim = {'user': 'agent@relay.test', 'until': 2e9, 'paused_generation': 4}
        self.frappe.cache.hget.return_value = json.dumps(claim)
        self.assertTrue(hand_over.handles(message()))
        # Staff took over again after the claim paused it, or the claim expired: a takeover.
        contact['generation'] = 5
        self.assertFalse(hand_over.handles(message()))
        self.frappe.cache.hget.return_value = json.dumps(dict(claim, until=1, paused_generation=5))
        self.assertFalse(hand_over.handles(message()))

    def test_a_ticket_held_by_staff_is_a_takeover_but_one_held_by_an_ai_agent_user_is_not(self):
        self.frappe.get_roles.side_effect = lambda user: ['Relay AI Agent'] if user == 'agent@relay.test' else ['Relay Communication User']
        with patch.object(hand_over, 'held_ticket', return_value=_dict(ai_disabled=1, ownership_actor='staff@relay.test')):
            self.assertFalse(hand_over.handles(message()))
            self.assertTrue(hand_over.is_taken_over('RELAY-CON-0000000001', message()))
        with patch.object(hand_over, 'held_ticket', return_value=_dict(ai_disabled=1, ownership_actor='agent@relay.test')):
            self.assertTrue(hand_over.handles(message()))
        with patch.object(hand_over, 'held_ticket', return_value=_dict(ai_disabled=1, ownership_actor=None)):
            self.assertFalse(hand_over.handles(message()))
        with patch.object(hand_over, 'held_ticket', return_value=_dict(ai_disabled=0, ownership_actor='staff@relay.test')):
            self.assertTrue(hand_over.handles(message()))

    def test_reply_context_rule_reads_the_newest_customer_message(self):
        self.frappe.get_roles.side_effect = lambda user: ['Relay AI Agent'] if user == 'agent@relay.test' else []
        self.frappe.get_all.return_value = ['RELAY-MSG-0000000001']
        self.frappe.get_doc.return_value = message()
        with patch.object(hand_over, 'held_ticket', return_value=_dict(ai_disabled=1, ownership_actor='agent@relay.test')):
            self.assertFalse(hand_over.is_chat_taken_over('RELAY-CON-0000000001'))
        with patch.object(hand_over, 'held_ticket', return_value=_dict(ai_disabled=1, ownership_actor='staff@relay.test')):
            self.assertTrue(hand_over.is_chat_taken_over('RELAY-CON-0000000001'))

    def test_an_unexpected_error_leaves_the_message_to_the_relay_automation(self):
        from relay_core import email_preferences
        with patch.object(hand_over, 'handles', side_effect=RuntimeError('lock wait')), \
             patch.object(service, 'create_run', return_value={'status': 'Pending'}) as admit:
            self.assertFalse(hand_over.handles_safely(message()))
            self.assertEqual(service.on_message(message()), {'status': 'Pending'})
            email_preferences.on_message(message(direction='Outgoing'))
        admit.assert_called_once()
        self.assertEqual({entry.kwargs['title'] for entry in self.frappe.log_error.call_args_list},
                         {'Relay AI hand-over check failed'})

    def test_drain_sends_a_taken_over_chat_down_the_staff_path(self):
        with patch.object(hand_over, 'is_taken_over', return_value=True), patch.object(service, 'create_run') as admit:
            service.on_message(message())
        admit.assert_called_once()  # create_run cancels it as owned by staff.

    def test_reply_context_tells_the_agent_staff_took_over(self):
        from relay_core.mcp_tools import inbox
        with patch('relay_core.reply_context.read', return_value={'messages': {'items': []}}), \
             patch('relay_core.mcp_tools.coordination.with_actors', return_value=[]), \
             patch.object(hand_over, 'is_chat_taken_over', return_value=True) as taken:
            result = inbox.reply_context('RELAY-CON-0000000001')
        self.assertIs(result['taken_over'], True)
        taken.assert_called_once_with('RELAY-CON-0000000001')

    def deliver(self, error=None, doc=None):
        self.frappe.get_doc.return_value = doc or message()
        with patch.object(hand_over, 'payload', return_value={'version': 1}), \
             patch.object(conversation, 'hand_over', side_effect=error) as sent:
            hand_over.deliver('RELAY-MSG-0000000001')
        return sent

    def test_deliver_hands_the_message_to_the_skills_model_once(self):
        sent = self.deliver()
        sent.assert_called_once_with('Agent Model', 'relay', {'version': 1},
                                     headers={'X-Relay-Delivery': 'RELAY-MSG-0000000001'}, timeout=10)
        self.frappe.log_error.assert_not_called()

    def test_a_refused_hand_over_is_logged_once_and_not_retried(self):
        sent = self.deliver(error=conversation.HandOverError('HTTP 503'))
        sent.assert_called_once()
        self.frappe.log_error.assert_called_once()
        self.assertEqual(self.frappe.log_error.call_args.kwargs['title'], 'Relay AI hand-over failed')
        self.assertIn('HTTP 503', self.frappe.log_error.call_args.kwargs['message'])
        self.frappe.enqueue.assert_not_called()

    def test_a_voice_note_goes_at_once_and_a_chat_taken_over_meanwhile_does_not(self):
        self.deliver(doc=message(message_type='audio', transcript_status='Pending')).assert_called_once()
        with patch.object(hand_over, 'is_taken_over', return_value=True):
            self.deliver().assert_not_called()


class DrainTests(unittest.TestCase):
    def test_relay_automation_does_not_admit_messages_an_agent_answers(self):
        with patch.object(hand_over, 'handles', return_value=True), patch.object(service, 'create_run') as admit:
            self.assertEqual(service.on_message(message()), {'status': 'Ignored'})
        admit.assert_not_called()
        with patch.object(hand_over, 'handles', return_value=False), patch.object(service, 'create_run') as admit:
            service.on_message(message())
        admit.assert_called_once()

    def test_a_manual_automation_run_does_not_reply_in_a_chat_an_agent_answers(self):
        doc = Mock(**message())
        with patch('relay_core.ai_features.require'), patch.object(service, 'document_name'), \
                patch.object(service, 'require_access'), patch.object(service.frappe, 'get_doc', return_value=doc), \
                patch.object(service, 'create_run') as admit:
            with patch.object(hand_over, 'handles', return_value=True):
                self.assertEqual(service.enqueue(doc.name), {'status': 'Ignored'})
            admit.assert_not_called()
            with patch.object(hand_over, 'handles', return_value=False):
                service.enqueue(doc.name)
            admit.assert_called_once_with(doc)

    def test_email_rule_does_not_reply_to_messages_an_agent_answers(self):
        from relay_core import email_preferences
        fake = Mock()
        with patch.object(hand_over, 'handles', return_value=True), patch.object(email_preferences, 'frappe', fake):
            email_preferences.on_message(message())
        fake.db.set_value.assert_not_called()

    def test_the_hand_over_runs_last_in_the_inbound_drain(self):
        self.assertEqual(queue.HANDLERS[-1], 'relay_core.ai.hand_over.on_message')


class OldBridgePatchTests(unittest.TestCase):
    def test_patch_drops_the_old_delivery_log_and_settings_values(self):
        from relay_core.patches.v1_0 import remove_old_agent_delivery_log as old
        fake = Mock()
        with patch.object(old, 'frappe', fake):
            old.execute()
        fake.delete_doc.assert_called_once_with('DocType', old.OLD_DOCTYPE, ignore_missing=True, force=True)
        fake.db.sql_ddl.assert_called_once_with(f'drop table if exists `tab{old.OLD_DOCTYPE}`')
        self.assertEqual(fake.db.delete.call_args_list[0].args,
                         ('Singles', {'doctype': 'Relay Settings', 'field': ('in', old.OLD_SETTINGS)}))
        self.assertEqual(len(fake.db.delete.call_args_list), 2)


if __name__ == '__main__':
    unittest.main()
