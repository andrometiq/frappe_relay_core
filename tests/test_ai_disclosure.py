"""The assistant notice goes once per ticket, before the first AI reply."""
import hashlib
import re
import sys
import unittest
from unittest.mock import Mock, patch

from test_ai_skills import Doc, module

from relay_core.ai import matching
from relay_core.ai.disclosure import DISCLOSURE
from relay_core.ai.language import NOTICES
from relay_core.automation.contracts import action_key


class DisclosureDelivery(unittest.TestCase):
    def setUp(self):
        from test_ai_actions import VerifiedContactExecution
        VerifiedContactExecution.setUp(self)
        self.ticket.ai_disclosed = 0
        self.f.db.set_value = Mock(side_effect=lambda dt, name, field, value, **kw: self.ticket.update({field: value}))
        self.f.db.rollback = Mock()
        self.disclosure = module('relay_core/ai/disclosure.py', self.f)
        self.enterContext(patch.dict(sys.modules, {'relay_core.ai.disclosure': self.disclosure}))
        self.flag_at_send = []
        def send(source, kind, data, key, **kw):
            self.flag_at_send.append(self.ticket.ai_disclosed)
            return {'status': 'Submitted'}
        self.send.side_effect = send

    def sent(self):
        return [(call.args[2]['text'], call.args[3]) for call in self.send.call_args_list]

    def test_first_reply_is_preceded_by_one_disclosure_even_when_the_run_retries(self):
        self.service.process(self.run.name)
        self.assertEqual(self.sent(), [(DISCLOSURE, action_key(self.message.name, 'disclosure')),
            ('Noted: 1250 received.', action_key(self.message.name, 'event_reply_0'))])
        self.assertEqual(self.flag_at_send[0], 1)  # Written before the journal row commits.
        self.assertEqual(self.ticket.ai_disclosed, 1)
        self.assertEqual(self.run.status, 'Completed')

        self.send.reset_mock()
        self.run.status, self.journal.status = 'Pending', 'Pending'
        self.service.process(self.run.name)
        self.assertEqual([text for text, _ in self.sent()], ['Noted: 1250 received.'])

    def test_disclosed_ticket_gets_only_the_reply(self):
        self.ticket.ai_disclosed = 1
        self.service.process(self.run.name)
        self.assertEqual([text for text, _ in self.sent()], ['Noted: 1250 received.'])
        self.f.db.set_value.assert_not_called()

    def test_notice_uses_the_customer_language(self):
        self.message.content = 'என் கட்டணம் எப்போது வரும்?'
        self.service.process(self.run.name)
        self.assertEqual(self.sent()[0][0], NOTICES['disclosure']['Tamil'])

    def test_failed_journal_rolls_back_the_flag_and_retry_reuses_the_key(self):
        self.send.side_effect = ValueError('Conversation changed before sending')
        self.service.process(self.run.name)
        self.f.db.rollback.assert_called()
        self.handoff.assert_called_once()
        first = self.send.call_args.args[3]
        self.ticket.ai_disclosed, self.run.status = 0, 'Pending'
        self.service.process(self.run.name)
        self.assertEqual(self.send.call_args.args[3], first)

    def test_disclosure_receipt_never_decides_the_run(self):
        action = Doc(name='Sim Notice', operation='text', source_message=self.message.name,
            payload='{"automation_run": "Sim Run"}', request_key=hashlib.sha256(
                (self.run.execution_user + ':' + action_key(self.message.name, 'disclosure')).encode()).hexdigest())
        lookup = self.f.get_doc.side_effect
        self.f.get_doc.side_effect = lambda dt, name: action if dt == 'Relay Message Action' else lookup(dt, name)
        for status in ('Submitted', 'Rejected'):
            with self.subTest(status=status):
                action.status, self.run.status = status, 'Delivering'
                self.service.complete_delivery(action.name)
                self.assertEqual(self.run.status, 'Delivering')
                self.handoff.assert_not_called()
                self.f.enqueue.assert_not_called()


class BarePersonRequest(unittest.TestCase):
    def test_bare_word_in_four_languages_hands_off(self):
        for text in ('person', 'Person.', 'HUMAN!', 'staff?', ' agent ', 'ആള്', 'ആൾ', 'व्यक्ति', 'ஆள்!',
                     'మనిషి', 'ವ್ಯಕ್ತಿ', 'মানুষ।', 'व्यक्ती'):
            with self.subTest(text=text):
                self.assertTrue(matching.human_request(text))
        for text in ('person please call', 'the person', 'staff invoice', 'agent 25', 'ஆள் வேண்டாம்', 'మనిషి వద్దు', 'মানুষ লাগবে না'):
            with self.subTest(text=text):
                self.assertFalse(matching.human_request(text))

    def test_every_disclosure_names_a_word_that_hands_off(self):
        for text in [DISCLOSURE, *NOTICES['disclosure'].values()]:
            with self.subTest(text=text):
                self.assertTrue(matching.human_request(re.search(r" '([^'\s]+)'", text).group(1)))

    def test_notice_slots_have_stable_keys(self):
        for slot in ('disclosure', 'approval_notice'):
            self.assertEqual(action_key('MSG-1', slot), action_key('MSG-1', slot))
        self.assertNotEqual(action_key('MSG-1', 'disclosure'), action_key('MSG-1', 'reply'))
