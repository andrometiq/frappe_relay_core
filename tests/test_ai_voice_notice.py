"""A voice note without a transcript gets one gentle notice to type, never a staff ticket."""
import json
import unittest
from unittest.mock import Mock, patch

import test_ai_skills as fixtures
from relay_core.ai import voice
from relay_core.ai.language import NOTICES


class VoiceNoticeRuleTests(unittest.TestCase):
    def test_only_a_voice_note_with_no_transcript_coming_needs_the_notice(self):
        for message, expected in ((dict(message_type='voice', transcript=''), True),
                                  (dict(message_type='audio', transcript=None, transcript_status='Failed'), True),
                                  (dict(message_type='voice', transcript=' ', transcript_status='Unavailable'), True),
                                  (dict(message_type='voice', transcript='', transcript_status='Pending'), False),
                                  (dict(message_type='voice', transcript='Hello'), False),
                                  (dict(message_type='text', content='Hi'), False)):
            with self.subTest(message=message):
                self.assertEqual(voice.is_untranscribed(fixtures.Doc(message)), expected)

    def test_notice_uses_the_language_the_sender_last_wrote(self):
        message = fixtures.Doc(name='MSG-3', conversation_key='CHAT-1')
        rows = [fixtures.Doc(content='', transcript=''), fixtures.Doc(content='எனக்கு உதவி வேண்டும்', transcript=None)]
        with patch.object(voice.frappe, 'get_all', return_value=rows) as get_all:
            self.assertEqual(voice.language(message), 'Tamil')
        self.assertEqual(get_all.call_args.kwargs['filters']['conversation_key'], 'CHAT-1')
        self.assertEqual(voice.notice_text('Tamil'), NOTICES['voice']['Tamil'])
        with patch.object(voice.frappe, 'get_all', return_value=[fixtures.Doc(content='ok', transcript='')]):
            self.assertIsNone(voice.language(message))
        self.assertEqual(voice.notice_text(None), voice.VOICE_NOTICE)

    def test_every_language_has_a_notice_without_a_ticket_number(self):
        self.assertEqual(set(NOTICES['voice']), set(NOTICES['handoff']))
        for text in voice.notices():
            self.assertNotIn('TKT', text)

    def test_one_notice_per_episode(self):
        run = fixtures.Doc(name='RUN-2', ticket='TKT-1')
        with patch.object(voice.frappe, 'get_all', return_value=['RUN-1']) as get_all:
            self.assertIsNone(voice.decision(run, fixtures.Doc(), 'partner', {}))
        filters = get_all.call_args.kwargs['filters']
        self.assertEqual((filters['ticket'], filters['name']), ('TKT-1', ['!=', 'RUN-2']))
        with patch.object(voice.frappe, 'get_all', return_value=[]), patch.object(voice, 'language', return_value='Hindi'):
            value = voice.decision(run, fixtures.Doc(), 'partner', {'company': 'Local'})
        self.assertEqual((value['reply'], value['notice'], value['decline'], value['handoff']),
                         (NOTICES['voice']['Hindi'], 'voice', True, False))
        self.assertIn('"notice": "voice"', json.dumps(value))

    def test_admit_binds_the_default_skill_without_matching(self):
        from relay_core.ai.skills import DEFAULT_KEY
        skills = [fixtures.Doc(name='EVENT'), fixtures.Doc(name='DEFAULT', sample_key=DEFAULT_KEY)]
        run = fixtures.Doc(name='RUN-1')
        with patch('relay_core.ai.service.select_skill') as select:
            self.assertFalse(voice.admit(run, fixtures.Doc(message_type='text', content='Hi'), skills))
            self.assertFalse(voice.admit(run, fixtures.Doc(message_type='voice'), []))
            self.assertTrue(voice.admit(run, fixtures.Doc(message_type='voice'), skills))
        select.assert_called_once_with(run, unittest.mock.ANY, 'DEFAULT')
        self.assertEqual(json.loads(run.match_result)['method'], 'voice')


class VoiceNoticeDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.SkillDeliveryTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.message.update(message_type='voice', transcript='', conversation_key='CHAT-1')

    def test_voice_note_gets_the_notice_without_model_call_or_ticket(self):
        with patch.object(voice, 'already_sent', return_value=False), patch.object(voice, 'language', return_value='Tamil'):
            self.case.service.process(self.case.run.name)
        self.case.service.decide.assert_not_called()
        self.case.send.assert_called_once()
        self.assertEqual(self.case.send.call_args.args[2], {'text': NOTICES['voice']['Tamil']})
        self.case.handoff.assert_not_called()
        self.assertEqual(self.case.run.status, 'Completed')

    def test_a_second_voice_note_in_the_episode_is_not_answered_again(self):
        with patch.object(voice, 'already_sent', return_value=True):
            self.case.service.process(self.case.run.name)
        self.case.service.decide.assert_not_called()
        self.case.send.assert_not_called()
        self.case.handoff.assert_not_called()
        self.assertEqual(self.case.run.status, 'Completed')

    def test_failed_notice_does_not_become_ticket(self):
        self.case.send.side_effect = ValueError('Delivery rejected')
        with patch.object(voice, 'already_sent', return_value=False), patch.object(voice, 'language', return_value=None):
            self.case.service.process(self.case.run.name)
        self.case.handoff.assert_not_called()
        self.assertEqual(self.case.run.status, 'Cancelled')


if __name__ == '__main__':
    unittest.main()
