"""Event match boundaries and exclusive, durable inbound admission."""
import time
import unittest
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core.ai import matching, adapter, service as ai
from relay_core.automation import service, queue
from relay_core.flows import service as flows


class MatchingTests(unittest.TestCase):
    def result(self, first, second, human=False):
        return matching.validate_result({'scores': [{'id':'one','score':first}, {'id':'two','score':second}],
                                         'human_request':human}, {'one','two'})

    def test_confidence_and_margin_boundaries(self):
        for first, second, selected in [(.85,.70,'one'), (.849,.1,None), (.85,.701,None),
                                        (.9,.9,None), (1,.85,'one'), (.95,.8,'one')]:
            self.assertEqual(self.result(first, second)['selected'], selected)
        self.assertIsNone(self.result(1, 0, True)['selected'])

    def test_human_request_requires_explicit_intent(self):
        for text in ('Person in charge listed on invoice', 'agent commission 1250', 'staff payment',
                     'human resources balance', 'I want a human resources balance', 'Who is the agent?', 'person', 'staff',
                     "I don't want to talk to a human", 'No need to speak with staff'):
            with self.subTest(text=text): self.assertFalse(matching.human_request(text))
        for text in ('Talk to a human', 'Please connect me with an agent', 'I want a human',
                     'Transfer me to your staff', 'Speak with a real person', 'Human please',
                     'Please hand this to a person', 'I need an operator'):
            with self.subTest(text=text): self.assertTrue(matching.human_request(text))

    def test_malformed_and_untrusted_output(self):
        valid = {'scores':[{'id':'one','score':.95}], 'human_request':False}
        for value in (None, [], {}, dict(valid, extra=True), dict(valid, human_request=1),
                      dict(valid, scores=[]), dict(valid, scores=[{'id':'other','score':1}]),
                      dict(valid, scores=[{'id':'one','score':True}]),
                      dict(valid, scores=[{'id':'one','score':float('nan')}]),
                      dict(valid, scores=[{'id':'one','score':float('inf')}]),
                      dict(valid, scores=[{'id':'one','score':1.01}]),
                      dict(valid, scores=[{'id':'one','score':.95,'sql':'select'}])):
            with self.subTest(value=value), self.assertRaises(ValueError):
                matching.validate_result(value, {'one'})
        with self.assertRaises(ValueError):
            matching.validate_result({'scores':[{'id':'one','score':1}]*2, 'human_request':False}, {'one','two'})

    def test_no_candidate_exact_trigger_duplicate_and_human_precedence(self):
        doc = _dict(content='/ledger')
        skills = [_dict(name='one', exact_trigger='/ledger')]
        with patch.object(adapter, 'match') as model:
            self.assertIsNone(matching.select(doc, [], 'run', time.monotonic()+10)['selected'])
            self.assertEqual(matching.select(doc, skills, 'run', time.monotonic()+10)['selected'], 'one')
            skills.append(_dict(name='two', exact_trigger='/ledger'))
            self.assertIsNone(matching.select(doc, skills, 'run', time.monotonic()+10)['selected'])
            doc.content = 'Talk to a human'
            skills[0].exact_trigger = doc.content
            self.assertEqual(matching.select(doc, skills, 'run', time.monotonic()+10)['method'], 'human')
        model.assert_not_called()

    def test_button_trigger_uses_payload_not_display_label(self):
        doc = _dict(content='Ledger', provider_context={'provider':'WhatsApp','original_message_type':'button'},
                    message_data={'selection_type':'template_button','selection_id':'ledger_button'})
        self.assertEqual(matching.trigger(doc), 'ledger_button')

    def test_single_candidate_still_requires_match_and_only_targets_are_disclosed(self):
        skill = _dict(name='one', target='Explain supplier ledger', instructions='private owner memory',
                      ai_model='model', daily_limit=1, allowed_tools='private contracts')
        with patch.object(adapter,'match',return_value={'scores':[{'id':'one','score':.2}], 'human_request':False}) as model, \
                patch.object(service,'reserve_attempt') as reserve:
            self.assertIsNone(matching.select(_dict(content='Weather', channel='channel'), [skill], 'run', 123)['selected'])
        model.assert_called_once_with('model',[{'id':'one','target':'Explain supplier ledger'}],'Weather','run',123)
        reserve.assert_called_once_with(_dict(name='matching:channel', daily_limit=1))

    def test_matching_budget_is_shared_and_independent_of_candidate_order(self):
        skills = [_dict(name='A', daily_limit=1, ai_model='model', target='A'),
                  _dict(name='B', daily_limit=100, ai_model='model', target='B')]
        counters = {}
        cache = Mock()
        cache.make_key.side_effect = lambda key: key
        def incr(key):
            counters[key] = counters.get(key, 0) + 1
            return counters[key]
        cache.incr.side_effect = incr
        with patch.object(service, 'now_datetime', return_value=__import__('datetime').datetime(2026, 10, 25)), \
                patch.object(service.frappe, 'cache', return_value=cache), patch.object(adapter, 'match',
                return_value={'human_request': False, 'scores': [{'id': 'A', 'score': .1}, {'id': 'B', 'score': .98}]}):
            service.reserve_attempt(skills[0])
            for candidates in (skills, list(reversed(skills))):
                result = matching.select(_dict(channel='channel', content='B request'), candidates, 'run', 123)
                self.assertEqual(result['selected'], 'B')
            self.assertEqual(next(v for k, v in counters.items() if ':A:' in k), 1)
            self.assertEqual(next(v for k, v in counters.items() if ':matching:channel:' in k), 2)

    def test_candidate_query_is_bounded_and_scoped(self):
        fake = Mock(); fake.get_all.return_value = ['one','two']
        with patch.object(matching,'frappe',fake), patch('relay_core.business_access.reference',return_value=('Supplier','A')):
            matching.candidates(_dict(channel='channel'))
            self.assertEqual(fake.get_all.call_args.kwargs['filters'],
                {'channel':'channel','business_doctype':'Supplier','enabled':1})
            fake.get_all.return_value = list(range(21))
            with self.assertRaises(ValueError): matching.candidates(_dict(channel='channel'))


