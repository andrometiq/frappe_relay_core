"""Failure, authorization and ingestion contracts for the WhatsApp v1 journal."""
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import frappe
from frappe import _dict


class DispatchRecoveryTests(unittest.TestCase):
    def setUp(self):
        from relay_core import messaging
        self.api = messaging
        self.payload = {'tool':'whatsapp.execute','arguments':{'operation':'messages.send','to':'15550000001','body':'Hello'},'content':{'kind':'text','text':'Hello'}}
        self.action = _dict(name='action',status='Dispatching',request_key='original-key',source_message='source',payload=json.dumps(self.payload),check_permission=Mock())
        self.source = _dict(name='source',relay_contact='contact',channel='channel',sender_endpoint='15550000001')
        self.channel = _dict(channel='WhatsApp',name='channel')
        self.hub = Mock()
        self.finish = Mock(return_value={'status':'Submitted'})
        for fixture in (patch.object(messaging,'frappe',SimpleNamespace(get_doc=Mock(return_value=self.action))),
                        patch.object(messaging,'readable_source',return_value=(self.source,self.channel,{})),
                        patch.object(messaging,'require_reply_window'),patch.object(messaging.whatsapp,'client',return_value=self.hub),
                        patch.object(messaging,'finish',self.finish)):
            fixture.start();self.addCleanup(fixture.stop)

    def test_never_admitted_dispatch_is_resubmitted_with_original_key(self):
        self.hub.call_tool.side_effect=[{'deliveries':[]},{'messages':[{'id':'provider-id'}]}]
        self.assertEqual(self.api.reconcile('action'),{'status':'Submitted'})
        self.assertEqual(self.hub.call_tool.call_args.args,('whatsapp.execute',dict(self.payload['arguments'],request_key='original-key')))

    def test_uncertain_never_blind_resends_even_when_lookup_is_empty(self):
        self.action.status='Uncertain';self.hub.call_tool.return_value={'deliveries':[]}
        with self.assertRaises(ValueError):self.api.reconcile('action')
        self.hub.call_tool.assert_called_once_with('whatsapp.deliveries',{'request_key':'original-key'})
        self.finish.assert_not_called()

    def test_missing_malformed_or_failed_lookup_does_not_resend(self):
        for response in ({}, {'deliveries':None}, {'deliveries':[{'key':'other'}]}):
            self.hub.reset_mock();self.hub.call_tool.return_value=response
            with self.assertRaises(ValueError):self.api.reconcile('action')
            self.assertEqual(self.hub.call_tool.call_count,1)
        self.hub.reset_mock();self.hub.call_tool.side_effect=TimeoutError
        with self.assertRaises(TimeoutError):self.api.reconcile('action')
        self.assertEqual(self.hub.call_tool.call_count,1)

    def test_hub_uncertainty_and_submitted_results_are_reconciled_without_send(self):
        for state in ('uncertain','submitted'):
            row={'key':'original-key','state':state,'result':{'messages':[{'id':'provider-id'}]}}
            self.hub.reset_mock();self.hub.call_tool.return_value={'deliveries':[row]}
            self.api.reconcile('action')
            self.assertEqual(self.hub.call_tool.call_count,1)
            self.assertEqual(self.finish.call_args.args[-1],row['result'] if state=='submitted' else {'delivery':row})

    def test_retry_preserves_original_business_and_revalidates_target(self):
        from relay_core import conversation_start
        intent={'contact':'contact','endpoint':'endpoint','kind':'text','data':{'text':'Hello'},'business_doctype':'Customer','business_name':'customer-two'}
        self.action.update(owner='sender',status='Rejected',start_contact='contact',payload=json.dumps({'start':intent}))
        self.api.frappe.session=SimpleNamespace(user='sender')
        with patch.object(self.api,'require_access'),patch.object(conversation_start,'action_target') as target,patch.object(conversation_start,'send') as send:
            self.api.retry('action')
        target.assert_called_once_with(self.action)
        self.assertEqual(send.call_args.args[-2:],('Customer','customer-two'))


