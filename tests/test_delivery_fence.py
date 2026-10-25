"""Automatic admission, recovery and lifecycle intent ownership boundaries."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core import messaging, email


class DeliveryFenceTests(unittest.TestCase):
    def setUp(self):
        self.ticket = _dict(name='episode', generation=0, ai_disabled=0, active_scope_key='scope')
        self.source = _dict(name='source', channel='channel', relay_contact='person', sender_endpoint='peer')
        self.rows = self.enterContext(patch.object(messaging, 'delivery_episodes', return_value=[self.ticket]))

    def action(self, **values):
        payload = dict(automation_run='run', delivery_episodes=[['episode', 0]], **values)
        return _dict(name='action', status='Dispatching', payload=json.dumps(payload), reload=Mock(), result='{}')

    def test_ai_origins_stop_but_manual_and_business_notices_remain_available(self):
        self.ticket.ai_disabled = 1
        for marker in ('automation_run', 'flow_run', 'notification', 'routing', 'email_values'):
            value = {'auto_submitted': 1} if marker == 'email_values' else 'intent'
            with self.subTest(marker=marker), self.assertRaises(messaging.DeliverySuppressed):
                messaging.delivery_fence(_dict(payload=json.dumps({marker:value})), self.source, {})
        messaging.delivery_fence(_dict(payload='{}'), self.source, {})

    def test_business_notices_survive_takeover_resume_and_release_without_becoming_manual(self):
        payload = dict(business_event='event', delivery_episodes=[['episode', 0]])
        for context in ({'provider': 'WhatsApp'}, {'provider': 'Telegram'}, {'provider': 'Email'}):
            for change in ({'ai_disabled': 1}, {'generation': 2}, {'active_scope_key': None}):
                with self.subTest(context=context, change=change), patch.dict(self.ticket, change):
                    self.assertTrue(messaging.automatic_delivery(payload))
                    messaging.delivery_fence(_dict(payload=json.dumps(payload)), self.source, context)
        self.rows.assert_not_called()
        # AI provenance must still fence an action even if it also has an event.
        self.ticket.ai_disabled = 1
        for marker in ('automation_run', 'flow_run'):
            with self.subTest(marker=marker), self.assertRaises(messaging.DeliverySuppressed):
                messaging.delivery_fence(_dict(payload=json.dumps(dict(payload, **{marker: 'run'}))), self.source, {})

    def test_resume_release_replacement_and_legacy_intents_never_revive_old_work(self):
        action = self.action()
        messaging.delivery_fence(action, self.source, {})
        for change in ({'generation':2}, {'active_scope_key':None}, {'name':'replacement'}):
            with self.subTest(change=change), patch.dict(self.ticket, change):
                with self.assertRaises(messaging.DeliverySuppressed):
                    messaging.delivery_fence(action, self.source, {})
        self.ticket.generation = 2
        with self.assertRaises(messaging.DeliverySuppressed):
            messaging.delivery_fence(_dict(payload='{"automation_run":"legacy"}'), self.source, {})
        fresh = {'automation_run':'fresh'}
        messaging.delivery_snapshot(fresh, self.source, {})
        messaging.delivery_fence(_dict(payload=json.dumps(fresh)), self.source, {})

    def test_pending_fixed_email_cannot_first_journal_after_resume(self):
        self.ticket.update(generation=2, ownership_at='2026-10-25 12:00:00')
        self.source.creation='2026-10-25 11:00:00'
        payload={'email_values':{'auto_submitted':1}}
        messaging.delivery_snapshot(payload,self.source,{})
        with self.assertRaises(messaging.DeliverySuppressed):
            messaging.delivery_fence(_dict(payload=json.dumps(payload)),self.source,{})
        self.source.creation='2026-10-25 12:01:00'
        messaging.delivery_fence(_dict(payload=json.dumps(payload)),self.source,{})

    def test_lifecycle_snapshot_comes_from_original_intent(self):
        payload = {'business_event':'event'}
        fake = SimpleNamespace(get_doc=Mock(return_value=_dict(payload='{"delivery_episodes":[["old",0]]}')))
        with patch.object(messaging, 'frappe', fake):
            messaging.delivery_snapshot(payload, self.source, {})
        self.assertEqual(payload['delivery_episodes'], [['old',0]])
        self.rows.assert_not_called()

    def test_suppression_preserves_accepted_and_uncertain_transport_evidence(self):
        fake = SimpleNamespace(db=Mock())
        with patch.object(messaging, 'frappe', fake), patch.object(messaging, 'internal_save') as save:
            for state in ('Queued','Uncertain','Submitted'):
                action = self.action(); action.status = state
                self.assertEqual(messaging.suppress_delivery(action)['status'], state)
            save.assert_not_called()
            action = self.action()
            result = messaging.suppress_delivery(action)
            self.assertEqual(result['status'], 'Rejected')
            self.assertTrue(json.loads(action.result)['suppressed'])
            self.assertIn('staff', result['error'])
            save.assert_called_once_with(action)

    def test_email_rechecks_after_its_preparation_commit(self):
        action = self.action(email_values={})
        fake = SimpleNamespace(db=Mock(), TimestampMismatchError=type('TimestampMismatchError',(Exception,),{}),
            ValidationError=ValueError,PermissionError=PermissionError,DoesNotExistError=LookupError)
        def admission(_):
            if fake.db.commit.called:
                raise messaging.DeliverySuppressed('claimed during commit')
        with patch.object(email, 'frappe', fake), patch.object(email, 'prepare', return_value={'body':'Amount 1250'}), \
                patch.object(messaging, 'admission_scope', side_effect=admission) as check, \
                patch('relay_core.automation.service.internal_save'), \
                patch.object(messaging, 'suppress_delivery', return_value={'status':'Rejected'}) as suppress, \
                patch.object(email.whatsapp, 'client') as hub:
            self.assertEqual(email.submit(action), {'status':'Rejected'})
        self.assertEqual(check.call_count, 2)
        suppress.assert_called_once_with(action)
        hub.assert_not_called()

    def test_chat_and_email_projection_keep_journal_episode_after_source_changes(self):
        source = _dict(name='source',channel='channel',relay_contact='contact',sender_endpoint='peer',
            ticket='replacement',business_doctype='Supplier',business_name='supplier')
        payload = dict(ticket='original',business=['Supplier','supplier'],email_request='request',
            email_values=dict(to=['peer@example.invalid'],subject='Review',body='Amount 1250'),
            arguments={'in_reply_to':'<incoming@example.invalid>'})
        action = _dict(name='action',operation='text',request_key='stable',source_message='source',
            owner='staff',payload=json.dumps(payload),result='{}',reload=Mock())
        fake=SimpleNamespace(db=Mock(),session=SimpleNamespace(user='staff'),get_doc=lambda values:_dict(values,name='outgoing'))
        fake.db.get_value.return_value=None
        with patch.object(messaging,'frappe',fake),patch.object(email,'frappe',fake), \
                patch.object(messaging,'internal_save'),patch('relay_core.ticket_notifications.insert_message') as insert:
            messaging.finish(action,source,_dict(channel='Telegram'),{},dict(kind='text',text='Amount 1250'),{'message_id':42})
            self.assertEqual(insert.call_args.args[0].ticket,'original')
            with patch.object(email,'target',return_value=(source,_dict(name='channel',account='local'),
                    {'provider':'Email','email_thread_id':'<thread@example.invalid>'})):
                email.project(action,{'message_id':'<outgoing@example.invalid>'})
            self.assertEqual(insert.call_args.args[0].ticket,'original')

    def test_suppressed_lifecycle_is_retained_and_never_auto_replayed(self):
        from relay_core import business_events
        self.assertEqual(business_events.delivery_status('Rejected', {'suppressed':True}), 'Suppressed')
        self.assertEqual(business_events.delivery_status('Rejected'), 'Failed')
        self.assertEqual(business_events.delivery_status('Queued'), 'Queued')


class DeliveryScopeTests(unittest.TestCase):
    def test_email_choice_prompt_uses_its_thread_not_other_held_threads(self):
        from relay_core import tickets, business_routing_prompt as prompts
        state = _dict(prompt_action='prompt', relay_contact='contact', channel='email',
                      endpoint='peer@example.invalid', conversation_key='new-thread')
        fake = SimpleNamespace(db=Mock(), qb=Mock(), _dict=_dict, get_doc=Mock(return_value=_dict(
            enabled=1, channel='Email', account='local')))
        fake.db.get_value.return_value = 'contact'
        fake.qb.get_query.return_value.run.return_value = []
        action = _dict(name='prompt', start_contact='contact', payload='{"routing":"new-thread","context":{"provider":"Email"}}')
        with patch.object(prompts, 'frappe', fake), patch.object(prompts, 'require_access'), \
                patch.object(prompts, 'routing_state', return_value=state), \
                patch.object(prompts, 'connection_value', return_value='local'), \
                patch.object(messaging, 'frappe', fake), patch.object(tickets, '_lock_episode_routing'):
            source, _, context = prompts.target(action)
            messaging.delivery_fence(action, source, context)
            fake.qb.get_query.assert_called_once()
            self.assertEqual(fake.qb.get_query.call_args.args, ('Relay Ticket',))
            self.assertEqual(fake.qb.get_query.call_args.kwargs['filters']['conversation_key'], 'new-thread')
            # A hold in this exact thread still stops its pending prompt.
            fake.qb.get_query.return_value.run.return_value = ['held']
            fake.get_doc.return_value = _dict(name='held', active_scope_key='scope', ai_disabled=1, generation=1)
            with self.assertRaises(messaging.DeliverySuppressed):
                messaging.delivery_fence(action, source, context)

    def test_queries_use_company_business_and_exact_conversation_with_current_locks(self):
        from relay_core import tickets
        source = _dict(name='source',channel='channel',sender_endpoint='peer',relay_contact='contact',
                       business_doctype='Supplier',business_name='supplier',conversation_key='topic')
        fake = SimpleNamespace(db=Mock(),qb=Mock(),get_doc=Mock())
        fake.db.get_value.return_value='company'
        fake.qb.get_query.return_value.run.return_value=['episode']
        with patch.object(messaging,'frappe',fake),patch.object(tickets,'_lock_episode_routing') as lock:
            messaging.delivery_episodes(source, {'provider':'Telegram'})
        self.assertEqual(fake.qb.get_query.call_args.kwargs['filters'],dict(company='company',
            business_doctype='Supplier',business_name='supplier',conversation_key='topic'))
        self.assertTrue(fake.qb.get_query.call_args.kwargs['for_update'])
        fake.get_doc.assert_called_once_with('Relay Ticket','episode',for_update=True)
        lock.assert_called_once_with(source,'topic')

    def test_unresolved_assignment_allows_routing_until_staff_claims(self):
        from relay_core import tickets
        source=_dict(channel='channel',sender_endpoint='peer',relay_contact='contact')
        triage=_dict(name='triage',ai_disabled=1,source_hub_event='event',generation=1)
        fake=SimpleNamespace(db=Mock(),qb=Mock(),get_doc=Mock(return_value=triage))
        fake.db.get_value.return_value='company'
        fake.qb.get_query.return_value.run.return_value=['triage']
        with patch.object(messaging,'frappe',fake),patch.object(tickets,'_lock_episode_routing'):
            self.assertEqual(messaging.delivery_episodes(source,{}),[])
            for actor in ('Sim Staff','Administrator'):
                triage.ownership_actor=actor
                self.assertEqual(messaging.delivery_episodes(source,{}),[triage])
        self.assertIn(['source_hub_event','is','set'],fake.qb.get_query.call_args.kwargs['or_filters'])

    def test_standalone_email_checks_all_endpoint_threads_and_bounds_work(self):
        from relay_core import tickets
        source = _dict(channel='email',sender_endpoint='peer@example.invalid',relay_contact='contact',
                       business_doctype='Supplier',business_name='supplier')
        fake = SimpleNamespace(db=Mock(),qb=Mock(),get_doc=Mock())
        fake.db.get_value.return_value='company'
        fake.qb.get_query.return_value.run.side_effect=[['thread-one','thread-two'],[]]
        with patch.object(messaging,'frappe',fake),patch.object(tickets,'_lock_episode_routing'):
            self.assertEqual(messaging.delivery_episodes(source,{'provider':'Email'}),[])
            self.assertEqual(fake.qb.get_query.call_args.kwargs['filters']['conversation_key'],
                             ['in',['thread-one','thread-two']])
            fake.qb.get_query.return_value.run.side_effect=[list(range(101))]
            with self.assertRaises(messaging.DeliverySuppressed):
                messaging.delivery_episodes(source,{'provider':'Email'})