class AdmissionTests(unittest.TestCase):
    def test_latest_message_does_not_require_ingress_user_read_permission(self):
        fake = Mock(session=_dict(user='integration@example.invalid'))
        fake.get_list.side_effect = PermissionError('Ingress cannot read messages')
        message = _dict(name='MSG-1', relay_contact='contact', channel='channel',
            conversation_key='conversation', sender_endpoint='sender', business_doctype='Supplier', business_name='SUP-1')
        with patch.object(service, 'frappe', fake):
            fake.get_all.return_value = [_dict(name='MSG-1')]
            self.assertTrue(service.latest_message(message))
            fake.get_all.assert_called_once_with('Relay Message', filters={
                'relay_contact': 'contact', 'channel': 'channel', 'direction': 'Incoming',
                'conversation_key': 'conversation', 'business_doctype': 'Supplier', 'business_name': 'SUP-1'},
                fields=['name'], order_by='name desc', limit_page_length=1)
            fake.get_all.return_value = [_dict(name='MSG-2')]
            self.assertFalse(service.latest_message(message))
            fake.get_all.return_value = []
            self.assertFalse(service.latest_message(message))
        fake.get_list.assert_not_called()

    def test_latest_message_keeps_legacy_sender_scope(self):
        fake = Mock()
        fake.get_all.return_value = [_dict(name='MSG-1')]
        message = _dict(name='MSG-1', relay_contact='contact', channel='channel', sender_endpoint='sender')
        with patch.object(service, 'frappe', fake):
            self.assertTrue(service.latest_message(message))
        self.assertEqual(fake.get_all.call_args.kwargs['filters'], {
            'relay_contact': 'contact', 'channel': 'channel', 'direction': 'Incoming', 'sender_endpoint': 'sender'})

    def setUp(self):
        self.fake = Mock(conf={'relay_automation_enabled':1}, session=_dict(user='Administrator'),
                         PermissionError=PermissionError, ValidationError=ValueError)
        self.fake.db.get_value.return_value = None
        self.run = _dict(name='run', status='Pending')
        def doc(values):
            self.run.update(values)
            return self.run
        self.fake.get_doc.side_effect = doc
        self.message = _dict(name='message', relay_contact='person', channel='channel',
                             direction='Incoming', content='Ledger 1250', message_type='text')
        self.enterContext(patch.object(service,'frappe',self.fake))
        self.save = self.enterContext(patch.object(service,'internal_save'))
        self.enterContext(patch.object(service,'message_hash',return_value='hash'))
        self.contact = _dict(automation_generation=0, automation_paused=0, save=Mock())
        self.enterContext(patch.object(service,'lock_contact',return_value=self.contact))
        self.episode = self.enterContext(patch.object(service,'episode',return_value=_dict(name='ticket',ai_disabled=0)))
        self.claims = self.enterContext(patch.object(flows,'claims',return_value=False))
        self.event = self.enterContext(patch.object(flows,'create_event'))
        self.confirm = self.enterContext(patch.object(ai,'continue_search',return_value=False))
        self.keyword = self.enterContext(patch('relay_core.opt_out.is_keyword', return_value=False))

    def test_an_opt_out_keyword_gets_no_automatic_reply(self):
        self.keyword.return_value = True
        self.claims.return_value = True
        self.assertEqual(service.create_run(self.message), {'status': 'Ignored'})
        self.save.assert_not_called()
        self.event.assert_not_called()
        self.fake.enqueue.assert_not_called()

    def test_flow_and_event_exclusion_with_one_source_journal(self):
        self.claims.return_value = True
        self.assertEqual(service.create_run(self.message), {'name':'run','status':'Completed'})
        self.assertEqual(self.run.stage,'Flow')
        self.event.assert_called_once_with(self.message)
        self.episode.assert_called_once()
        self.fake.enqueue.assert_not_called()
        self.fake.db.get_value.return_value = _dict(name='run',status='Completed')
        service.create_run(self.message)
        self.event.assert_called_once()

    def test_approved_search_precedes_a_competing_flow(self):
        self.claims.return_value=True
        def confirm(run, message):
            run.stage='Event'; run.skill='Event'
            return True
        self.confirm.side_effect=confirm
        self.assertEqual(service.create_run(self.message)['status'],'Pending')
        self.assertEqual(self.run.stage,'Event')
        self.event.assert_not_called()
        self.fake.enqueue.assert_called_once()
        self.confirm.side_effect=ValueError('Changed search scope')
        self.assertEqual(service.create_run(self.message)['status'],'Handoff')
        self.event.assert_not_called()

    def test_unmatched_source_is_admitted_off_projection_queue(self):
        with patch.object(adapter,'match') as model:
            self.assertEqual(service.create_run(self.message)['status'],'Pending')
        self.assertEqual(self.run.stage,'Matching')
        self.event.assert_not_called(); model.assert_not_called()
        self.assertEqual(self.fake.enqueue.call_args.kwargs['queue'],'default')
        self.assertTrue(self.fake.enqueue.call_args.kwargs['enqueue_after_commit'])

    def test_human_request_overrides_explicit_flow_and_suppresses_model(self):
        self.message.content='I want a human'
        self.claims.return_value=True
        self.assertEqual(service.create_run(self.message)['status'],'Handoff')
        self.event.assert_not_called(); self.fake.enqueue.assert_not_called()
        self.episode.assert_called_with(self.run, self.message, hold=True)
        self.assertEqual(self.contact.automation_paused, 0)
        self.assertEqual(self.contact.automation_generation, 0)
        self.contact.save.assert_not_called()
        self.episode.return_value.ai_disabled = 1
        self.assertEqual(service.create_run(self.message)['status'], 'Cancelled')
        self.contact.save.assert_not_called()
        self.event.assert_not_called(); self.fake.enqueue.assert_not_called()

    def test_takeover_and_owner_failure_never_start_handlers(self):
        self.episode.return_value.ai_disabled=1
        self.assertEqual(service.create_run(self.message)['status'],'Cancelled')
        self.episode.side_effect=ValueError('owner unavailable')
        self.assertEqual(service.create_run(self.message)['status'],'Pending')
        self.assertEqual(self.run.stage,'Triage')
        self.event.assert_not_called(); self.fake.enqueue.assert_not_called()

    def test_both_hooks_and_manual_flow_enqueue_share_admission(self):
        with patch.object(service,'create_run',return_value={'name':'run'}) as admit:
            flows.on_message(self.message)
            service.on_message(self.message)
        self.assertEqual(admit.call_count,2)
        self.assertNotIn('relay_core.flows.service.on_message',queue.HANDLERS)


def setUpModule():
    """These tests cover AI behavior, so the AI features switch is on."""
    from unittest import addModuleCleanup, mock
    switch = mock.patch('relay_core.ai_features.is_enabled', return_value=True)
    switch.start()
    addModuleCleanup(switch.stop)


if __name__ == '__main__':
    unittest.main()
