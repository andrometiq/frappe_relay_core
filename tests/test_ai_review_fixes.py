"""Regression coverage for the six AI review findings; all provider I/O is mocked."""
import hashlib
import json
import unittest
from unittest.mock import patch

import frappe
from frappe import permissions
import test_ai_skills as fixtures
from relay_core import ai_features, hooks
from relay_core.ai import language, reply_guard


class PermissionRegression(unittest.TestCase):
    def test_feature_hook_preserves_role_permissions_through_frappe_evaluator(self):
        registered = {dt: [ai_features.document_permission] for dt, method in hooks.has_permission.items()
                      if method == 'relay_core.ai_features.document_permission'}
        self.assertTrue(registered)
        with patch.object(frappe, 'get_hooks', return_value=registered), \
                patch.object(frappe, 'get_meta', return_value=frappe._dict(is_submittable=0, allow_import=0)), \
                patch.object(permissions, 'has_user_permission', return_value=True), \
                patch.object(permissions, '_', side_effect=lambda text: text), \
                patch.object(permissions, 'push_perm_check_log'):
            for enabled in (False, True):
                for allowed in (0, 1):
                    with patch.object(ai_features, 'is_enabled', return_value=enabled), \
                            patch.object(permissions, 'get_role_permissions', return_value={
                                'read': allowed, 'write': allowed, 'create': allowed}):
                        for doctype in registered:
                            for action in ('read', 'write', 'create'):
                                with self.subTest(enabled=enabled, allowed=allowed, doctype=doctype, action=action):
                                    result = permissions.get_doc_permissions(frappe._dict(doctype=doctype),
                                        user='local-manager@example.test', ptype=action)
                                    self.assertEqual(bool(result.get(action)), enabled and bool(allowed))


class VoiceSearchRegression(unittest.TestCase):
    def test_voice_search_accepts_typed_and_spoken_confirmation_but_not_edited_transcript(self):
        for kind in ('text', 'voice'):
            with self.subTest(kind=kind):
                case = fixtures.SearchGateTests()
                case.setUp()
                try:
                    case.source.update(message_type='voice', transcript='എന്റെ ലെഡ്ജർ കാണിക്കൂ')
                    case.reply.update(message_type=kind, content='അതെ', transcript='അതെ' if kind == 'voice' else '')
                    def context(skill, message):
                        scope = dict(case.scope, message=message.name)
                        if message.message_type == 'voice':
                            scope['transcript_hash'] = hashlib.sha256(language.incoming(message).encode()).hexdigest()
                        return 'partner', ('Supplier', 'Supplier'), scope
                    case.service.context = context
                    case.service.current = lambda run, skill, message: context(skill, message)
                    case.origin.search_plan = None
                    case.service.declare_search(case.origin, case.skill, case.source, case.decision)
                    case.confirmed()
                    case.authorize()
                    case.source.transcript = 'A different ledger request'
                    with self.assertRaisesRegex(ValueError, 'source changed'):
                        case.authorize()
                finally:
                    case.doCleanups()


class LanguageRegression(unittest.TestCase):
    def test_mixed_questions_short_followups_language_switch_and_neutral_replies(self):
        for text, expected in [('SIHMA International Textile Expo എപ്പോൾ?', 'Malayalam'),
                               ('SIHMA International Textile Expo कब है?', 'Hindi'),
                               ('SIHMA International Textile Expo எப்போது?', 'Tamil')]:
            with self.subTest(text=text):
                self.assertEqual(language.detect(text)['language'], expected)
        history = [dict(direction='Incoming', content='പരിപാടി എപ്പോൾ?'),
                   dict(direction='Outgoing', content='The event is tomorrow.')]
        for text in ('ok', 'OK!', '5', '👍', '2026-11-05', 'yes', 'k'):
            self.assertEqual(language.resolve(text, history)['language'], 'Malayalam')
        self.assertEqual(language.resolve('Where is the event?', history)['language'], 'English')
        for text in ('5', '൫', '५', '2026-11-05', '₹4,200.00', 'INR 4,200.00', 'Rs. 500', '👍'):
            self.assertTrue(language.matches(text, language.detect(history[0]['content'])))

    def test_language_context_reads_scoped_permitted_customer_transcripts_without_old_answers(self):
        f = fixtures.framework()
        local = fixtures.module('relay_core/ai/service.py', f)
        message = fixtures.Doc(name='NEW', content='ok', conversation_key='LOCAL-CONVERSATION')
        source = fixtures.Doc(name='OLD', message_type='voice', transcript='പരിപാടി എപ്പോൾ?')
        f.get_list.return_value = [source]
        f.get_doc.return_value = source
        with patch.object(local, 'as_user'):
            self.assertEqual(local.conversation_language(message, 'local-user', ('Customer', 'LOCAL')), source.transcript)
            self.assertEqual(f.get_list.call_args.kwargs['filters'], dict(conversation_key='LOCAL-CONVERSATION',
                business_doctype='Customer', business_name='LOCAL', direction='Incoming', name=['<', 'NEW']))
            source.denied = True
            self.assertEqual(local.conversation_language(message, 'local-user', ('Customer', 'LOCAL')), '')
            source.denied = False
            with patch.object(fixtures.Doc, 'apply_fieldlevel_read_permissions', lambda doc: doc.update(transcript='')):
                self.assertEqual(local.conversation_language(message, 'local-user', ('Customer', 'LOCAL')), '')
        f.db.get_value.assert_not_called()

    def test_language_lookup_pages_past_neutral_messages(self):
        f = fixtures.framework()
        local = fixtures.module('relay_core/ai/service.py', f)
        message = fixtures.Doc(name='NEW', content='👍', conversation_key='LOCAL-CONVERSATION')
        neutral = [fixtures.Doc(name=f'NEUTRAL-{index}', content='ok') for index in range(50)]
        clear = fixtures.Doc(name='OLD', message_type='voice', transcript='कार्यक्रम कब है?')
        rows = {row.name: row for row in [*neutral, clear]}
        f.get_list.side_effect = [neutral, [clear]]
        f.get_doc.side_effect = lambda doctype, name: rows[name]
        with patch.object(local, 'as_user'):
            self.assertEqual(local.conversation_language(message, 'local-user', ('Customer', 'LOCAL')), clear.transcript)
        self.assertEqual(f.get_list.call_args.kwargs['filters']['name'], ['<', neutral[-1].name])

    def test_decide_passes_prior_customer_language_to_the_adapter(self):
        case = fixtures.ConversationIdentityTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.message.content = 'ok'
        source = fixtures.Doc(case.message, name='MSG-0', message_type='voice', transcript='പരിപാടി എപ്പോൾ?')
        get_doc = case.f.get_doc.side_effect
        case.f.get_doc.side_effect = lambda dt, name: source if (dt, name) == ('Relay Message', source.name) else get_doc(dt, name)
        case.f.get_list.return_value = [source]
        with patch('relay_core.ai.adapter.complete', return_value={'handoff': False}) as complete:
            case.service.decide(case.skill, case.message)
        prompt = json.loads(complete.call_args.args[3])
        self.assertEqual(prompt['incoming'], 'ok')
        self.assertEqual(prompt['language_context'], source.transcript)
        self.assertEqual(prompt['history'], [])