class CallbackBoundaryTests(unittest.TestCase):
    def test_event_guard_rejects_document_flags_and_resets_after_failure(self):
        from relay_core import inbound
        from relay_core.relay_core.doctype.relay_hub_event.relay_hub_event import RelayHubEvent
        doc=object.__new__(RelayHubEvent)
        doc.flags=_dict(ignore_permissions=True,relay_authenticated_callback=True)
        with patch.object(frappe,'throw',side_effect=PermissionError):
            with self.assertRaises(PermissionError):doc.validate()
        with patch.object(inbound.frappe,'get_doc') as get_doc:
            def fail(**kwargs):
                doc.validate()
                raise RuntimeError('fixture insert failure')
            get_doc.return_value.insert.side_effect=fail
            with self.assertRaises(RuntimeError):inbound.insert_event({'event_key':'fixture'})
        self.assertFalse(inbound.callback_write.get())

    def test_mixed_envelope_splits_fast_messages_from_receipts(self):
        from relay_core.inbound import split_payload
        from relay_core.automation.projection import projection_queue
        message={'id':'incoming','from':'15550000001','type':'text','text':{'body':'Hello'}}
        statuses=[{'id':'outgoing','recipient_id':'15550000001','status':'read','timestamp':'1'}]*500
        payload={'entry':[{'changes':[{'field':'messages','value':{'messages':[message],'statuses':statuses}}]}]}
        parts=split_payload(payload)
        self.assertEqual([suffix for suffix,_ in parts],['',':updates'])
        self.assertEqual([projection_queue(part) for _,part in parts],['short','long'])
        self.assertNotIn('statuses',parts[0][1]['entry'][0]['changes'][0]['value'])
        self.assertEqual(len(parts[1][1]['entry'][0]['changes'][0]['value']['statuses']),500)
        self.assertIn('statuses',payload['entry'][0]['changes'][0]['value'])


class IncomingBusinessTests(unittest.TestCase):
    def test_only_verified_same_conversation_reply_context_selects_business(self):
        from relay_core import business_access
        links=[('Customer','one'),('Customer','two')]
        db=Mock();db.get_value.return_value=_dict(business_doctype='Customer',business_name='two')
        with patch.object(business_access,'candidates',return_value=links),patch.object(business_access,'frappe',SimpleNamespace(db=db)):
            self.assertEqual(business_access.incoming_reference('contact','channel','15550000001',{'reply_to_message_id':'provider'}),links[1])
            filters=db.get_value.call_args.args[1]
            self.assertEqual(filters['sender_endpoint'],'15550000001')
            self.assertEqual(filters['channel'],'channel')
            self.assertEqual(filters['relay_contact'],'contact')
            self.assertIsNone(business_access.incoming_reference('contact','channel','15550000001',{}))
            db.get_value.return_value=_dict(business_doctype='Customer',business_name='unlinked')
            self.assertIsNone(business_access.incoming_reference('contact','channel','15550000001',{'reply_to_message_id':'provider'}))

    def test_ambiguous_message_remains_in_manager_triage(self):
        from relay_core.automation import projection
        from relay_core import business_access, whatsapp_templates
        payload={'entry':[{'changes':[{'value':{'messages':[{'id':'in','from':'15550000001','type':'text','text':{'body':'Choose my business'}}]}}]}]}
        event=_dict(name='event',account='fixture',payload=json.dumps(payload),projection_status='Pending')
        db=Mock();db.exists.return_value=False;db.get_value.return_value='contact'
        fake=SimpleNamespace(db=db,get_doc=Mock(return_value=event),get_all=Mock(return_value=['channel']))
        with patch.object(projection,'frappe',fake),patch.object(projection,'apply_updates',return_value='Ignored'),patch.object(whatsapp_templates,'project',return_value=False),patch.object(business_access,'incoming_reference',return_value=None),patch('relay_core.call_records.ingest',return_value=False),patch('relay_core.realtime.changed'):
            projection.project('event')
        fake.get_doc.assert_called_once_with('Relay Hub Event','event')
        db.set_value.assert_called_with('Relay Hub Event','event','projection_status','Uncategorized')


