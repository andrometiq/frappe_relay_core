"""WhatsApp polls: sent as reply buttons or a list, taps counted as one current vote per contact."""
import json
import unittest
from unittest.mock import patch

from frappe import _dict

from channel_fakes import FakeSite
from relay_core import messaging, polls
from relay_core.automation import projection
from relay_core.message_types import preview
from relay_core.message_updates import provider_key

CHANNEL, NUMBER = 'Acme-WA', '919999999999'


class PollSendTests(unittest.TestCase):
    def prepare(self, data):
        source = _dict(name='RELAY-MSG-1', sender_endpoint=NUMBER, provider_id='wamid.in')
        return messaging.prepare(source, _dict(channel='WhatsApp'), {'provider': 'WhatsApp'}, 'poll', data)

    def test_two_or_three_options_go_as_reply_buttons(self):
        tool, arguments, content = self.prepare({'question': 'Which colour?', 'options': ['Red', 'Blue']})
        self.assertEqual((tool, arguments['operation']), ('whatsapp.execute', 'messages.interactive'))
        self.assertEqual(arguments['interactive'], {'type': 'button', 'body': {'text': 'Which colour?'}, 'action': {'buttons': [
            {'type': 'reply', 'reply': {'id': 'poll-1', 'title': 'Red'}}, {'type': 'reply', 'reply': {'id': 'poll-2', 'title': 'Blue'}}]}})
        self.assertEqual(content, {'kind': 'poll', 'poll': {'question': 'Which colour?', 'options': ['Red', 'Blue'], 'votes': {}}})
        self.assertEqual(preview(content), 'Poll: Which colour?')

    def test_four_to_ten_options_go_as_a_list(self):
        options = ['Size %d' % number for number in range(1, 11)]
        _, arguments, content = self.prepare({'question': 'Pick a size', 'options': options})
        interactive = arguments['interactive']
        self.assertEqual((interactive['type'], interactive['action']['button']), ('list', 'Vote'))
        self.assertEqual([row['id'] for row in interactive['action']['sections'][0]['rows']], ['poll-%d' % n for n in range(1, 11)])
        self.assertEqual(content['poll']['options'], options)

    def test_invalid_polls_are_refused(self):
        for data in [{'question': 'Q', 'options': ['Only']}, {'question': 'Q', 'options': ['x%d' % n for n in range(11)]},
                     {'question': ' ', 'options': ['A', 'B']}, {'question': 'Q', 'options': ['Red', 'red']},
                     {'question': 'Q', 'options': ['x' * 21, 'B']}, {'question': 'Q', 'options': ['x' * 25, 'B', 'C', 'D']},
                     {'question': 'Q', 'options': ['A', 'B'], 'extra': 1}, {'question': 'Q', 'options': ['A', 7]}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.prepare(data)

    def test_a_poll_needs_a_private_whatsapp_chat(self):
        source = _dict(name='RELAY-MSG-1', sender_endpoint='12345', provider_id='1')
        with self.assertRaises(ValueError):
            messaging.prepare(source, _dict(channel='Telegram'), {'provider': 'Telegram'}, 'poll', {'question': 'Q', 'options': ['A', 'B']})
        with self.assertRaises(ValueError):
            messaging.prepare(source, _dict(channel='WhatsApp'), {'provider': 'WhatsApp', 'group_id': 'g'}, 'poll', {'question': 'Q', 'options': ['A', 'B']})


class PollVoteTests(unittest.TestCase):
    def setUp(self):
        content = {'kind': 'poll', 'poll': {'question': 'Which colour?', 'options': ['Red', 'Blue'], 'votes': {}}}
        self.site = FakeSite(Relay_Message=[{'name': 'POLL-1', 'channel': CHANNEL, 'relay_contact': 'CON-1', 'sender_endpoint': NUMBER,
            'direction': 'Outgoing', 'message_type': 'poll', 'message_data': json.dumps(content),
            'provider_message_key': provider_key(CHANNEL, NUMBER, 'wamid.poll')}])
        self.changed = []
        for item in (patch.object(polls, 'frappe', self.site.frappe), patch('relay_core.realtime.changed', self.changed.append)):
            item.start()
            self.addCleanup(item.stop)

    def reply(self, selection, at, name='REPLY', contact='CON-1', sender=NUMBER, channel=CHANNEL, target='wamid.poll'):
        return _dict(name=name, channel=channel, relay_contact=contact, sender_endpoint=sender, sent_at=at,
                     message_data=json.dumps({'kind': 'text', 'text': 'Blue', 'selection_id': selection}),
                     provider_context=json.dumps({'provider': 'WhatsApp', 'reply_to_message_id': target}))

    def votes(self):
        return json.loads(self.site.rows('Relay Message', {'name': 'POLL-1'})[0].message_data)['poll']['votes']

    def test_a_tap_is_the_contacts_vote_and_updates_the_poll_live(self):
        self.assertEqual(polls.record_vote(self.reply('poll-2', '2026-11-04 10:00:00')), 'POLL-1')
        self.assertEqual(self.votes(), {'CON-1': {'option': 1, 'message': 'REPLY', 'at': '2026-11-04 10:00:00'}})
        self.assertEqual([doc.name for doc in self.changed], ['POLL-1'])

    def test_a_later_tap_changes_the_vote_and_a_late_older_tap_does_not(self):
        polls.record_vote(self.reply('poll-2', '2026-11-04 10:00:00', name='FIRST'))
        polls.record_vote(self.reply('poll-1', '2026-11-04 10:05:00', name='SECOND'))
        self.assertIsNone(polls.record_vote(self.reply('poll-2', '2026-11-04 10:01:00', name='LATE')))
        self.assertEqual(self.votes(), {'CON-1': {'option': 0, 'message': 'SECOND', 'at': '2026-11-04 10:05:00'}})

    def test_a_reply_from_another_contact_or_chat_is_not_counted(self):
        for reply in [self.reply('poll-1', '2026-11-04 10:00:00', contact='CON-2', sender='919876543210'),
                      self.reply('poll-1', '2026-11-04 10:00:00', contact='CON-2'),
                      self.reply('poll-1', '2026-11-04 10:00:00', channel='Acme-WA-2'),
                      self.reply('poll-1', '2026-11-04 10:00:00', target='wamid.other'),
                      self.reply('poll-9', '2026-11-04 10:00:00'), self.reply('Red', '2026-11-04 10:00:00')]:
            with self.subTest(reply=reply):
                self.assertIsNone(polls.record_vote(reply))
        self.assertEqual(self.votes(), {})
        self.assertEqual(self.changed, [])

    def test_only_outgoing_polls_take_votes(self):
        self.site.rows('Relay Message', {'name': 'POLL-1'})[0].update(message_type='text')
        self.assertIsNone(polls.record_vote(self.reply('poll-1', '2026-11-04 10:00:00')))


class InboundPollTests(unittest.TestCase):
    def extract(self, unsupported_type):
        message = {'id': 'wamid.in', 'from': NUMBER, 'timestamp': '1792948421', 'type': 'unsupported',
                   'unsupported': {'type': unsupported_type},
                   'errors': [{'code': 131051, 'title': 'Message type unknown', 'error_data': {'details': 'Message type is currently not supported.'}}]}
        row, = projection.extract_messages({'entry': [{'changes': [{'value': {'messages': [message]}}]}]})
        return row['message_data']

    def test_a_customer_poll_says_why_its_content_is_missing(self):
        data = self.extract('poll_creation')
        self.assertEqual(data['kind'], 'unsupported')
        self.assertEqual((data['unsupported']['type'], data['unsupported']['code']), ('poll_creation', 131051))
        self.assertEqual(preview(data), 'Poll: WhatsApp does not share poll contents with business accounts. Ask the customer to reply in text.')

    def test_a_customer_poll_vote_says_why_it_is_missing(self):
        self.assertTrue(preview(self.extract('poll_update')).startswith('Poll vote: WhatsApp does not share poll votes'))

    def test_a_tap_on_our_poll_keeps_the_option_and_the_quoted_poll(self):
        message = {'id': 'wamid.vote', 'from': NUMBER, 'timestamp': '1792948421', 'type': 'interactive',
                   'context': {'from': '919876543210', 'id': 'wamid.poll'},
                   'interactive': {'type': 'button_reply', 'button_reply': {'id': 'poll-2', 'title': 'Blue'}}}
        row, = projection.extract_messages({'entry': [{'changes': [{'value': {'messages': [message]}}]}]})
        self.assertEqual(row['provider_context']['reply_to_message_id'], 'wamid.poll')
        self.assertEqual(row['message_data'], {'kind': 'text', 'text': 'Blue', 'selection_id': 'poll-2'})


if __name__ == '__main__':
    unittest.main()
