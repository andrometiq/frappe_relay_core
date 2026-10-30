import json
import unittest
from contextlib import nullcontext
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import frappe
from frappe import _dict
from relay_core.automation import channel, service
from relay_core.flows import service as flows
from relay_core.ai import service as ai


def row(kind, **values):
    return dict(step=kind, enabled=1, on_reply='Continue', **values)


class ChannelHoursTests(unittest.TestCase):
    def test_local_hours_boundaries_and_weekends(self):
        config = _dict(timezone='Asia/Kolkata', open_time='09:00:00', close_time='18:00:00', working_days='Monday\nTuesday')
        for stamp, outside in [('2026-10-26T03:29:00+00:00', True), ('2026-10-26T03:30:00+00:00', False),
                               ('2026-10-26T12:30:00+00:00', True), ('2026-10-25T06:00:00+00:00', True)]:
            with self.subTest(stamp=stamp):
                self.assertEqual(channel.outside_hours(config, datetime.fromisoformat(stamp)), outside)

    def test_overnight_hours_belong_to_the_opening_day(self):
        config = _dict(timezone='UTC', open_time='22:00:00', close_time='06:00:00', working_days='Monday')
        for stamp, outside in [('2026-10-26T23:00:00', False), ('2026-10-27T05:59:00', False),
                               ('2026-10-27T06:00:00', True), ('2026-10-25T23:00:00', True)]:
            self.assertEqual(channel.outside_hours(config, datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)), outside)

    def test_timezone_handles_dst_without_fixed_offsets(self):
        config = _dict(timezone='America/New_York', open_time='09:00:00', close_time='17:00:00', working_days='Monday')
        self.assertFalse(channel.outside_hours(config, datetime.fromisoformat('2026-07-06T13:00:00+00:00')))
        self.assertTrue(channel.outside_hours(config, datetime.fromisoformat('2026-12-07T13:00:00+00:00')))

    def test_empty_steps_preserve_defaults_and_disabled_rows_need_no_hours(self):
        self.assertEqual(channel.steps(_dict()), [])
        self.assertTrue(channel.enabled(_dict()))
        self.assertFalse(channel.enabled(_dict(automation_enabled=0)))
        with patch.object(channel, 'outside_hours', side_effect=AssertionError('disabled step evaluated')):
            self.assertEqual(channel.evaluate(row('Out of hours reply') | {'enabled': 0}, _dict(), _dict()), (False, 'Step disabled'))

    def test_only_one_responder_but_enrichment_can_continue(self):
        for kind in ('Flow', 'AI skill', 'Out of hours reply'):
            self.assertFalse(channel.decision(row(kind), flow=True, ai=True, outside=True, claimed=True)[0])
        self.assertTrue(channel.decision(row('Assign'), claimed=True)[0])
        for rule, resolved, expected in [('Never', False, False), ('Always', True, True),
                                        ('Create if not resolved', True, False), ('Create if not resolved', False, True)]:
            self.assertEqual(channel.decision(row('Ticket', ticket_rule=rule), claimed=True, resolved=resolved)[0], expected)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.message = _dict(name='msg', relay_contact='person', channel='channel', content='Order 1250', business_doctype='Customer')
        self.run = _dict(name='run', message='msg', execution_user='manager', ticket='ticket', generation=0,
                         status='Pending', stage='Channel', reload=Mock())
        self.fake = Mock(PermissionError=PermissionError, ValidationError=ValueError)
        self.fake.get_doc.return_value = self.message
        self.enterContext(patch.object(channel, 'frappe', self.fake))
        self.enterContext(patch('relay_core.ai.tools.as_user', side_effect=lambda user: nullcontext()))
        self.scope = self.enterContext(patch.object(channel, 'delivery_scope', return_value=_dict()))
        self.enterContext(patch.object(channel, 'ticket_resolved', return_value=False))
        self.enterContext(patch.object(channel, 'ai_available', return_value=True))
        self.enterContext(patch.object(channel, 'outside_hours', return_value=True))
        self.enterContext(patch('relay_core.features.is_enabled', return_value=True))
        self.enterContext(patch.object(flows, 'claims', return_value=True))
        self.save = self.enterContext(patch.object(service, 'internal_save'))
        self.triage = self.enterContext(patch.object(service, 'triage'))
        self.flow = self.enterContext(patch.object(flows, 'create_event'))
        self.assign = self.enterContext(patch('relay_core.teams.assign'))
        self.ticket = self.enterContext(patch.object(flows, 'flow_ticket'))
        self.reply = self.enterContext(patch.object(ai, 'send_reply', return_value={'status': 'Submitted'}))
        self.select = self.enterContext(patch.object(ai, 'select_skill'))
        self.enterContext(patch.object(ai, 'continue_search', return_value=False))

    def process(self, rows):
        self.run.pipeline_state = json.dumps(dict(steps=rows, index=0))
        channel.process(self.run)

    def test_order_assign_flow_ticket_suppresses_competing_ai_and_reply(self):
        calls = []
        self.assign.side_effect = lambda *args: calls.append('assign')
        self.flow.side_effect = lambda *args: calls.append('flow')
        self.ticket.side_effect = lambda *args: calls.append('ticket')
        self.process([row('Assign', team='support', user='agent'), row('Flow'), row('AI skill', ai_skill='skill'),
                      row('Ticket', ticket_rule='Always'), row('Out of hours reply', message='Closed')])
        self.assertEqual(calls, ['assign', 'flow', 'ticket'])
        self.assertEqual(self.run.status, 'Completed')
        self.reply.assert_not_called(); self.select.assert_not_called(); self.triage.assert_not_called()

    def test_stop_prevents_later_assignment(self):
        self.process([row('Flow') | {'on_reply': 'Stop'}, row('Assign', team='support')])
        self.flow.assert_called_once(); self.assign.assert_not_called()

    def test_selected_ai_uses_existing_skill_run_after_enrichment(self):
        self.process([row('AI skill', ai_skill='skill'), row('Ticket', ticket_rule='Always'), row('Flow')])
        self.select.assert_called_once_with(self.run, self.message, 'skill')
        self.ticket.assert_called_once(); self.flow.assert_not_called()
        self.assertEqual(self.fake.enqueue.call_args.args[0], 'relay_core.automation.service.process')

    def test_uncertain_reply_keeps_position_and_reuses_it_after_hours_change(self):
        self.reply.return_value = {'status': 'Uncertain'}
        self.process([row('Out of hours reply', message='Closed'), row('Assign', team='support')])
        self.assertEqual(json.loads(self.run.pipeline_state)['inflight'], 0)
        self.assign.assert_not_called()
        self.reply.return_value = {'status': 'Submitted'}
        with patch.object(channel, 'outside_hours', return_value=False):
            channel.process(self.run)
        self.assertEqual(self.reply.call_count, 2)
        self.assign.assert_called_once()
        self.assertEqual(self.run.status, 'Completed')

    def test_ownership_loss_prevents_all_steps(self):
        self.scope.side_effect = ai.Superseded('Taken over')
        self.process([row('Flow'), row('Assign', team='support')])
        self.flow.assert_not_called(); self.assign.assert_not_called(); self.triage.assert_not_called()
        self.assertEqual(self.run.status, 'Cancelled')

    def test_rejected_reply_cannot_fall_through(self):
        self.reply.return_value = {'status': 'Rejected'}
        self.process([row('Out of hours reply', message='Closed'), row('Assign', team='support')])
        self.assign.assert_not_called(); self.triage.assert_called_once()