class TemplateLifecycleTests(unittest.TestCase):
    def test_lifecycle_updates_record_and_publishes_without_provider_call(self):
        from relay_core import whatsapp_templates
        doc=_dict(hub_event_id='4')
        fake=SimpleNamespace(db=Mock(),get_doc=Mock(return_value=doc),publish_realtime=Mock(),realtime=SimpleNamespace(get_doctype_room=lambda dt:dt))
        fake.db.get_value.return_value='record'
        payload={'entry':[{'changes':[{'field':'message_template_status_update','value':{'message_template_id':123,'message_template_name':'welcome','message_template_language':'en_US','event':'APPROVED'}}]}]}
        with patch.object(whatsapp_templates,'frappe',fake),patch.object(whatsapp_templates,'internal_save') as save:
            self.assertTrue(whatsapp_templates.project(payload,_dict(account='fixture',hub_event_id='5')))
            self.assertEqual(doc.status,'APPROVED')
            save.assert_called_once_with(doc,new=False)
            fake.publish_realtime.assert_called_once_with('relay_changed',{'kind':'templates'},room='Relay WhatsApp Template',after_commit=True)
            whatsapp_templates.project(payload,_dict(account='fixture',hub_event_id='3'))
            self.assertEqual(save.call_count,1)


class IngestionCursorTests(unittest.TestCase):
    def test_ingestion_order_uses_journal_identity_instead_of_provider_time(self):
        from relay_core import timeline
        from pypika import Query, Table
        message=Table('tabRelay Message')
        qb=SimpleNamespace(DocType=lambda dt:message,get_query=lambda *a,**kw:Query.from_(message).select(message.name))
        anchor=_dict(name='RELAY-MSG-0000000002',sent_at='2030-01-01',creation='2026-10-24',relay_contact='contact',channel='channel',check_permission=Mock())
        fake=SimpleNamespace(qb=qb,conf=SimpleNamespace(db_type='postgres'),get_doc=Mock(return_value=anchor))
        with patch.object(timeline,'frappe',fake),patch('relay_core.permissions.readable_contact'):
            sql=str(timeline.page_query(['name'],{},50,after=anchor.name,ingestion=True))
        self.assertIn('"name">\'RELAY-MSG-0000000002\'',sql)
        self.assertNotIn('2030-01-01',sql)
        self.assertNotIn('COALESCE',sql)


class AutomationDispatchTests(unittest.TestCase):
    def test_automation_uses_source_action_with_run_and_stable_key(self):
        from relay_core.automation import service
        from relay_core import messaging, whatsapp
        submission={'key':'stable-outbox-key','operation':'messages.send','arguments':{'body':'Approved reply'},'contact':'person','business_doctype':'Customer','business_name':'customer'}
        payload=json.dumps(submission)
        out=_dict(name='outbox',run='run',status='Pending',payload=payload,payload_hash=hashlib.sha256(payload.encode()).hexdigest(),reply='reply',reply_version='v1',recipient='15550000001',reload=Mock())
        run=_dict(name='run',policy='policy',execution_user='actor',message='source',policy_version='v1',generation=1)
        policy=_dict(name='policy',enabled=1,modified='v1')
        message=_dict(name='source',channel='channel',relay_contact='contact',sender_endpoint='15550000001',check_permission=Mock())
        contact=_dict(name='contact',automation_generation=1,check_permission=Mock())
        reply=_dict(body='Approved reply',ai_enabled=1,published=1,modified='v1')
        docs={'Relay Automation Outbox':out,'Relay Automation Run':run,'Relay Automation Policy':policy,'Relay Message':message,'Relay Canned Reply':reply}
        fake=SimpleNamespace(session=SimpleNamespace(user='worker'),db=Mock(),get_doc=lambda dt,name:docs[dt],set_user=Mock(),conf={'relay_automation_enabled':1},PermissionError=PermissionError,DoesNotExistError=LookupError)
        fake.db.get_value.return_value='contact'
        def send(*args,**kwargs):
            self.assertEqual(service.outgoing_run.get(),'run')
            return {'action':'action','status':'Queued'}
        with patch.object(service,'now_datetime',return_value=__import__('datetime').datetime(2026,10,24)),patch.object(service,'frappe',fake),patch.object(service,'check_actor'),patch.object(service,'lock_contact',return_value=contact),patch.object(service,'latest_message',return_value=True),patch.object(service,'business_scope',return_value=(_dict(name='person'),_dict(name='channel',channel='WhatsApp'),'Customer','customer')),patch.object(service,'internal_save'),patch.object(whatsapp,'prepare',return_value={'to':'15550000001'}),patch.object(messaging,'send',side_effect=send) as submit:
            service.dispatch('outbox');service.dispatch('outbox')
        submit.assert_called_once_with('source','text',{'text':'Approved reply'},'stable-outbox-key',quote=0)
        self.assertEqual(json.loads(out.result)['action'],'action')
        self.assertIsNone(service.outgoing_run.get())


