"""Regression coverage for the backend review boundaries and recovery paths."""
import json
import unittest
from datetime import datetime
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe import _dict
from relay_core import business_access, cases, channel_statuses, collaboration, delivery, email_preferences, legacy, messaging, permissions, telegram, tickets
from relay_core.automation import projection, queue
from relay_core.flows import service as flows
from relay_core.ai.ledger import summarize
from test_business_routing import RoutingFixtures


class RoutingRegression(RoutingFixtures, unittest.TestCase):
    def test_missing_explicit_parent_never_uses_single_or_previous_business(self):
        for links in (self.links, self.links[:1]):
            self.links = links
            self.resolve(override=links[0])
            business, rule = self.resolve(context={'reply_to_message_id': 'not-stored-yet'})
            self.assertIsNone(business)
            self.assertEqual(rule, 'triage_unresolved_reference')


class BackendFindings(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('relay_core.business_access.relay_user', return_value=True))

    def fake(self):
        f = Mock(session=_dict(user='manager'), PermissionError=PermissionError,
                 DoesNotExistError=LookupError, ValidationError=ValueError,
                 QueryDeadlockError=type('Deadlock', (Exception,), {}))
        def throw(text, exception=ValueError): raise exception(text)
        f.throw = throw
        f._dict = _dict
        return f

    def test_import_upgrades_only_proven_unscoped_baselines(self):
        from relay_core import legacy_metadata
        for dt,collection in [('Relay Internal Comment','notes'),('Relay Conversation Topic','topics')]:
            for explicit in (False,True):
                f=self.fake();f.db.exists.return_value=True
                current={'name':'imported','relay_contact':'contact','body':'Locally edited',
                         'title':'Locally edited','business_doctype':'Supplier' if explicit else None,
                         'business_name':'supplier' if explicit else None}
                fields={'relay_contact':'contact','body':'Old text','title':'Old text'}
                identity='relay-history-'+legacy.source_key('source',dt+':old')
                baseline={identity:{'name':'imported','fields':fields}}
                def get_value(doctype,key,columns,**kwargs):
                    if columns=='name':return 'imported'
                    return _dict({field:current.get(field) for field in columns})
                f.db.get_value.side_effect=get_value
                f.db.set_value.side_effect=lambda doctype,name,values,**kw:current.update(values)
                job=_dict(relay_contact='contact',business_doctype='Customer',business_name='customer',
                          user_mapping={'staff':'manager'},team_mapping={})
                manifest={'source_site':'source','metadata':{collection:[{'name':'old','user':'staff',
                          'content':'New text','title':'New text'}]}}
                with patch.object(legacy_metadata,'frappe',f), \
                        patch.object(legacy_metadata,'previous_projections',return_value=baseline):
                    legacy_metadata.import_metadata(job,manifest,{'mismatches':[]})
                self.assertEqual(current['business_name'],'supplier' if explicit else 'customer')
                self.assertEqual(current['body'],'Locally edited')
                self.assertEqual(current['title'],'Locally edited')

    def test_telegram_shared_group_requires_every_business_before_hub(self):
        f=self.fake(); f.get_doc.side_effect=[Mock(has_permission=lambda *a:True),Mock(has_permission=lambda *a:False)]
        with patch.object(telegram,'frappe',f), patch.object(telegram,'require_access'), \
                patch.object(telegram,'group_binding',return_value=('contact','channel')), \
                patch.object(business_access,'allowed_types',return_value={'Customer'}), \
                patch.object(business_access,'candidates',return_value=[('Customer','C'),('Supplier','S')]), \
                patch.object(telegram,'client') as hub:
            with self.assertRaises(PermissionError): telegram.groups('topics.delete',{'chat_id':-123,'message_thread_id':25})
            hub.assert_not_called()

    def test_business_event_names_do_not_contend_on_a_shared_series(self):
        schema=json.loads(Path('relay_core/relay_core/doctype/relay_business_event_delivery/relay_business_event_delivery.json').read_text())
        self.assertEqual(schema['autoname'],'format:RELAY-BED-{event_key}')

    def test_business_event_permission_denial_rolls_back_only_capture(self):
        from relay_core import business_events
        f=self.fake();f.flags=_dict();f.get_all.return_value=['rule']
        with patch.object(business_events,'frappe',f), \
                patch.object(business_events,'enabled_rule_pairs',return_value={('Sales Order','on_submit')}), \
                patch.object(business_events,'capture',side_effect=PermissionError) as capture, \
                patch.object(business_events,'log_failure'):
            business_events.on_event(_dict(doctype='Sales Order',name='SO'),'on_submit')
            f.db.rollback.assert_called_once_with(save_point='relay_business_event')
            capture.side_effect=f.QueryDeadlockError
            with self.assertRaises(f.QueryDeadlockError): business_events.on_event(_dict(doctype='Sales Order',name='SO'),'on_submit')
        self.assertFalse(f.flags.relay_business_event)

    def test_email_permanent_denial_and_retry_exhaustion_are_terminal(self):
        f=self.fake();f.db.get_value.return_value=_dict(email_reply_status='Pending',email_reply_attempts=5)
        for error in (PermissionError,TimeoutError):
            with patch.object(email_preferences,'frappe',f),patch.object(email_preferences,'deliver_reply',side_effect=error):
                email_preferences.auto_reply('message')
            self.assertEqual(f.db.set_value.call_args.args[2]['email_reply_status'],'Failed')

    def test_receipts_isolate_revoked_target_and_preserve_other_evidence(self):
        f = self.fake()
        f.db.get_value.side_effect = lambda dt, key, *args, **kw: key['request_key'] if isinstance(key, dict) else 1
        f.get_doc.side_effect = lambda dt, name: _dict(name=name, owner='manager', status='Submitted' if name=='bounce' else 'Queued', result='{}', operation='email' if name=='bounce' else 'business_prompt', check_permission=Mock())
        rows = [dict(request_key='revoked',operation='telegram.message',state='submitted',id=1),
                dict(request_key='bounce',operation='email.send',state='bounced',id=2)]
        with patch.object(channel_statuses, 'frappe', f), patch.object(channel_statuses, 'connection_value', return_value='account'), \
             patch.object(messaging, 'action_target', side_effect=[ValueError('Revoked endpoint'), (None,_dict(channel='Email',account='account'),{})]), \
             patch.object(channel_statuses, 'apply_email_evidence', return_value=True) as apply, patch('relay_core.realtime.incoming_changed'):
            channel_statuses.project_batch(_dict(name='event',account='account'),rows)
        apply.assert_called_once()
        f.db.rollback.assert_called_once_with(save_point='relay_status_row')
        f.db.set_value.assert_called_with('Relay Hub Event','event','projection_status','Uncategorized')

    def test_receipt_deadlock_is_never_swallowed(self):
        f=self.fake(); f.db.get_value.return_value='action'
        f.get_doc.return_value=_dict(name='action',owner='manager',status='Queued',result='{}',check_permission=Mock())
        with patch.object(channel_statuses,'frappe',f), patch.object(channel_statuses,'connection_value',return_value='a'), \
             patch.object(messaging,'action_target',side_effect=f.QueryDeadlockError):
            with self.assertRaises(f.QueryDeadlockError):
                channel_statuses.project_batch(_dict(account='a'),[dict(request_key='key',operation='telegram.message',state='submitted',id=1)])
        f.db.rollback.assert_not_called()

    def test_early_projection_failures_publish_incoming_invalidation(self):
        f=self.fake(); f.get_all.return_value=[]
        for payload, status in [('invalid','Failed'), ('{}','Uncategorized')]:
            f.get_doc.return_value=_dict(projection_status='Pending',payload=payload,account='account')
            with patch.object(projection,'frappe',f), patch('relay_core.hub_channels.frappe',f), patch('relay_core.realtime.incoming_changed') as publish:
                projection.project('event')
                publish.assert_called_once()
                f.db.set_value.assert_called_with('Relay Hub Event','event','projection_status',status)

    def test_long_email_identifiers_fit_schema_without_truncation(self):
        from relay_core.automation.provenance import email_message_id
        value='<'+('a'*120)+'@'+('b'*120)+'>'
        self.assertEqual(email_message_id(value),value)
        for dt,field,length in [('relay_message','provider_id',len(value)),('relay_message','sender_endpoint',200),('relay_contact_endpoint','endpoint',200)]:
            schema=json.loads(Path(f'relay_core/relay_core/doctype/{dt}/{dt}.json').read_text())
            self.assertGreaterEqual(next(f['length'] for f in schema['fields'] if f['fieldname']==field),length)

    def test_unsupported_drain_fails_before_locking_or_consuming_signal(self):
        f=self.fake(); f.db.db_type='sqlite'
        with patch.object(queue,'frappe',f), patch.object(queue.AUTOMATION,'release_signal') as release:
            with self.assertRaisesRegex(RuntimeError,'supports MariaDB and PostgreSQL'): queue.drain('token')
            release.assert_not_called(); f.db.sql.assert_not_called()

    def test_ledger_refuses_missing_or_mixed_company(self):
        for rows in ([dict(debit=25,credit=1)], [dict(company='',debit=25,credit=1)], [dict(company='INR company',debit=25,credit=1),dict(company='USD company',debit=3,credit=0)]):
            with self.assertRaises(ValueError): summarize(rows,False)

    def test_flow_claims_queued_trigger_before_run_exists(self):
        f=self.fake(); f.db.exists.return_value=True
        source=_dict(direction='Incoming',message_type='text')
        with patch.object(flows,'frappe',f), patch.object(flows,'context_of',return_value={'provider':'WhatsApp'}), \
             patch.object(flows,'matching',return_value=None), patch.object(flows,'active',return_value=None),patch.object(flows,'route',return_value='route'), \
             patch.object(flows.features,'is_enabled',return_value=True):
            self.assertTrue(flows.claims(source))
            f.db.exists.assert_called_with('Relay Flow Event',{'conversation_key':'route','status':'Pending'})

    def test_flow_runs_and_cases_check_specific_business(self):
        f=self.fake(); f.get_doc.return_value.check_permission.side_effect=PermissionError
        run=_dict(relay_contact='shared',business_doctype='Supplier',business_name='private')
        with patch.object(flows,'frappe',f), patch.object(flows,'readable_contact'), patch.object(business_access,'business_document',side_effect=PermissionError):
            with self.assertRaises(PermissionError): flows.readable_run(run)
        with patch.object(cases,'frappe',f), patch.object(business_access,'readable_business',side_effect=PermissionError):
            for call in (lambda:cases._read(run),lambda:cases.authorize(run,'recipient')):
                with self.assertRaises(PermissionError): call()

    def test_flow_reply_provenance_is_scoped_and_reset(self):
        run=_dict(name='run',version='v1',generation=2)
        def send(*args):
            self.assertEqual(messaging.outgoing_flow.get(),dict(name='run',version='v1',generation=2))
            return {'status':'Submitted'}
        with patch.object(messaging,'send',side_effect=send):
            flows.send(run,None,_dict(name='source'),_dict(channel='WhatsApp'),'Hello','key')
        self.assertIsNone(messaging.outgoing_flow.get())

    def test_handoff_confirmation_keeps_its_flow_provenance(self):
        run=_dict(name='run',version='v1',generation=2,status='Handoff')
        def send(*args):
            self.assertEqual(messaging.outgoing_flow.get(),dict(name='run',version='v1',generation=2,handoff=True))
            return {'status':'Submitted'}
        with patch.object(messaging,'send',side_effect=send):
            flows.send(run,None,_dict(name='source'),_dict(channel='WhatsApp'),'Hello','key')
        self.assertIsNone(messaging.outgoing_flow.get())
        f=self.fake();f.get_doc.return_value=run
        with patch.object(messaging,'frappe',f),patch.object(flows,'scope') as scope:
            source=_dict(name='source')
            messaging.automation_scope(_dict(payload={'flow_run':dict(name='run',version='v1',generation=2,handoff=True)}),source)
            scope.assert_called_once_with(run,source,handoff=True)

    def test_flow_recovery_checks_status_version_and_generation(self):
        f=self.fake(); f.get_doc.return_value=_dict(version='v1',generation=2,status='Cancelled')
        action=_dict(payload={'flow_run':dict(name='run',version='v1',generation=2)})
        with patch.object(messaging,'frappe',f),patch.object(flows,'scope',side_effect=ValueError('cancelled')) as scope:
            with self.assertRaises(ValueError): messaging.automation_scope(action,_dict(name='source'))
            scope.assert_called_once()
            f.get_doc.return_value.version='v2'; scope.reset_mock()
            with self.assertRaises(ValueError): messaging.automation_scope(action,_dict(name='source'))
            scope.assert_not_called()

    def test_flow_ticket_reuses_shared_episode(self):
        f=self.fake()
        source=_dict(name='message',business_doctype='Customer',business_name='customer')
        with patch.object(flows,'frappe',f), patch.object(tickets,'_save_episode') as save, patch.object(tickets,'ensure_episode',return_value=_dict(name='ticket')) as ensure:
            ticket = flows.flow_ticket(source,'Needs help')
            self.assertEqual((ticket.name, ticket.subject, ticket.brief), ('ticket','Needs help','Needs help'))
            save.assert_called_once_with(ticket)
        ensure.assert_called_once_with(source,owner='manager',subject='Needs help',reason='Needs help')
        f.get_doc.assert_not_called()

    def test_fixed_email_intent_is_written_before_hook_acknowledgement(self):
        f=self.fake(); f.db.exists.return_value=True
        with patch.object(email_preferences,'frappe',f),patch.object(email_preferences,'context_of',return_value={}), \
             patch.object(email_preferences,'skill_claims',return_value=False),patch.object(flows,'claims',return_value=False):
            email_preferences.on_message(_dict(name='message',direction='Incoming',channel='email'))
        f.db.set_value.assert_called_with('Relay Message','message','email_reply_status','Pending',update_modified=False)
        f.enqueue.assert_not_called()

    def test_fixed_email_failures_rotate_and_success_completes(self):
        f=self.fake()
        f.db.get_value.return_value=_dict(email_reply_status='Pending',email_reply_attempts=0)
        with patch.object(email_preferences,'frappe',f),patch.object(email_preferences,'deliver_reply',side_effect=TimeoutError) as send:
            email_preferences.auto_reply('message')
            values=f.db.set_value.call_args.args[2]
            self.assertEqual(values['email_reply_status'],'Pending')
            self.assertEqual(values['email_reply_attempts'],1)
            self.assertIn('email_reply_next_attempt',values)
            send.side_effect=None;email_preferences.auto_reply('message')
            f.db.set_value.assert_called_with('Relay Message','message','email_reply_status','Complete',update_modified=False)

    def test_deliveries_require_administrator_before_hub(self):
        f=self.fake()
        with patch.dict('sys.modules',frappe=f),patch.object(delivery,'client') as hub:
            for call in (lambda:delivery.page(), lambda:delivery.resolve(1,'rejected','Verified local evidence')):
                with self.assertRaises(PermissionError):call()
            hub.assert_not_called()

    def test_native_ticket_entry_role_does_not_bypass_message_access(self):
        f=self.fake();f.get_roles.return_value=['Relay Communication Manager'];f.get_doc.return_value.has_permission.return_value=False
        ticket=_dict(owner='manager',messages=[_dict(message='private')])
        with patch.object(tickets,'frappe',f):
            self.assertFalse(tickets.permission(ticket))

    def test_telegram_group_admin_requires_verified_readable_binding(self):
        f=self.fake();f.db.get_value.return_value=None;f.get_all.side_effect=[['channel'],[]]
        with patch.object(telegram,'frappe',f),patch.object(telegram,'require_access'),patch.object(telegram,'connection_value',return_value='account'),patch.object(telegram,'client') as hub:
            with self.assertRaises(PermissionError):telegram.groups('members.ban',{'chat_id':-123,'user_id':42})
            hub.assert_not_called()

    def test_legacy_timezone_conversion_is_absolute(self):
        with patch.object(frappe.utils,'get_system_timezone',return_value='UTC'):
            self.assertEqual(legacy.source_datetime('2026-10-01 05:30:00','Asia/Kolkata'),datetime(2026,10,1))

    def test_notification_preview_requires_full_comment_authorization(self):
        f=self.fake();f.get_all.return_value=[_dict(name='notification',relay_contact='shared',comment='private')]
        f.get_doc.return_value=_dict(deleted=0,body='Supplier private 4500')
        with patch.object(collaboration,'frappe',f),patch.object(collaboration,'require_access'),patch.object(collaboration,'readable_contact'),patch.object(collaboration,'serialize',side_effect=PermissionError):
            self.assertEqual(collaboration.notifications()['items'],[])

    def test_model_discovery_returns_ai_model_identifiers_and_enabled_accounts(self):
        f=self.fake();f.get_list.side_effect=[['account'],[_dict(name='MODEL',provider='OpenRouter',model='model-id')]]
        with patch.object(flows,'frappe',f),patch.object(flows,'require_access'):
            result=flows.providers('model')
        self.assertEqual(result,{'items':[_dict(name='MODEL',provider='OpenRouter',model='model-id')],'next':None})
        self.assertEqual(f.get_list.call_args.args,('AI Model',))
        self.assertEqual(f.get_list.call_args.kwargs['filters'],{'enabled':1,'account':['in',['account']]})

    def test_case_lists_filter_each_business_in_shared_contact(self):
        f=self.fake();f.get_all.return_value=[_dict(name='own'),_dict(name='private')]
        def authorize(doc):
            if doc.name=='private':raise PermissionError
        with patch.object(cases,'frappe',f),patch.object(cases,'require_access'),patch.object(cases,'readable_contact'),patch.object(cases,'authorize',side_effect=authorize):
            self.assertEqual([r.name for r in cases.directory('shared')['items']],['own'])
            self.assertEqual([r.name for r in cases.workspace()['items']],['own'])

    @patch('relay_core.business_access.business_document')
    def test_old_single_business_note_resolves_scope_for_replies(self, business):
        f=self.fake();f.parse_json.return_value=[]
        note=_dict(relay_contact='contact',messages='[]')
        with patch.object(collaboration,'frappe',f),patch.object(business_access,'reference',return_value=('Customer','customer')),patch.object(collaboration,'readable_contact'):
            collaboration.authorize(note)
        self.assertEqual((note.business_doctype,note.business_name),('Customer','customer'))

    @patch('relay_core.business_access.business_document')
    def test_business_note_requires_conversation_and_business(self, business):
        f=self.fake();f.parse_json.return_value=[]
        note=_dict(relay_contact='contact',messages='[]',business_doctype='Customer',business_name='private')
        with patch.object(collaboration,'frappe',f),patch.object(business_access,'allowed',return_value=False):
            with patch.object(collaboration,'readable_contact') as reader:
                self.assertIs(collaboration.authorize(note),note)
                reader.assert_called_once_with('contact')
                business.assert_called_with('Customer', 'private', None)
                business.side_effect = PermissionError
                with self.assertRaises(PermissionError): collaboration.authorize(note)
            with patch.object(collaboration,'readable_contact',side_effect=PermissionError):
                with self.assertRaises(PermissionError):collaboration.authorize(note)
            with patch.object(permissions,'can_read_contact_as',return_value=False):
                with self.assertRaises(PermissionError):collaboration.authorize(note,'outsider')
        self.assertEqual((note.business_doctype,note.business_name),('Customer','private'))

    @patch('relay_core.business_access.unlinked_contact', return_value=False)
    @patch('relay_core.business_access.business_document')
    def test_new_business_note_needs_link_and_business_access(self, business, unlinked):
        f=self.fake()
        with patch.object(collaboration,'frappe',f),patch.object(business_access,'candidates',return_value=[('Customer','C1')]),\
                patch.object(business_access,'primary',return_value=('Customer','C1')):
            self.assertEqual(collaboration.business_scope('linked',[]),('Customer','C1'))
            business.assert_called_once_with('Customer', 'C1')
            business.side_effect = PermissionError
            with self.assertRaises(PermissionError): collaboration.business_scope('linked', [])
            with patch.object(business_access,'frappe',f),self.assertRaises(ValueError):
                f.throw.side_effect=ValueError
                collaboration.business_scope('linked',[],'Customer','other')

    @patch('relay_core.business_access.unlinked_contact', return_value=True)
    def test_conversation_note_uses_conversation_read_rule(self, unlinked):
        f=self.fake();f.parse_json.return_value=[]
        note=_dict(relay_contact='unlinked',messages='[]',business_doctype=None,business_name=None)
        with patch.object(collaboration,'frappe',f),patch.object(business_access,'reference',return_value=None),patch.object(business_access,'readable_business') as business:
            with patch.object(collaboration,'readable_contact') as reader:
                self.assertIs(collaboration.authorize(note),note)
                reader.assert_called_once_with('unlinked')
            with patch.object(collaboration,'readable_contact',side_effect=PermissionError):
                with self.assertRaises(PermissionError):collaboration.authorize(note)
            with patch.object(permissions,'can_read_contact_as',return_value=False):
                with self.assertRaises(PermissionError):collaboration.authorize(note,'outsider')
            with patch.object(permissions,'can_read_contact_as',return_value=True):
                self.assertIs(collaboration.authorize(note,'teammate'),note)
            business.assert_not_called()

    def test_note_business_cannot_mix_customer_and_supplier_sources(self):
        f=self.fake();f.get_doc.side_effect=[_dict(business_doctype='Customer',business_name='C'),_dict(business_doctype='Supplier',business_name='S')]
        with patch.object(collaboration,'frappe',f):
            with self.assertRaises(PermissionError):collaboration.business_scope('shared',['one','two'])

    def test_note_recipients_are_checked_against_full_note_scope(self):
        f=self.fake();doc=_dict(relay_contact='shared')
        with patch.object(collaboration,'frappe',f),patch.object(permissions,'can_read_contact_as',return_value=True),patch.object(collaboration,'authorize',side_effect=PermissionError):
            with self.assertRaises(PermissionError):collaboration.recipients('shared',['customer-only'],doc)

    def test_old_identical_pass_cannot_lower_import_watermark(self):
        row=_dict(modified='2026-01-01',delivery_status='Sent')
        from relay_core import legacy_bundle
        existing=_dict(legacy_data=json.dumps({'row':row,'watermark':'2026-03-01'}),legacy_checksum=legacy_bundle.checksum(row))
        self.assertEqual(legacy.check_revision(existing,row,{'watermark':'2026-02-01'}),'2026-03-01')
        changed=_dict(row,delivery_status='Queued')
        with self.assertRaisesRegex(ValueError,'Conflicting'):legacy.check_revision(existing,changed,{'watermark':'2026-02-01'})

    def test_native_auxiliary_records_and_outbox_are_system_manager_only(self):
        from relay_core import hooks
        for dt in ('Relay Conversation Summary','Relay Message Translation','Relay Internal Comment','Relay Flow Run','Relay Automation Outbox'):
            slug=dt.lower().replace(' ','_')
            meta=json.loads(Path(f'relay_core/relay_core/doctype/{slug}/{slug}.json').read_text())
            self.assertEqual({row['role'] for row in meta['permissions']},{'System Manager'},dt)
            if dt in ('Relay Conversation Summary', 'Relay Message Translation'):
                self.assertEqual(hooks.has_permission[dt], 'relay_core.ai_features.document_permission')
                self.assertEqual(hooks.permission_query_conditions[dt], 'relay_core.ai_features.query_condition')
            else:
                self.assertNotIn(dt,hooks.has_permission)
                self.assertNotIn(dt,hooks.permission_query_conditions)
