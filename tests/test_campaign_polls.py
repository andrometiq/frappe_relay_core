"""Poll campaigns: a template button tap asks the poll, a pick asks to confirm, Confirm ends it and opt-out opts out."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe import _dict

from channel_fakes import FakeSite
from relay_core import bulk_campaigns, campaign_polls, messaging
from relay_core.automation import queue, service

CHANNEL, NUMBER, OTHER = 'Acme-WA', '910000000001', '910000000002'
ROW = 'bulk-0a1b2c3d4e5f6a7b-1'
BUTTONS = {'type': 'BUTTONS', 'buttons': [{'type': 'QUICK_REPLY', 'text': 'Interested'},
                                          {'type': 'QUICK_REPLY', 'text': 'Opt out'}, {'type': 'URL', 'text': 'Visit'}]}
POLL = {'question': 'Which size?', 'options': ['Small', 'Large'], 'opt_in': 'Interested', 'opt_out': 'Opt out',
        'thanks': campaign_polls.THANKS}


def throw(message):
    raise frappe.ValidationError(message)


def snapshot(poll=None, components=(BUTTONS,)):
    return {'template': {'name': 'poll_invite', 'components': [{'type': 'BODY', 'text': 'Hi'}, *components]},
            'fields': [], **({'poll': poll} if poll is not None else {})}


class PollSettingsTests(unittest.TestCase):
    def test_quick_reply_buttons_come_from_the_template(self):
        self.assertEqual(campaign_polls.template_buttons(snapshot()), ['Interested', 'Opt out'])
        self.assertEqual(campaign_polls.template_buttons({'message': {'kind': 'text'}}), [])

    def test_settings_keep_the_mapped_buttons_question_and_options(self):
        data = {'question': ' Which size? ', 'options': ['Small', 'Large'], 'opt_in': 'Interested', 'opt_out': ''}
        self.assertEqual(campaign_polls.settings(snapshot(), data), {**POLL, 'question': 'Which size?', 'opt_out': ''})

    def test_invalid_settings_are_refused(self):
        good = {'question': 'Q', 'options': ['A', 'B'], 'opt_in': 'Interested'}
        for data, source in [({**good, 'opt_in': 'Visit'}, snapshot()), ({**good, 'opt_out': 'Interested'}, snapshot()),
                             ({**good, 'opt_out': 'Stop'}, snapshot()), ({**good, 'options': ['A']}, snapshot()),
                             ({**good, 'options': ['x' * 21, 'B']}, snapshot()), ({**good, 'extra': 1}, snapshot()),
                             (good, snapshot(components=()))]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                campaign_polls.settings(source, data)

    def test_a_poll_campaign_sends_only_after_the_poll_is_set_up(self):
        self.assertTrue(campaign_polls.is_ready(snapshot()))
        self.assertFalse(campaign_polls.is_ready(snapshot({})))
        self.assertTrue(campaign_polls.is_ready(snapshot(POLL)))


class PollCampaignTests(unittest.TestCase):
    def create(self, components, **values):
        hub = Mock()
        hub.execute.return_value = {'data': [{'name': 'poll_invite', 'language': 'en', 'status': 'APPROVED',
                                              'components': [{'type': 'BODY', 'text': 'Hi'}, *components]}]}
        saved = []
        fake = SimpleNamespace(db=Mock(exists=Mock(return_value=False)), utils=frappe.utils, throw=throw,
                               get_doc=lambda values: _dict(values))
        with patch.object(bulk_campaigns, 'require_access'), patch.object(bulk_campaigns, 'campaign_channel', return_value='WA'), \
                patch.object(bulk_campaigns, 'frappe', fake), patch.object(bulk_campaigns, 'channel_region', return_value='IN'), \
                patch.object(bulk_campaigns, 'connection_value', return_value='acct'), patch.object(bulk_campaigns, 'phase'), \
                patch.object(bulk_campaigns, 'internal_save', side_effect=lambda doc, new=False: saved.append(doc)), \
                patch.object(bulk_campaigns, 'read', side_effect=lambda name: saved[-1]), \
                patch.object(bulk_campaigns.whatsapp, 'checked_client', return_value=(hub, {})), \
                patch('relay_core.whatsapp_templates.overlay', side_effect=lambda page: page), \
                patch.object(bulk_campaigns, 'hub_arguments', side_effect=lambda channel, arguments: arguments):
            return bulk_campaigns.create('Poll launch', 'poll_invite', 'en', **values)

    def test_a_poll_campaign_needs_a_quick_reply_template_and_starts_unset(self):
        doc = self.create([BUTTONS], poll=1)
        self.assertEqual(json.loads(doc.arguments)['poll'], {})
        self.assertNotIn('poll', json.loads(self.create([BUTTONS]).arguments))
        with self.assertRaisesRegex(frappe.ValidationError, 'quick reply button'):
            self.create([], poll=1)

    def test_sending_waits_for_the_poll_set_up(self):
        doc = _dict(arguments=json.dumps(snapshot({})), status='Running')
        with patch.object(bulk_campaigns.frappe, 'throw', throw), \
                self.assertRaisesRegex(frappe.ValidationError, 'Set up the poll'):
            bulk_campaigns.check_validation(doc)
        bulk_campaigns.check_validation(_dict(doc, arguments=json.dumps(snapshot(POLL))))


class PollSiteTests(unittest.TestCase):
    def setUp(self):
        self.site = FakeSite(
            Relay_Campaign=[{'name': 'Poll launch', 'channel': CHANNEL, 'execution_user': 'manager@example.com',
                             'arguments': json.dumps(snapshot(POLL))},
                            {'name': 'Plain launch', 'channel': CHANNEL, 'arguments': json.dumps(snapshot())}],
            Relay_Campaign_Recipient=[{'name': ROW, 'campaign': 'Poll launch', 'destination': NUMBER, 'provider_id': 'wamid.sent',
                                       'arguments': json.dumps({'values': {}})},
                                      {'name': 'bulk-0a1b2c3d4e5f6a7b-2', 'campaign': 'Plain launch', 'destination': NUMBER,
                                       'provider_id': 'wamid.plain', 'arguments': '{}'}])
        self.site.frappe.db.set_value = self.site.set_value
        self.opt_outs, self.changed = [], []
        for item in (patch.object(campaign_polls, 'frappe', self.site.frappe),
                     patch('relay_core.opt_out.set_choice', lambda *args: self.opt_outs.append(args)),
                     patch('relay_core.bulk_updates.changed', self.changed.append)):
            item.start()
            self.addCleanup(item.stop)

    def tap(self, text, quoted='wamid.sent', sender=NUMBER, channel=CHANNEL, name='MSG-1'):
        return _dict(name=name, direction='Incoming', message_type='text', channel=channel, sender_endpoint=sender,
                     sent_at='2026-11-26 10:00:00', message_data=json.dumps(
                         {'kind': 'text', 'text': text, 'selection_id': text, 'selection_type': 'template_button'}),
                     provider_context=json.dumps({'provider': 'WhatsApp', 'reply_to_message_id': quoted}))

    def pick(self, value, sender=NUMBER, name='MSG-2'):
        return _dict(name=name, direction='Incoming', message_type='text', channel=CHANNEL, sender_endpoint=sender,
                     sent_at='2026-11-26 10:01:00', message_data=json.dumps({'kind': 'text', 'text': 'x', 'selection_id': value}),
                     provider_context=json.dumps({'provider': 'WhatsApp', 'reply_to_message_id': 'wamid.prompt'}))

    def state(self):
        return json.loads(self.site.rows('Relay Campaign Recipient', {'name': ROW})[0].arguments).get('poll')

    def replies(self):
        return [(job[1]['kind'], job[1]['data']) for job in self.site.queued]

    def test_the_opt_in_button_on_the_campaign_message_is_claimed(self):
        step = campaign_polls.claim(self.tap('Interested'))
        self.assertEqual((step.recipient, step.campaign, step.step, step.user), (ROW, 'Poll launch', 'in', 'manager@example.com'))
        self.assertEqual(campaign_polls.claim(self.tap('Opt out')).step, 'out')

    def test_other_taps_and_other_messages_are_not_claimed(self):
        plain = _dict(self.tap('Interested'), message_data=json.dumps({'kind': 'text', 'text': 'Interested'}))
        for message in [self.tap('Something else'), self.tap('Interested', quoted='wamid.other'),
                        self.tap('Interested', quoted=''), self.tap('Interested', sender=OTHER),
                        self.tap('Interested', channel='Other-WA'), self.tap('Interested', quoted='wamid.plain'), plain,
                        self.pick('cpoll:bulk-0a1b2c3d4e5f6a7b-2:0'), self.pick(f'cpoll:{ROW}:0', sender=OTHER), self.pick('poll-1'),
                        _dict(self.tap('Interested'), direction='Outgoing')]:
            with self.subTest(message=message):
                self.assertIsNone(campaign_polls.claim(message))

    def test_opt_in_pick_and_confirm_record_one_final_answer(self):
        campaign_polls.on_message(self.tap('Interested'))
        self.assertEqual(self.state()['state'], 'Asked')
        kind, data = self.replies()[-1]
        self.assertEqual((kind, data['body']), ('choices', 'Which size?'))
        self.assertEqual([row['value'] for row in data['choices']], [f'cpoll:{ROW}:0', f'cpoll:{ROW}:1'])

        campaign_polls.on_message(self.pick(f'cpoll:{ROW}:1'))
        self.assertEqual((self.state()['state'], self.state()['option']), ('Chosen', 1))
        kind, data = self.replies()[-1]
        self.assertEqual(data['body'], 'You chose: Large\nConfirm your answer?')
        self.assertEqual([row['label'] for row in data['choices']], ['Confirm', 'Change'])

        campaign_polls.on_message(self.pick(f'cpoll:{ROW}:confirm:1', name='MSG-3'))
        self.assertEqual((self.state()['state'], self.state()['option'], self.state()['message']), ('Confirmed', 1, 'MSG-3'))
        self.assertEqual(self.replies()[-1], ('text', {'text': campaign_polls.THANKS}))
        self.assertEqual(self.changed, ['Poll launch'] * 3)

    def test_after_confirm_every_tap_is_answered_already_recorded(self):
        for message in [self.tap('Interested'), self.pick(f'cpoll:{ROW}:0'), self.pick(f'cpoll:{ROW}:confirm:0')]:
            campaign_polls.on_message(message)
        for message in [self.pick(f'cpoll:{ROW}:1'), self.pick(f'cpoll:{ROW}:change'), self.tap('Interested'),
                        self.pick(f'cpoll:{ROW}:confirm:0')]:
            campaign_polls.on_message(message)
            self.assertEqual(self.replies()[-1], ('text', {'text': campaign_polls.ALREADY}))
        self.assertEqual((self.state()['state'], self.state()['option']), ('Confirmed', 0))

    def test_change_asks_again_and_a_stale_confirm_is_ignored(self):
        for message in [self.tap('Interested'), self.pick(f'cpoll:{ROW}:0'), self.pick(f'cpoll:{ROW}:change')]:
            campaign_polls.on_message(message)
        self.assertEqual(self.replies()[-1][1]['body'], 'Which size?')
        sent = len(self.site.queued)
        campaign_polls.on_message(self.pick(f'cpoll:{ROW}:confirm:0'))
        self.assertEqual((self.state()['state'], len(self.site.queued)), ('Asked', sent))
        campaign_polls.on_message(self.pick(f'cpoll:{ROW}:1'))
        campaign_polls.on_message(self.pick(f'cpoll:{ROW}:confirm:1'))
        self.assertEqual((self.state()['state'], self.state()['option']), ('Confirmed', 1))

    def test_a_closed_poll_records_and_sends_nothing(self):
        closed = {'question': 'Which size?', 'options': ['Small', 'Large'], 'closed': 1}
        for step in ('in', '0', 'confirm:0', 'change'):
            with self.subTest(step=step):
                self.assertEqual(campaign_polls.advance({'state': 'Chosen', 'option': 0}, step, ROW, closed),
                                 ({'state': 'Chosen', 'option': 0}, None))

    def test_opt_out_opts_the_number_out_and_sends_nothing(self):
        campaign_polls.on_message(self.tap('Opt out'))
        self.assertEqual(self.opt_outs, [(CHANNEL, NUMBER, True)])
        self.assertEqual((self.state()['state'], self.site.queued), ('Opted out', []))
        campaign_polls.on_message(self.tap('Interested'))
        self.assertEqual((self.state()['state'], self.site.queued), ('Opted out', []))

    def test_a_reply_goes_once_per_tap_as_the_campaign_user(self):
        campaign_polls.on_message(self.tap('Interested'))
        args, kwargs = self.site.queued[0]
        self.assertEqual((args, kwargs['message'], kwargs['user'], kwargs['enqueue_after_commit']),
                         (('relay_core.campaign_polls.send_reply',), 'MSG-1', 'manager@example.com', True))

    def test_counts_per_option_waiting_and_opted_out(self):
        rows = [_dict(state='Confirmed', choice='1', count=4), _dict(state='Chosen', choice='1', count=2),
                _dict(state='Confirmed', choice='0', count=1), _dict(state='Asked', choice='null', count=3),
                _dict(state='Opted out', choice=None, count=5)]
        self.site.frappe.db.sql = Mock(return_value=rows)
        result = campaign_polls.summary('Poll launch', snapshot(POLL))
        self.assertEqual(result['results'], [{'label': 'Small', 'confirmed': 1, 'pending': 0},
                                             {'label': 'Large', 'confirmed': 4, 'pending': 2}])
        self.assertEqual((result['waiting'], result['opted_out'], result['buttons']), (3, 5, ['Interested', 'Opt out']))


class PollSendTests(unittest.TestCase):
    def test_send_reply_marks_the_send_as_a_poll_step_with_a_stable_key(self):
        seen = []

        def send_one(message, kind, data, request_key, quote=1):
            seen.append((message, kind, request_key, messaging.outgoing_poll.get()))
            return {'status': 'Submitted'}
        fake = Mock(session=_dict(user='Guest'))
        with patch.object(campaign_polls, 'frappe', fake), patch.object(messaging, 'send_one', send_one):
            campaign_polls.send_reply('MSG-1', 'text', {'text': 'Thanks'}, 'manager@example.com')
        self.assertEqual(seen, [('MSG-1', 'text', 'campaign-poll-MSG-1', 'MSG-1')])
        self.assertEqual([call.args[0] for call in fake.set_user.call_args_list], ['manager@example.com', 'Guest'])
        self.assertIsNone(messaging.outgoing_poll.get())

    def test_a_poll_step_is_automatic_and_not_stopped_by_staff_ownership(self):
        payload = {'campaign_poll': 'MSG-1', 'delivery_episodes': []}
        self.assertTrue(messaging.automatic_delivery(payload))
        with patch.object(messaging, 'delivery_episodes', side_effect=AssertionError('no ownership check')):
            messaging.delivery_fence(_dict(payload=json.dumps(payload)), _dict(), {})


class PollAdmissionTests(unittest.TestCase):
    def test_the_poll_handler_runs_first_in_the_inbound_drain(self):
        self.assertEqual(queue.HANDLERS[0], 'relay_core.campaign_polls.on_message')

    def test_a_claimed_tap_starts_no_automation_flow_or_ticket(self):
        message = _dict(name='MSG-1', direction='Incoming', content='Interested', relay_contact='CON-1')
        with patch('relay_core.campaign_polls.claims', return_value=True), patch('relay_core.opt_out.is_keyword', return_value=False):
            self.assertEqual(service.create_run(message), {'status': 'Ignored'})

    def test_a_claimed_tap_is_not_handed_to_an_agent(self):
        from relay_core.ai import hand_over
        message = _dict(name='MSG-1', direction='Incoming', relay_contact='CON-1', message_type='text')
        with patch.object(hand_over.ai_features, 'is_enabled', return_value=True), \
                patch.object(hand_over.features, 'is_automation_allowed', return_value=True), \
                patch('relay_core.automation.provenance.context_of', return_value={'provider': 'WhatsApp'}), \
                patch('relay_core.email_preferences.automatic_allowed', return_value=True), \
                patch('relay_core.opt_out.is_keyword', return_value=False), \
                patch.object(hand_over, 'is_group', return_value=False), \
                patch('relay_core.campaign_polls.claims', return_value=True), \
                patch.object(hand_over, 'live_agent_skill', side_effect=AssertionError('no agent')):
            self.assertIsNone(hand_over.agent_skill(message))


if __name__ == '__main__':
    unittest.main()