class DisabledSurfaceTests(unittest.TestCase):
    def test_campaign_mutations_are_removed_and_whatsapp_scheduler_cannot_send(self):
        from relay_core import campaigns
        for name in ('create','add_recipients','control','refresh'):
            self.assertFalse(hasattr(campaigns,name))
        fake=SimpleNamespace(db=Mock(),cache=Mock())
        fake.db.get_value.return_value='messages.send'
        with patch.object(campaigns,'frappe',fake):campaigns.process('existing-campaign')
        fake.cache.lock.assert_not_called()

    def test_group_message_builder_rejects_before_preparation(self):
        from relay_core import messaging
        with patch.object(messaging,'_prepare') as prepare:
            with self.assertRaises(ValueError):messaging.prepare(_dict(),_dict(channel='WhatsApp'),{'group_id':'group'},'text',{'text':'Hello'})
            prepare.assert_not_called()

    def test_triage_realtime_is_manager_scoped_without_raw_event_rest_access(self):
        from relay_core import realtime
        fake=SimpleNamespace(get_all=Mock(return_value=['manager']),publish_realtime=Mock())
        with patch.object(realtime,'frappe',fake):realtime.changed(_dict(doctype='Relay Hub Event'))
        self.assertEqual({call.kwargs['user'] for call in fake.publish_realtime.call_args_list},{'Administrator','manager'})
        self.assertTrue(all(call.args[1]=={'kind':'incoming'} for call in fake.publish_realtime.call_args_list))
        metadata=json.loads(__import__('pathlib').Path('relay_core/relay_core/doctype/relay_hub_event/relay_hub_event.json').read_text())
        self.assertFalse(any(row.get('create') or row.get('write') for row in metadata['permissions']))

    def test_malformed_provider_event_is_retained_for_failed_projection(self):
        from relay_core.inbound import split_payload
        from relay_core.automation.projection import projection_queue
        payload={'entry':[{'changes':[{'value':{'messages':[None]}}]}]}
        self.assertEqual(split_payload(payload),[('',payload)])
        self.assertEqual(projection_queue(payload),'long')


