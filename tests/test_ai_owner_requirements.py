"""Owner requirements through the real decision/tools path with a mocked model; no network."""
import json
import time
import unittest
from unittest.mock import Mock, patch

import frappe
import test_ai_skills as fixtures
from test_ai_skills import Doc
from relay_core import ai_features
from relay_core.ai import events, evals, knowledge, language, matching, reports, reply_guard, service, skills


class OwnerBoundaries(unittest.TestCase):
    def test_disabled_ai_denies_all_new_apis_and_generic_documents(self):
        with patch.object(ai_features, 'is_enabled', return_value=False), \
                patch.object(frappe, 'throw', side_effect=frappe.PermissionError):
            for function, args in ((knowledge.directory, ()), (knowledge.save, ({},)),
                    (events.directory, ()), (events.save, ({},)), (evals.run, ('default',))):
                with self.subTest(api=function.__name__), self.assertRaises(frappe.PermissionError):
                    function(*args)
            self.assertFalse(ai_features.document_permission())
            self.assertEqual(ai_features.query_condition(), '1=0')
        with patch.object(ai_features, 'is_enabled', return_value=True):
            self.assertTrue(ai_features.document_permission())
            self.assertEqual(ai_features.query_condition(), '')

    def test_default_creation_is_idempotent_and_keeps_owner_changes(self):
        database = Mock()
        database.get_value.side_effect = [None, 'DEFAULT']
        doc = Mock()
        doc.name = 'DEFAULT'
        doc.insert.return_value = doc
        fake = Mock(db=database, get_doc=Mock(return_value=doc))
        with patch.object(skills, 'frappe', fake):
            self.assertEqual(skills.ensure_default(), 'DEFAULT')
            self.assertEqual(skills.ensure_default(), 'DEFAULT')
        fake.get_doc.assert_called_once()
        values = fake.get_doc.call_args.args[0]
        self.assertEqual(values['sample_key'], skills.DEFAULT_KEY)
        self.assertEqual(values['enabled'], 0)
        doc.insert.assert_called_once()

    def test_default_only_falls_back_after_no_match_not_human_or_exact(self):
        default = Doc(name='DEFAULT', sample_key=skills.DEFAULT_KEY, daily_limit=10, ai_model='MOCK')
        specific = Doc(name='EVENT', target='Event overview', daily_limit=10, ai_model='MOCK')
        message = Doc(content='സിഹ്മ പരിപാടി എവിടെ?', channel='WA')
        with patch('relay_core.automation.service.reserve_attempt'), patch('relay_core.ai.adapter.match') as model:
            self.assertEqual(matching.select(message, [default], None, time.monotonic()+20)['selected'], 'DEFAULT')
            model.assert_not_called()
            model.return_value = dict(human_request=False, scores=[dict(id='EVENT', score=.2)])
            self.assertEqual(matching.select(message, [specific, default], None, time.monotonic()+20)['selected'], 'DEFAULT')
            model.return_value['human_request'] = True
            self.assertIsNone(matching.select(message, [specific, default], None, time.monotonic()+20)['selected'])
            specific.exact_trigger = message.content
            self.assertEqual(matching.select(message, [specific, default], None, time.monotonic()+20)['selected'], 'EVENT')

    def test_knowledge_is_scoped_standing_guidance_and_bounded(self):
        rows = [Doc(title='Work', instructions='Ask one question at a time.', company='', business_doctype=''),
                Doc(title='Other', instructions='Private.', company='Other', business_doctype='Customer')]
        with patch.object(knowledge.frappe, 'get_all', return_value=rows):
            self.assertEqual(knowledge.prompt(('Customer', 'LOCAL-1'), 'Local'), 'Work\nAsk one question at a time.')
        with patch.object(knowledge.frappe, 'get_all', return_value=rows * 51), self.assertRaises(ValueError):
            knowledge.prompt(('Customer', 'LOCAL-1'), 'Local')

    def test_language_script_and_native_digits(self):
        for text, expected in [('പരിപാടി എവിടെയാണ്?', 'Malayalam'), ('कार्यक्रम कब है?', 'Hindi'),
                ('நிகழ்ச்சி எங்கே?', 'Tamil'), ('Where is the event?', 'English'),
                ('కార్యక్రమం ఎప్పుడు?', 'Telugu'), ('أين الحدث؟', 'Arabic')]:
            self.assertEqual(language.detect(text)['language'], expected)
        self.assertIsNone(language.detect('൫ ५ 5')['script'])
        self.assertEqual(reply_guard.phones('९८७६५४३२१०'), {'9876543210'})
        self.assertEqual(reply_guard.phones('൯൮൭൬൫൪൩൨൧൦'), {'9876543210'})
        for text in ('പരിപാടി നവംബർ ൫ന് കൊച്ചിയിൽ നടക്കും.', 'कार्यक्रम ५ नवंबर को होगा।'):
            reply_guard.check(text, {}, {})
        # A phone is still private regardless of its digit script; authorized ASCII evidence matches it.
        reply_guard.check('വിളിക്കുക ൯൮൭൬൫൪൩൨൧൦', {}, {'endpoint': '9876543210'})
        with self.assertRaises(reply_guard.ReplyBlocked):
            reply_guard.check('फोन ९८७६५४३२१०', {}, {})

    def test_voice_uses_transcript_and_never_audio_placeholder(self):
        message = Doc(message_type='voice', content='[audio]', transcript='कार्यक्रम कब है?')
        self.assertEqual(language.incoming(message), message.transcript)
        with patch.object(service, 'context', return_value=('staff', ('Customer', 'LOCAL'), {'company':'Local'})), \
                patch.object(service, 'conversation_history', return_value=[]), \
                patch('relay_core.ai.event_memory.ReplyContext') as reference, \
                patch.object(service, 'decide_text', return_value={'reply':'कार्यक्रम नवंबर में है।'}) as decide:
            service.decide(Doc(), message)
            self.assertEqual(decide.call_args.args[1], message.transcript)
            message.transcript = ''
            with self.assertRaisesRegex(ValueError, 'no transcript'):
                service.decide(Doc(), message)
            self.assertEqual(decide.call_count, 1)
            self.assertEqual(reference.call_count, 1)

    def test_eval_language_grading_and_voice_case(self):
        cases = evals.load_cases(None)
        self.assertTrue(any(case.get('transcript') for case in cases))
        for lang, text in [('Malayalam','പരിപാടി കൊച്ചിയിൽ നടക്കും.'), ('Hindi','कार्यक्रम कोच्चि में है।'),
                           ('Tamil','நிகழ்ச்சி கொச்சியில் நடக்கும்.'), ('English','The event is in Kochi.')]:
            case = dict(message=text, expected='reply', language=lang)
            self.assertTrue(evals.grade(case, dict(reply=text))['passed'])
            if lang != 'English':
                self.assertFalse(evals.grade(case, dict(reply='The event is in Kochi.'))['passed'])