class ChannelApiTests(unittest.TestCase):
    def setUp(self):
        self.fake = Mock(PermissionError=PermissionError, ValidationError=ValueError, _dict=_dict,
                         conf={'relay_automation_enabled': 1})
        self.fake.throw.side_effect = lambda message, *args: (_ for _ in ()).throw(ValueError(message))
        self.doc = _dict(name='channel', title='Support', channel='WhatsApp', enabled=1, automation_enabled=1,
                         modified='revision', check_permission=Mock(), save=Mock())
        self.doc.set = lambda key, value: self.doc.update({key: value})
        self.fake.get_doc.return_value = self.doc
        self.enterContext(patch.object(channel, 'frappe', self.fake))
        self.access = self.enterContext(patch.object(channel, 'require_access'))

    def test_channel_picker_labels_and_search_include_provider_and_address(self):
        self.fake.get_list.return_value = [
            _dict(name='wa', title='yrp', channel='WhatsApp', address='+91 98000 00001'),
            _dict(name='mail', title='yrp', channel='Email', address='help@example.invalid')]
        rows = channel.references('channel', '98000')
        self.assertEqual(rows[0], dict(value='wa', label='WhatsApp · yrp · +91 98000 00001', icon='message-circle'))
        self.assertEqual(rows[1]['label'], 'Email · yrp · help@example.invalid')
        self.assertEqual(self.fake.get_list.call_args.kwargs['or_filters'], [
            [field, 'like', '%98000%'] for field in ('name', 'title', 'channel', 'address')])

    def test_customizing_defaults_keeps_automatic_skill_matching(self):
        self.doc.automation_steps = channel.DEFAULT_STEPS
        with patch.object(channel, 'validate_skill') as validate_skill:
            channel.validate(self.doc)
        validate_skill.assert_not_called()

    def test_hours_use_utc_by_default_and_only_enabled_hours_steps_require_times(self):
        self.doc.automation_steps = [row('Out of hours reply', message='We are closed.')]
        self.doc.update(timezone='', open_time='09:00', close_time='17:00', working_days='Monday')
        channel.validate(self.doc)
        self.assertFalse(channel.outside_hours(self.doc, datetime(2026, 10, 26, 10, tzinfo=timezone.utc)))
        self.doc.open_time = None
        with self.assertRaisesRegex(ValueError, 'opening and closing times'):
            channel.validate(self.doc)
        self.doc.automation_steps = [row('Flow')]
        channel.validate(self.doc)

    def test_read_exposes_effective_defaults_without_saving_them(self):
        result = channel.read('channel')
        self.assertEqual(result['steps'], [])
        self.assertEqual([row['step'] for row in result['defaults']], ['Flow', 'AI skill'])
        self.assertEqual(result['timezone_default'], 'UTC')
        self.doc.save.assert_not_called()

    def test_save_is_allowlisted_and_checks_revision(self):
        for values, revision in [({'company': 'other'}, 'revision'), ({'automation_enabled': 1, 'steps': []}, 'stale'),
                                 ({'automation_enabled': 1, 'steps': [row('Flow', injected='bad')]}, 'revision')]:
            with self.assertRaises(ValueError):
                channel.save('channel', values, revision)
        self.doc.save.assert_not_called()
        channel.save('channel', {'automation_enabled': 0, 'steps': []}, 'revision')
        self.access.assert_called_with(manage=True)
        self.doc.save.assert_called_once_with(ignore_permissions=True)
        self.assertEqual(self.doc.automation_enabled, 0)

    @patch('relay_core.ai_features.is_enabled', return_value=True)
    def test_partial_save_preserves_every_omitted_field(self, enabled):
        self.doc.update(timezone='UTC', open_time='09:00', close_time='17:00', working_days='Monday',
                        automation_steps=[row('Flow')])
        channel.save('channel', {'steps': [row('AI skill')]}, 'revision')
        self.assertEqual(self.doc.automation_enabled, 1)
        self.assertEqual(self.doc.open_time, '09:00')
        self.assertEqual(self.doc.automation_steps, [row('AI skill')])
        channel.save('channel', {'open_time': '10:00'}, 'revision')
        self.assertEqual(self.doc.open_time, '10:00')
        self.assertEqual(self.doc.close_time, '17:00')
        self.assertEqual(self.doc.automation_steps, [row('AI skill')])
        channel.save('channel', {'automation_enabled': 0}, 'revision')
        channel.save('channel', {'steps': []}, 'revision')
        self.assertEqual(self.doc.automation_enabled, 0)
        self.assertEqual(self.doc.automation_steps, [])

    def test_partial_save_still_rejects_invalid_explicit_values(self):
        for values in ({'automation_enabled': None}, {'automation_enabled': '1'},
                       {'automation_enabled': 2}, {'steps': None}, {'steps': [row('Flow') | {'enabled': None}]}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                channel.save('channel', values, 'revision')
        self.doc.save.assert_not_called()

    def test_preview_checks_active_episode_instead_of_closed_source_ticket(self):
        message = _dict(name='msg', relay_contact='person', channel='channel', ticket='closed-ticket',
                        provider_context='{}', direction='Incoming')
        person = _dict(automation_paused=0)
        self.fake.get_doc.side_effect = lambda dt, name: {
            'Relay Channel': self.doc, 'Relay Message': message, 'Relay Contact': person}[dt]
        self.fake.get_list.return_value = [message.name]
        self.doc.automation_steps = [row('Flow')]
        active = {'held': None}
        def lookup(dt, filters, field):
            self.assertEqual((dt, filters, field), ('Relay Ticket', {'active_scope_key': 'current-scope'}, 'ai_disabled'))
            return active['held']
        self.fake.db.get_value.side_effect = lookup
        with patch.object(service, 'frappe', self.fake), \
             patch('relay_core.tickets._episode_scope', return_value=({}, 'current-scope')), \
             patch('relay_core.permissions.readable_contact'), patch('relay_core.opt_out.is_keyword', return_value=False), \
             patch.object(channel, 'identity'), patch.object(channel, 'owns_reply', return_value=False), \
             patch.object(channel, 'ai_available', return_value=False), \
             patch.object(channel, 'ticket_resolved', return_value=True), \
             patch.object(channel, 'evaluate', return_value=(True, 'Flow matched')), \
             patch.object(service, 'staff_owned', wraps=service.staff_owned) as ownership:
            for held, paused, runs in ((None, 0, True), (0, 0, True), (1, 0, False), (None, 1, False)):
                with self.subTest(held=held, paused=paused):
                    active['held'], person.automation_paused = held, paused
                    result = channel.dry_run('channel', 'Order 1250', contact='person')
                    self.assertEqual(result['trace'][0]['runs'], runs)
                    ownership.assert_called_with(person, message=message)
                    # Admission passes the episode it has resolved; both paths use this check.
                    self.assertEqual(service.staff_owned(person, ticket=_dict(ai_disabled=held or 0)), not runs)
        self.doc.save.assert_not_called()
        self.fake.db.commit.assert_not_called()
        self.fake.db.set_value.assert_not_called()

    def test_non_manager_cannot_save(self):
        self.access.side_effect = PermissionError()
        with self.assertRaises(PermissionError):
            channel.save('channel', {'automation_enabled': 1, 'steps': []}, 'revision')
        self.doc.save.assert_not_called()

    def test_consent_and_human_requests_stop_preview_without_writes(self):
        with patch('relay_core.opt_out.is_keyword', return_value=True):
            self.assertIn('Consent keyword', channel.dry_run('channel', 'STOP')['trace'][0]['reason'])
        with patch('relay_core.opt_out.is_keyword', return_value=False):
            self.assertIn('requested a person', channel.dry_run('channel', 'I want a human')['trace'][0]['reason'])
        self.doc.save.assert_not_called(); self.fake.enqueue.assert_not_called(); self.fake.db.set_value.assert_not_called()

    def test_dry_run_and_runtime_share_ordered_decisions(self):
        self.doc.automation_steps = [row('Out of hours reply', message='Closed') | {'on_reply': 'Stop'}, row('Flow')]
        with patch('relay_core.opt_out.is_keyword', return_value=False), patch.object(channel, 'outside_hours', return_value=True), \
             patch('relay_core.features.is_enabled', return_value=True), patch.object(flows, 'matching', return_value='flow'):
            result = channel.dry_run('channel', '/help')
        self.assertEqual([item['step'] for item in result['trace']], ['Pre-checks', 'Out of hours reply'])
        self.assertTrue(result['trace'][-1]['runs'])
        self.fake.db.commit.assert_not_called()