class OutgoingProjectionTests(unittest.TestCase):
    def test_immediate_reaction_acknowledgement_projects_on_loaded_message(self):
        from relay_core import conversation_start, messaging, whatsapp
        source = _dict(relay_contact='contact', channel='channel', sender_endpoint='15550000001',
                       business_doctype='Customer', business_name='customer')
        quoted = _dict(source, doctype='Relay Message', name='quoted',
                       reactions=json.dumps({'peer':[{'type':'emoji','emoji':'❤'}]}))
        quoted.check_permission = Mock()
        quoted.reload = Mock()
        channel = _dict(name='channel', channel='WhatsApp')
        args = {'operation':'messages.react','to':source.sender_endpoint,'reply_to':'provider','emoji':'👍'}
        action = None

        def get_doc(doctype, name=None):
            nonlocal action
            if isinstance(doctype, dict):
                action = _dict(doctype, name='action')
                action.reload = Mock()
                return action
            self.assertEqual((doctype, name), ('Relay Message', 'quoted'))
            return quoted

        db = Mock()
        db.get_value.side_effect = lambda dt, *a, **kw: {
            'Relay Message Action':None, 'Relay Contact':'person', 'Relay Message':'quoted',
        }[dt]
        fake = SimpleNamespace(db=db, get_doc=get_doc, session=SimpleNamespace(user='sender'),
                               PermissionError=PermissionError, ValidationError=ValueError)
        hub = Mock()
        hub.call_tool.return_value = {'success':True}
        with patch.object(conversation_start,'frappe',fake), patch.object(messaging,'frappe',fake), \
             patch.object(conversation_start,'target',side_effect=lambda *a:(_dict(source),channel,{'provider':'WhatsApp'})), \
             patch.object(whatsapp,'prepare',return_value=args), patch.object(whatsapp,'client',return_value=hub), \
             patch.object(conversation_start.service_window,'require_open'), \
             patch.object(conversation_start,'internal_save'), patch.object(messaging,'internal_save') as save, \
             patch('relay_core.realtime.changed') as changed:
            result = conversation_start.send('contact','endpoint','whatsapp',
                {'operation':'messages.react','arguments':{'reply_to':'provider','emoji':'👍'}},
                'reaction-key','Customer','customer')
        self.assertEqual(result, {'action':'action','status':'Submitted','message':None})
        self.assertEqual(action.status, 'Submitted')
        self.assertEqual(json.loads(action.result), {'success':True})
        quoted.reload.assert_called_once_with()
        changed.assert_called_once_with(quoted)
        saved = db.set_value.call_args.args
        self.assertEqual(saved[:3], ('Relay Message','quoted','reactions'))
        self.assertEqual(json.loads(saved[3]), {
            'peer':[{'type':'emoji','emoji':'❤'}], 'bot':[{'type':'emoji','emoji':'👍'}],
        })
        hub.call_tool.assert_called_once_with('whatsapp.execute',dict(args,request_key=action.request_key))
        save.assert_called_once_with(action)
        self.assertEqual(db.commit.call_count, 2)

    def test_finish_uses_persisted_business_and_applies_early_receipt(self):
        from relay_core import messaging, whatsapp_receipts
        action=_dict(name='action',status='Queued',operation='text',request_key='key',payload=json.dumps({'business':['Customer','original'],'arguments':{}}),reload=Mock())
        source=_dict(relay_contact='contact',channel='channel',sender_endpoint='15550000001',business_doctype='Customer',business_name='changed')
        channel=_dict(channel='WhatsApp',name='channel')
        created=[]
        def get_doc(values):
            doc=_dict(values,name='outgoing');doc.insert=Mock(return_value=doc);created.append(doc);return doc
        fake=SimpleNamespace(db=Mock(),get_doc=get_doc)
        with patch.object(messaging,'frappe',fake),patch.object(messaging,'internal_save'),patch.object(whatsapp_receipts,'lock_endpoints'),patch.object(whatsapp_receipts,'apply_pending') as pending:
            result=messaging.finish(action,source,channel,{'provider':'WhatsApp'},{'kind':'text','text':'Hello'},{'messages':[{'id':'provider'}]})
        self.assertEqual(result,{'action':'action','status':'Submitted','message':'outgoing'})
        self.assertEqual(created[0].business_name,'original')
        pending.assert_called_once_with(created[0])

    def test_pushed_whatsapp_outcome_finishes_action_once_without_network(self):
        from relay_core import channel_statuses, messaging
        action=_dict(name='action',status='Queued',request_key='key',source_message='source',owner='sender',payload=json.dumps({'content':{'kind':'text','text':'Hello'}}),check_permission=Mock())
        source=_dict(name='source');channel=_dict(channel='WhatsApp',account='fixture')
        fake=SimpleNamespace(db=Mock(),get_doc=Mock(return_value=action),session=SimpleNamespace(user='worker'),set_user=Mock(),PermissionError=PermissionError,DoesNotExistError=LookupError)
        fake.db.get_value.return_value='action'
        row={'id':1,'request_key':'key','operation':'whatsapp.execute','state':'submitted','receipt':{'message_id':'provider'}}
        def finish(*args,**kwargs):action.status='Submitted'
        with patch.object(channel_statuses,'frappe',fake),patch.object(channel_statuses,'connection_value',return_value='fixture'),patch.object(messaging,'readable_source',return_value=(source,channel,{})),patch.object(messaging,'finish',side_effect=finish) as project,patch.object(messaging.whatsapp,'client') as hub:
            channel_statuses.project_batch(_dict(name='event',account='fixture'),[row])
            channel_statuses.project_batch(_dict(name='event',account='fixture'),[row])
        project.assert_called_once()
        self.assertEqual(project.call_args.args[-1]['messages'],[{'id':'provider'}])
        self.assertFalse(project.call_args.kwargs['commit'])
        hub.assert_not_called()