class DecisionRegression(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.SharedAdapterTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.skill.update(allowed_actions='[{"action":"reply"}]', execution_policy='Execute')
        from relay_core.ai.actions import REPLY
        self.enterContext(patch('relay_core.flows.actions.definitions', return_value={'reply': REPLY}))

    def complete(self, text, reply, **prompt):
        self.case.attempt.return_value = self.case.outcome(dict(reply=reply, handoff=False, reason=''))
        return self.case.adapter.complete(self.case.skill, 'operator', ('Supplier', 'LOCAL'),
            json.dumps(dict(incoming=text, **prompt), ensure_ascii=False))

    def test_language_gate_handles_mixed_neutral_and_latest_clear_language(self):
        reply = 'പരിപാടി കൊച്ചിയിൽ നടക്കും.'
        self.assertFalse(self.complete('SIHMA International Textile Expo എപ്പോൾ?', reply)['handoff'])
        for incoming in ('ok', '5', '👍'):
            context = dict(language_context='പരിപാടി എപ്പോൾ?')
            self.assertFalse(self.complete(incoming, reply, **context)['handoff'])
            self.assertTrue(self.complete(incoming, 'The event is in Kochi.', **context)['handoff'])
        for reply in ('5', '2026-11-05', '₹4,200.00', 'INR 4,200.00'):
            self.assertFalse(self.complete('പരിപാടി എപ്പോൾ?', reply)['handoff'])
        self.assertFalse(self.complete('Where is the event?', 'The event is in Kochi.',
            language_context='പരിപാടി എപ്പോൾ?')['handoff'])

    def test_missing_or_non_boolean_data_classification_is_rejected(self):
        self.assertIn('data_question', self.case.adapter.RESPONSE['required'])
        for flag in ('missing', None, 0, 'false'):
            outcome = self.case.outcome(dict(reply='Your balance is 4200.', handoff=False, reason=''))
            if flag == 'missing':
                del outcome['result']['data']['data_question']
            else:
                outcome['result']['data']['data_question'] = flag
            self.case.attempt.return_value = outcome
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'Invalid skill decision'):
                self.case.adapter.complete(self.case.skill, 'operator', ('Supplier', 'LOCAL'), 'What is my balance?')

    def test_knowledge_copy_is_blocked_at_inference_and_delivery(self):
        instructions = 'always ask the internal team to verify every special discount before sharing details with customers'
        with patch('relay_core.ai.knowledge.prompt', return_value=instructions) as knowledge:
            result = self.complete('What should I know?', instructions)
            self.assertTrue(result['handoff'])
            self.assertEqual(result['reason'], reply_guard.REASON)
            message = fixtures.Doc(channel='LOCAL', sender_endpoint='local', relay_contact='LOCAL',
                business_doctype='Supplier', business_name='LOCAL', content='What should I know?')
            with self.assertRaises(reply_guard.ReplyBlocked):
                reply_guard.check_delivery(fixtures.Doc(decision='{}'), self.case.skill, message, instructions)
            self.assertEqual(knowledge.call_args.args[0], ('Supplier', 'LOCAL'))
            reply_guard.check_delivery(fixtures.Doc(decision='{}'), self.case.skill, message, 'we will verify that discount.')