class ReportContracts(unittest.TestCase):
    def setUp(self):
        fixtures.ScopedToolTests.setUp(self)

    # Use populated scoped rows and the real Reader, with framework I/O mocked.
    def test_registered_report_cannot_change_code_fields_or_business_scope(self):
        contract = dict(self.contract, report='supplier_ledger', doctype='GL Entry', fields=reports.LEDGER_FIELDS)
        reports.validate(contract, 'Supplier')
        for changes in ({'report':'sql'}, {'method':'python'}, {'fields':['password']}, {'scope_field':'name'}):
            with self.assertRaises(ValueError):
                reports.validate(dict(contract, **changes), 'Supplier')
        with self.assertRaises(ValueError):
            reports.validate(contract, 'Customer')


class DecisionPath(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.SharedAdapterTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.skill.update(allowed_actions='[{"action":"reply"}]', execution_policy='Execute')
        from relay_core.ai.actions import REPLY
        self.enterContext(patch('relay_core.flows.actions.definitions', return_value={'reply': REPLY}))

    def complete(self, incoming, response):
        self.case.attempt.return_value = self.case.outcome(response)
        return self.case.adapter.complete(self.case.skill, 'operator', ('Supplier', 'LOCAL'),
            json.dumps({'incoming':incoming, 'reference_data':{'events':[{'memory':'SIHMA on 5 Nov at Kochi'}]}}, ensure_ascii=False))

    def test_prompt_labels_keep_knowledge_and_events_separate(self):
        with patch('relay_core.ai.knowledge.prompt', return_value='Be concise.'), \
                patch.object(self.case.agent.AgentRun, 'run_route', return_value=self.case.outcome(
                    dict(reply='SIHMA is in Kochi.', handoff=False, reason=''))) as model:
            self.complete('Overview of the event?', {})
        system, text, _ = model.call_args.args[2]
        self.assertIn('Knowledge base — standing instructions:\nBe concise.', system)
        self.assertIn('Events and conversation memory — reference facts:', system)
        self.assertIn('SIHMA on 5 Nov at Kochi', text)
        self.assertNotIn('SIHMA on 5 Nov at Kochi', system)

    def test_unconfigured_data_report_hands_off(self):
        result = self.complete('What is my balance?', dict(reply='42', handoff=False, reason='', data_question=True))
        self.assertTrue(result['handoff'])
        self.assertIn('report', result['reason'])
        self.assertEqual(result['reply'], '')

    def test_latest_language_is_enforced_before_actions(self):
        for incoming, reply in [('പരിപാടി എവിടെ?', 'പരിപാടി കൊച്ചിയിൽ നടക്കും.'),
                               ('कार्यक्रम कहाँ है?', 'कार्यक्रम कोच्चि में है।'),
                               ('நிகழ்ச்சி எங்கே?', 'நிகழ்ச்சி கொச்சியில் நடக்கும்.')]:
            result = self.complete(incoming, dict(reply=reply, handoff=False, reason=''))
            self.assertEqual(result['actions'][0]['parameters']['text'], reply)
            wrong = self.complete(incoming, dict(reply='In Kochi.', handoff=False, reason=''))
            self.assertTrue(wrong['handoff'])
            self.assertNotIn('actions', wrong)

    def test_no_sql_code_or_legacy_read_tool_reachable(self):
        legacy = dict(name='records', method='get_list', doctype='Customer', fields=['name'], scope_field='name')
        with patch.object(self.case.adapter, 'contracts', return_value=[legacy]), \
                patch.object(self.case.tools.Reader, 'read') as read:
            for name in ('sql', 'python', 'run_code', 'get_list', 'records', 'SEARCH'):
                self.case.attempt.return_value = self.case.outcome(calls=[dict(id='1', name=name, arguments={})])
                with self.subTest(tool=name), self.assertRaises(ValueError):
                    self.case.adapter.complete(self.case.skill, 'operator', ('Supplier', 'LOCAL'), 'Balance?')
            read.assert_not_called()


class HandoffPath(unittest.TestCase):
    def test_missing_report_and_transcript_reach_handoff_without_send(self):
        case = fixtures.SkillDeliveryTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        for reason in ('The requested data report is not configured',
                       'Voice message needs staff review: no transcript is available'):
            case.run.update(status='Pending', decision=None, attempts=0)
            case.service.decide.return_value = dict(reply='', handoff=True, reason=reason,
                user='partner', reads=[], scope=case.tools.fingerprint(case.scope))
            case.service.process(case.run.name)
            self.assertEqual(case.handoff.call_args.args[2], reason)
        case.send.assert_not_called()
