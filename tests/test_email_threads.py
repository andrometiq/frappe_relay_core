import unittest
from relay_core.automation.provenance import conversation_key, email_context, email_message_id


class EmailThreadTests(unittest.TestCase):
    def test_threads_remain_separate_for_shared_senders_and_accounts(self):
        first = email_context({'message_id': '<first@example.invalid>'}, 'Same subject', 'event-one')
        second = email_context({'message_id': '<second@example.invalid>'}, 'Same subject', 'event-two')
        key = conversation_key('channel', 'person@example.invalid', first)
        self.assertNotEqual(key, conversation_key('channel', 'person@example.invalid', second))
        self.assertNotEqual(key, conversation_key('another-channel', 'person@example.invalid', first))
        self.assertNotEqual(key, conversation_key('channel', 'another@example.invalid', first))
        reply = email_context({'message_id': '<reply@example.invalid>', 'in_reply_to': '<first@example.invalid>',
                               'references': ['<first@example.invalid>']}, 'Re: Same subject', 'event-three')
        self.assertEqual(key, conversation_key('channel', 'person@example.invalid', reply))
        self.assertEqual(reply['reply_to_message_id'], '<first@example.invalid>')

    def test_missing_headers_never_merge_unrelated_mail(self):
        keys = [conversation_key('channel', 'person@example.invalid', email_context({}, 'Same subject', event))
                for event in ('one', 'two')]
        self.assertNotEqual(*keys)
        for value in ('<x@example.invalid>\r\nBcc:other@example.invalid', 42, '<x@example.invalid><y@example.invalid>'):
            self.assertIsNone(email_message_id(value))
        for raw in ({'references': 'invalid'}, {'references': ['<x@example.invalid>'] * 101},
                    {'authentication': 'pass'}, []):
            with self.assertRaises(ValueError):
                email_context(raw, 'Subject', 'event')
