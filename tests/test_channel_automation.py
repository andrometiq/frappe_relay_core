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
