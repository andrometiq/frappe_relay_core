"""Step 9 atomic takeover through real yrp.site HTTP, drain and worker paths.

External models, sends, queues and notifications are intercepted. Every inserted
fixture (including children and Companies) is removed in finally.
"""
import json
import os
from pathlib import Path
import secrets
import sys
from contextlib import ExitStack
from unittest.mock import patch
from types import SimpleNamespace

from integration_ai_permissions_site import confine_writes
from site_labels import run_label, phone

SITES = '/home/sakthi/development/pilot/benches/version_16/sites'
ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.addaudithook(confine_writes)
    os.environ.update(FRAPPE_STREAM_LOGGING='1', SITES_PATH=SITES)
    import frappe
    import frappe.app
    import relay_core
    from frappe.model.base_document import BaseDocument
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    from relay_core.ai import adapter, service as ai
    from relay_core.automation import service
    from relay_core.automation.provenance import conversation_key
    from relay_core.permissions import sequential_name

    assert Path(relay_core.__file__).resolve().parents[1] == ROOT
    os.chdir(SITES)
    def connect():
        if not getattr(frappe.local, 'db', None):
            frappe.init(site='yrp.site', sites_path=SITES); frappe.connect()
        assert frappe.local.site == 'yrp.site'
        frappe.set_user('Administrator')
        frappe.flags.mute_emails = True
        frappe.conf.relay_automation_enabled = 1
    connect()
    for name in ('relay_ticket', 'relay_automation_run'):
        frappe.reload_doc('relay_core', 'doctype', name, force=True)
    frappe.db.commit()
    print('RELOADED Relay Ticket, Relay Automation Run from worktree JSON')
    created = []
    original_insert = BaseDocument.db_insert
    def tracked(doc, *args, **kwargs):
        result = original_insert(doc, *args, **kwargs)
        created.append((doc.doctype, doc.name))
        return result
    stamp = run_label()
    def raw(doctype, label, **fields):
        doc = frappe.get_doc(dict(doctype=doctype, name='Sim '+label+' '+stamp, **fields))
        doc.db_insert()
        return doc
    with ExitStack() as stack:
        stack.enter_context(patch.object(BaseDocument, 'db_insert', tracked))
        stack.enter_context(patch.object(frappe, 'enqueue'))
        stack.enter_context(patch.object(frappe, 'publish_realtime'))
        stack.enter_context(patch('relay_core.automation.queue.wake'))
        stack.enter_context(patch('relay_core.messaging.connection_value', return_value='Sim Takeover '+stamp))
        stack.enter_context(patch('relay_core.whatsapp.client', side_effect=AssertionError('External delivery forbidden')))
        stack.enter_context(patch('frappe.core.doctype.user.user.throttle_user_creation'))
        # No outbound email, including fixture provisioning notifications.
        stack.enter_context(patch.object(frappe, 'sendmail'))
        try:
            company = raw('Company', 'Takeover Company', company_name='Sim Takeover Company '+stamp,
                          abbr='SM', country='India', default_currency='INR')
            actor = frappe.get_doc(dict(doctype='User', email='sim-takeover-'+stamp.lower()+'@example.invalid',
                first_name='Sim Takeover Operator '+stamp, send_welcome_email=0,
                roles=[{'role':r} for r in ('Relay Communication Manager','Relay Communication User',
                                          'Accounts Manager','Purchase Manager','Sales Manager')])).insert()
            actor.api_key, actor.api_secret = secrets.token_hex(12), secrets.token_hex(24)
            auth = 'token '+actor.api_key+':'+actor.api_secret
            actor.save()
            endpoint = phone(stamp)
            supplier = raw('Supplier', 'Takeover Supplier', supplier_name='Sim Takeover Supplier '+stamp,
                           supplier_type='Company', alias=endpoint)
            person = frappe.get_doc(dict(doctype='Contact', first_name='Sim Takeover Person '+stamp,
                links=[dict(link_doctype='Supplier',link_name=supplier.name)])).insert()
            contact = frappe.get_doc(dict(doctype='Relay Contact',contact=person.name,
                                         display_name='Sim Takeover Contact '+stamp)).insert()
            channel = frappe.get_doc(dict(doctype='Relay Channel',channel='WhatsApp',account='Sim Takeover '+stamp,
                company=company.name,triage_owner=actor.name,enabled=1)).insert(set_name=sequential_name('channel'))
            frappe.get_doc(dict(doctype='Relay Contact Endpoint',channel=channel.name,endpoint=endpoint,
                               relay_contact=contact.name,verified=1)).insert()
            contract = dict(name='supplier_ledger', method='get_list', doctype='GL Entry', scope_field='party',
                fields=['name','company','posting_date','debit','credit'], identity_anchor='Supplier',
                identity_fields={'WhatsApp':'alias'}, company_field='company')
            raw('GL Entry','Takeover Debit',company=company.name,party_type='Supplier',party=supplier.name,
                posting_date='2026-10-01',debit=1250,credit=0,is_cancelled=0)
            raw('GL Entry','Takeover Credit',company=company.name,party_type='Supplier',party=supplier.name,
                posting_date='2026-10-02',debit=0,credit=250,is_cancelled=0)
            event = raw('Relay AI Skill','Takeover Ledger',title='Sim Takeover Ledger '+stamp,enabled=1,
                channel=channel.name,business_doctype='Supplier',run_as_user=actor.name,handoff_owner=actor.name,
                mode='Automatic',daily_limit=100,target='Explain supplier ledger',instructions='Use my ledger only',
                execution_policy='Execute',allowed_tools=json.dumps([contract]),allowed_actions='[]')
            ticket_event = raw('Relay AI Skill','Takeover Support',title='Sim Takeover Support '+stamp,enabled=1,
                channel=channel.name,business_doctype='Supplier',run_as_user=actor.name,handoff_owner=actor.name,
                mode='Automatic',daily_limit=100,target='Open support ticket',instructions='Ticket only',
                execution_policy='Ticket only',exact_trigger='/support',allowed_tools='[]',allowed_actions='[]')
            frappe.db.commit()
            client = Client(frappe.app.application, Response)
            def request(method, data=None, authenticated=True, verb='POST'):
                frappe.db.commit(); frappe.destroy()
                response = client.open('/api/method/relay_core.'+method, method=verb, **({'json':data} if verb=='POST' else {'data':data}),
                    headers={'Authorization':auth} if authenticated else {}, base_url='http://yrp.site')
                connect()
                return response
            def source(text, *, business=None):
                provenance = dict(provider='WhatsApp',participant_id=endpoint,message_id='sim-'+str(frappe.db.count('Relay Message',{'channel':channel.name})))
                doc = frappe.get_doc(dict(doctype='Relay Message',relay_contact=contact.name,channel=channel.name,
                    sender_endpoint=endpoint,direction='Incoming',message_type='text',content=text,status='Sent',
                    business_doctype='Supplier',business_name=business or supplier.name,provider_context=json.dumps(provenance),
                    conversation_key=conversation_key(channel.name,endpoint,provenance))).insert()
                frappe.db.commit()
                return doc
            from relay_core import tickets, messaging
            from concurrent.futures import ThreadPoolExecutor
            def admit(text, **kwargs):
                doc = source(text, **kwargs)
                response = request('automation.service.enqueue', {'message': doc.name})
                assert response.status_code == 200, ('admit', response.status_code)
                return doc, frappe.get_doc('Relay Automation Run', response.json['message']['name'])
            def ownership(method, ticket, **kwargs):
                response = request('tickets.'+method, {'name': ticket}, **kwargs)
                assert response.status_code == 200, (method, response.status_code, response.json.get('exc_type'))
                result = response.json['message']
                assert set(result) == {'name', 'ai_disabled', 'generation'}
                return result
            doc, run = admit('Explain my supplier ledger amount 1250')
            ticket = frappe.get_doc('Relay Ticket', run.ticket)
            assert not ticket.ai_disabled and ticket.generation == run.ownership_generation == 0
            # Assignment is administrative routing; it must not take over.
            response = request('tickets.assign', {'name': ticket.name, 'user': actor.name})
            assert response.status_code == 200 and not response.json['message']['ai_disabled']
            for method in ('claim', 'resume_ai', 'close_and_release'):
                response = request('tickets.'+method, {'name': ticket.name}, authenticated=False)
                assert response.status_code in (401,403) and response.json['exc_type'] == 'PermissionError'
                response = request('tickets.'+method, {'name': ticket.name}, verb='GET')
                assert response.status_code == 403
            result = ownership('claim', ticket.name)
            assert result['ai_disabled'] and result['generation'] == 1
            assert ownership('claim', ticket.name) == result
            ticket.reload()
            assert ticket.ownership_actor == actor.name and ticket.ownership_at and not ticket.pending_run
            assert not frappe.db.get_value('Relay Contact', contact.name, 'automation_paused')
            with patch.object(adapter, 'match') as model, patch.object(adapter, 'complete') as complete:
                service.process(run.name)
                run.reload(); assert run.status == 'Cancelled'
                _, held = admit('More ledger help')
                assert held.status == 'Cancelled' and held.ticket == ticket.name
                model.assert_not_called(); complete.assert_not_called()
            resumed = ownership('resume_ai', ticket.name)
            assert resumed == dict(name=ticket.name, ai_disabled=False, generation=2)
            try: tickets.check_episode(run)
            except ValueError: pass
            else: raise AssertionError('Resume revived an old run')
            _, fresh = admit('/support')
            assert fresh.ownership_generation == 2
            service.process(fresh.name); fresh.reload()
            assert fresh.status == 'Completed' and fresh.ticket == ticket.name
            print('PASS HTTP claim/deny/shape/idempotency, assignment, human hold, resume fences old runs')

            # Two staff claims serialize and increment the episode exactly once.
            def competing_claim(_):
                connect(); frappe.set_user(actor.name)
                try:
                    result = tickets.claim(ticket.name); frappe.db.commit(); return result
                finally: frappe.destroy()
            frappe.db.commit()
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(competing_claim, range(8)))
            frappe.db.rollback(); ticket.reload()
            assert {r['generation'] for r in results} == {3} and ticket.ai_disabled
            ownership('resume_ai', ticket.name)
            print('PASS eight concurrent claims produce one ownership transition')

            # Same authenticated sender, distinct business: no contact-wide hold.
            other = raw('Supplier', 'Takeover Other Supplier', supplier_name='Sim Takeover Other Supplier '+stamp,
                        supplier_type='Company')
            person.append('links', dict(link_doctype='Supplier', link_name=other.name)); person.save()
            _, isolated = admit('/support', business=other.name)
            assert isolated.ticket != ticket.name
            ownership('claim', ticket.name)
            service.process(isolated.name); isolated.reload()
            assert isolated.status == 'Completed'
            assert not frappe.db.get_value('Relay Ticket', isolated.ticket, 'ai_disabled')
            # Company restriction makes even a manager unable to claim or resume.
            other_company = raw('Company', 'Takeover Other Company', company_name='Sim Takeover Other Company '+stamp,
                                abbr='SO', country='India', default_currency='INR')
            permission = frappe.get_doc(dict(doctype='User Permission', user=actor.name, allow='Company',
                                       for_value=other_company.name, apply_to_all_doctypes=1)).insert()
            frappe.clear_cache(user=actor.name)
            for method in ('claim', 'resume_ai', 'update_status'):
                response = request('tickets.'+method, dict(name=ticket.name, **({'status':'Closed'} if method=='update_status' else {})))
                assert response.status_code == 403 and response.json['exc_type'] == 'PermissionError', (method, response.status_code)
            frappe.delete_doc('User Permission', permission.name)
            frappe.clear_cache(user=actor.name)
            ownership('resume_ai', ticket.name)
            print('PASS business isolation and real company permission denial')

            # First manual chat reply holds the episode in its journal transaction.
            # Verify before the external boundary, which is mocked and never dispatched.
            original_save = messaging.internal_save
            def journal(doc, **kwargs):
                if doc.doctype == 'Relay Message Action':
                    assert frappe.db.get_value('Relay Ticket', ticket.name, 'ai_disabled')
                return original_save(doc, **kwargs)
            with patch.object(messaging, 'require_reply_window'), patch.object(messaging, 'internal_save', side_effect=journal), \
                    patch('relay_core.whatsapp.client', return_value=SimpleNamespace(call_tool=lambda *a, **k: {'messages':[{'id':'sim-staff-'+stamp}]})):
                response = request('messaging.send', dict(message=doc.name, kind='text',
                    data=json.dumps({'text':'Staff reviewing amount 1250'}), request_key='sim-staff-'+stamp))
                assert response.status_code == 200 and response.json['message']['status'] == 'Submitted', response.status_code
            ticket.reload()
            assert ticket.ai_disabled and ticket.ownership_actor == actor.name
            actions = frappe.get_all('Relay Message Action', filters={'source_message':doc.name}, pluck='name')
            assert len(actions) == 1
            response = request('messaging.send', dict(message=doc.name,kind='text',data='{}',request_key='sim-denied'), authenticated=False)
            assert response.status_code in (401,403)
            ownership('resume_ai', ticket.name)
            # A manual send before the drain has admitted the source still creates a hold.
            early_business=raw('Supplier','Takeover Early Supplier',supplier_name='Sim Takeover Early Supplier '+stamp,supplier_type='Company')
            person.reload(); person.append('links',dict(link_doctype='Supplier',link_name=early_business.name));person.save()
            early = source('Manual reply before admission', business=early_business.name)
            with patch.object(messaging, 'require_reply_window'), \
                    patch.object(messaging, 'record_submission_error', return_value={'status':'Uncertain'}):
                response=request('messaging.send',dict(message=early.name,kind='text',
                    data=json.dumps({'text':'Staff will check'}),request_key='sim-early-'+stamp))
                assert response.status_code==200
            early.reload()
            assert early.ticket and frappe.db.get_value('Relay Ticket',early.ticket,'ai_disabled')
            late_admission=request('automation.service.enqueue',{'message':early.name})
            assert late_admission.status_code==200 and late_admission.json['message']['status']=='Cancelled'
            print('PASS manual chat holds before journal commit; denied send cannot take over')

            # In-flight classifier result is fenced after the staff claim commits.
            racing_doc, racing = admit('Explain my ledger while staff claim')
            def delayed(model, targets, text, run_id, deadline, **kwargs):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(competing_claim, None).result(timeout=20)
                return {'human_request':False,'scores':[{'id':t['id'],'score':.95 if t['id']==event.name else .1} for t in targets]}
            with patch.object(adapter,'match',side_effect=delayed) as model, patch.object(adapter,'complete') as complete:
                service.process(racing.name); racing.reload()
                assert model.call_count == 1 and racing.status == 'Cancelled', (model.call_count,racing.status,racing.reason)
                complete.assert_not_called()
            ownership('resume_ai', ticket.name)
            # Ownership is checked between image observation and response inference.
            from relay_core.automation import multimodal
            model=raw('AI Model','Takeover Vision',model_id='sim-vision',enabled=1,supports_vision=1)
            frappe.db.set_value('Relay AI Skill',event.name,dict(ai_model=model.name,exact_trigger='/evidence',allowed_actions='[{"action":"reply"}]'))
            photo=source('/evidence')
            frappe.db.set_value('Relay Message',photo.name,'message_type','image')
            response=request('automation.service.enqueue',{'message':photo.name})
            assert response.status_code==200
            image_run=response.json['message']['name']
            def observed(*args,**kwargs):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(competing_claim,None).result(timeout=20)
                return 'Payment screenshot shows INR 1250'
            with patch.object(multimodal,'context',return_value=('Payment INR 1250',[{'data':b'sim-image','mime':'image/png'}])), \
                    patch.object(adapter,'observe_image',side_effect=observed) as vision, patch.object(adapter,'complete') as complete:
                service.process(image_run)
                observed_run=frappe.get_doc('Relay Automation Run',image_run)
                assert observed_run.status=='Cancelled', (observed_run.status,observed_run.reason)
                vision.assert_called_once();complete.assert_not_called()
            ownership('resume_ai',ticket.name)
            print('PASS committed takeover during image observation prevents subsequent model call')
            # Start work and resolution use the ticket controller ownership transition.
            response=request('tickets.update_status',{'name':ticket.name,'status':'In progress'})
            assert response.status_code==200 and response.json['message']==dict(name=ticket.name,status='In progress')
            ticket.reload(); assert ticket.ai_disabled
            response=request('tickets.update_status',{'name':ticket.name,'status':'Resolved'})
            assert response.status_code==200
            ticket.reload(); assert ticket.ai_disabled and ticket.active_scope_key
            response=request('tickets.resume_ai',{'name':ticket.name})
            assert response.status_code==417 and response.json['exc_type']=='ValidationError'
            replay = tickets.ensure_episode(frappe.get_doc('Relay Message',doc.name),owner=actor.name)
            assert replay.name==ticket.name and replay.status=='Resolved'
            _, held_closed=admit('/support')
            assert held_closed.ticket==ticket.name and held_closed.status=='Cancelled'
            ticket.reload(); assert ticket.status=='Open' and ticket.ai_disabled
            response=request('tickets.close_and_release',{'name':ticket.name})
            assert response.status_code==200 and response.json['message']['status']=='Closed'
            assert set(response.json['message'])=={'name','status','ai_disabled','generation'}
            ticket.reload(); assert not ticket.active_scope_key and ticket.ai_disabled
            assert request('tickets.close_and_release',{'name':ticket.name},authenticated=False).status_code in (401,403)
            _, released=admit('/support')
            assert released.ticket!=ticket.name and released.ownership_generation==0
            service.process(released.name); released.reload(); assert released.status=='Completed'
            print('PASS in-flight classifier cancellation, start work, closure retains hold; explicit release allows fresh-message execution')

            # A journal failure rolls the ownership change back with it.
            before = frappe.db.get_value('Relay Ticket', released.ticket, 'generation')
            original_save = messaging.internal_save
            def fail_journal(doc, **kwargs):
                if doc.doctype == 'Relay Message Action':
                    raise frappe.ValidationError('Sim journal failure')
                return original_save(doc, **kwargs)
            with patch.object(messaging,'require_reply_window'), patch.object(messaging,'internal_save',side_effect=fail_journal):
                response=request('messaging.send',dict(message=released.message,kind='text',
                    data=json.dumps({'text':'Staff reply'}),request_key='sim-failed-'+stamp))
                assert response.status_code==417
            state=frappe.get_doc('Relay Ticket',released.ticket)
            assert not state.ai_disabled and state.generation==before
            print('PASS failed manual journal rolls back the ownership transition')

            # Existing explicit flows keep their contact fence and gain the episode fence.
            from relay_core.flows import service as flows
            flow=raw('Relay Flow','Takeover Flow',title='Sim Takeover Flow '+stamp,enabled=1,
                channel=channel.name,business_doctype='Supplier',execution_user=actor.name,command='/staff_flow',
                trigger_key=flows.digest(channel.name,'/staff_flow'))
            nodes=json.dumps([dict(id='wait',kind='wait',seconds=60,text=''),
                              dict(id='reply',kind='reply',text='Automatic followup'),dict(id='end',kind='end',text='')])
            version=raw('Relay Flow Version','Takeover Version',flow=flow.name,nodes=nodes,
                channel=channel.name,business_doctype='Supplier',execution_user=actor.name,definition_hash='sim')
            frappe.db.set_value('Relay Flow',flow.name,'published_version',version.name)
            flow_doc, flow_admission=admit('/staff_flow')
            flow_event=frappe.db.get_value('Relay Flow Event',{'message':flow_doc.name},'name')
            assert flow_admission.stage=='Flow' and flow_event
            with patch.object(flows,'send') as sends:
                flows.process(flow_event)
                row=frappe.get_doc('Relay Flow Event',flow_event)
                assert row.status=='Pending' and row.run
                ownership('claim',flow_admission.ticket)
                ownership('resume_ai',flow_admission.ticket)
                frappe.db.set_value('Relay Flow Event',row.name,'next_attempt',None);frappe.db.commit()
                flows.process(flow_event)
                row.reload()
                assert row.status=='Rejected' and frappe.db.get_value('Relay Flow Run',row.run,'status')=='Cancelled'
                sends.assert_not_called()
            print('PASS waiting flow stays fenced after claim and resume')

            # Email uses its existing journal; takeover is in that same transaction.
            from relay_core import email
            email_channel=frappe.get_doc(dict(doctype='Relay Channel',channel='Email',account=channel.account,
                company=company.name,triage_owner=actor.name,enabled=1)).insert(set_name=sequential_name('channel'))
            address='sim-takeover-'+stamp.lower()+'@example.invalid'
            frappe.get_doc(dict(doctype='Relay Contact Endpoint',channel=email_channel.name,endpoint=address,
                               relay_contact=contact.name,verified=1)).insert()
            context=dict(provider='Email',message_id='<sim-source-'+stamp+'@example.invalid>',
                         email_thread_id='<sim-thread-'+stamp+'@example.invalid>',authentication={'status':'pass'})
            email_source=frappe.get_doc(dict(doctype='Relay Message',relay_contact=contact.name,channel=email_channel.name,
                sender_endpoint=address,direction='Incoming',message_type='text',content='Amount 1250',status='Sent',
                business_doctype='Supplier',business_name=supplier.name,provider_context=json.dumps(context),
                conversation_key=conversation_key(email_channel.name,address,context))).insert()
            email_ticket=tickets.ensure_episode(email_source,owner=actor.name);frappe.db.commit()
            def email_submit(action):
                assert action.operation=='email' and action.source_message==email_source.name
                assert frappe.db.get_value('Relay Ticket',email_ticket.name,'ai_disabled')
                return dict(action=action.name,status='Uncertain',message=None)
            with patch.object(email,'connection_value',return_value=channel.account), patch.object(email,'submit',side_effect=email_submit):
                payload=dict(to=[address],subject='Staff review',body='We will check amount 1250',
                             message=email_source.name,request_key='sim-email-'+stamp)
                response=request('email.send',payload)
                assert response.status_code==200, ('email',response.status_code,response.json.get('exc_type'))
                assert set(response.json['message'])=={'action','status','message'}
                email_ticket.reload();assert email_ticket.ai_disabled and email_ticket.ownership_actor==actor.name
                response=request('email.send',payload,authenticated=False)
                assert response.status_code in (401,403)
            print('PASS manual email takeover through HTTP journal and guest denial')

            for method in ('hold_episode','manual_takeover','check_episode','_ownership'):
                response=request('tickets.'+method)
                assert response.status_code==403, (method,response.status_code)
            assert request('ai.matching.human_request').status_code==403
            assert request('ai.service.check_continuation').status_code==403
            print('PASS internal transition HTTP denial')
        finally:
            connect(); frappe.db.rollback()
            for doctype,name in reversed(created):
                frappe.db.delete('__Auth', {'doctype':doctype, 'name':name})
                frappe.db.delete(doctype, {'name':name})
            frappe.db.commit()
            assert all(not frappe.db.exists(dt,name) for dt,name in created)
            frappe.destroy()
            print('CLEANUP all created fixtures deleted, including Companies and ledger entries')


if __name__=='__main__':
    main()
