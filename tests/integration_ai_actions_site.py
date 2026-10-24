"""Step 7 typed execution and approvals through real yrp.site HTTP and worker paths.

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

from integration_ai_permissions_site import confine_writes
from site_labels import run_label, phone

SITES = '/home/sakthi/development/pilot/benches/version_16/sites'
ROOT = Path(__file__).resolve().parents[1]


def main(exercise=None):
    sys.addaudithook(confine_writes)
    os.environ.update(FRAPPE_STREAM_LOGGING='1', SITES_PATH=SITES)
    import frappe
    import frappe.app
    import relay_core
    from frappe.model.base_document import BaseDocument
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    from relay_core.ai import service as ai
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
    frappe.reload_doc('relay_core', 'doctype', 'relay_flow_action', force=True)
    frappe.db.commit()
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
        stack.enter_context(patch('relay_core.messaging.connection_value', return_value='Sim Action '+stamp))
        stack.enter_context(patch('relay_core.whatsapp.client', side_effect=AssertionError('External delivery forbidden')))
        stack.enter_context(patch('frappe.core.doctype.user.user.throttle_user_creation'))
        # No outbound email, including fixture provisioning notifications.
        stack.enter_context(patch.object(frappe, 'sendmail'))
        try:
            company = raw('Company', 'Action Company', company_name='Sim Action Company '+stamp,
                          abbr='SM', country='India', default_currency='INR')
            actor = frappe.get_doc(dict(doctype='User', email='sim-action-'+stamp.lower()+'@example.invalid',
                first_name='Sim Action Operator '+stamp, send_welcome_email=0,
                roles=[{'role':r} for r in ('Relay Communication Manager','Relay Communication User',
                                          'Accounts Manager','Purchase Manager','Sales Manager')])).insert()
            actor.api_key, actor.api_secret = secrets.token_hex(12), secrets.token_hex(24)
            auth = 'token '+actor.api_key+':'+actor.api_secret
            actor.save()
            endpoint = phone(stamp)
            supplier = raw('Supplier', 'Action Supplier', supplier_name='Sim Action Supplier '+stamp,
                           supplier_type='Company', alias=endpoint)
            person = frappe.get_doc(dict(doctype='Contact', first_name='Sim Action Person '+stamp,
                links=[dict(link_doctype='Supplier',link_name=supplier.name)])).insert()
            contact = frappe.get_doc(dict(doctype='Relay Contact',contact=person.name,
                                         display_name='Sim Action Contact '+stamp)).insert()
            channel = frappe.get_doc(dict(doctype='Relay Channel',channel='WhatsApp',account='Sim Action '+stamp,
                company=company.name,triage_owner=actor.name,enabled=1)).insert(set_name=sequential_name('channel'))
            frappe.get_doc(dict(doctype='Relay Contact Endpoint',channel=channel.name,endpoint=endpoint,
                               relay_contact=contact.name,verified=1)).insert()
            contract = dict(name='supplier_ledger', method='get_list', doctype='GL Entry', scope_field='party',
                fields=['name','company','posting_date','debit','credit'], identity_anchor='Supplier',
                identity_fields={'WhatsApp':'alias'}, company_field='company')
            raw('GL Entry','Action Debit',company=company.name,party_type='Supplier',party=supplier.name,
                posting_date='2026-10-01',debit=1250,credit=0,is_cancelled=0)
            raw('GL Entry','Action Credit',company=company.name,party_type='Supplier',party=supplier.name,
                posting_date='2026-10-02',debit=0,credit=250,is_cancelled=0)
            event = raw('Relay AI Skill','Action Ledger',title='Sim Action Ledger '+stamp,enabled=1,
                channel=channel.name,business_doctype='Supplier',run_as_user=actor.name,handoff_owner=actor.name,
                mode='Automatic',daily_limit=100,search_confirmation='When required',target='Explain supplier ledger',instructions='Use my ledger only',
                execution_policy='Execute',allowed_tools=json.dumps([contract]),allowed_actions='[]')
            frappe.db.commit()
            client = Client(frappe.app.application, Response)
            def request(method, data=None, authenticated=True, verb='POST'):
                frappe.db.commit(); frappe.destroy()
                response = client.open('/api/method/relay_core.'+method, method=verb, data=data,
                    headers={'Authorization':auth} if authenticated else {}, base_url='http://yrp.site')
                connect()
                return response
            def source(text):
                provenance = dict(provider='WhatsApp',participant_id=endpoint,message_id='sim-source-'+str(len(created)))
                doc = frappe.get_doc(dict(doctype='Relay Message',relay_contact=contact.name,channel=channel.name,
                    sender_endpoint=endpoint,direction='Incoming',message_type='text',content=text,status='Sent',
                    business_doctype='Supplier',business_name=supplier.name,provider_context=json.dumps(provenance),
                    conversation_key=conversation_key(channel.name,endpoint,provenance))).insert()
                frappe.db.commit()
                return doc
            if exercise:
                exercise(stack=stack, raw=raw, actor=actor, company=company, supplier=supplier,
                    contact=contact, event=event, source=source, request=request, stamp=stamp)
                return
            from relay_core.flows import actions
            from relay_core.ai.tools import as_user, fingerprint
            from relay_core.tickets import ensure_episode
            from test_ai_actions import definition
            registered = definition()
            actual_get_attr = frappe.get_attr
            calls = []
            failure = None
            def handler(action_input, idempotency_key, **kwargs):
                scope = kwargs.get('execution_context') or dict(company=company.name,
                    business=[kwargs['business_doctype'],kwargs['business_name']])
                calls.append(idempotency_key)
                draft = raw('Payment Entry', 'Action Draft '+str(len(calls)),
                    payment_type='Pay', paid_amount=action_input['paid_amount'], received_amount=action_input['paid_amount'],
                    company=scope['company'], party_type=scope['business'][0], party=scope['business'][1], docstatus=0)
                if failure == 'exit': raise SystemExit('Sim worker exit')
                if failure == 'commit': frappe.db.commit()
                if failure == 'submitted': frappe.db.set_value('Payment Entry', draft.name, 'docstatus', 1)
                return {'doctype':draft.doctype, 'name':draft.name}
            def get_attr(method):
                return handler if method == registered['method'] else actual_get_attr(method)
            stack.enter_context(patch.object(actions, 'definitions', return_value={'draft_payment':registered}))
            stack.enter_context(patch.object(frappe, 'get_attr', side_effect=get_attr))
            event.allowed_actions=json.dumps([dict(action='draft_payment',doctype='Payment Entry',fields=['paid_amount'])])
            frappe.db.set_value('Relay AI Skill', event.name, 'allowed_actions', event.allowed_actions)
            event.reload()
            def new_run(label, amount=1250, steps=1):
                doc=source(label)
                ticket=ensure_episode(doc,owner=actor.name,skill=event)
                doc.reload()
                with as_user(actor.name):
                    user,business,scope=ai.context(event,doc)
                plan=dict(reply='',handoff=False,reason='',user=user,scope=fingerprint(scope),reads=[],
                    actions=[dict(action='draft_payment',parameters={'paid_amount':amount}) for _ in range(steps)])
                run=raw('Relay Automation Run','Action Run '+label,event_key='sim-action-'+label+'-'+stamp,
                    message=doc.name,execution_user=user,status='Deciding',skill=event.name,skill_version=str(event.modified),
                    generation=0,ticket=ticket.name,message_hash=service.message_hash(doc),scope_fingerprint=fingerprint(scope),
                    decision=json.dumps(plan),stage='Event')
                frappe.db.commit()
                return run,ticket
            def execute(run,step=0):
                result=actions.execute_ai(run.name,step)
                frappe.db.commit()
                return result
            def approval(result, **overrides):
                journal=frappe.get_doc('Relay Flow Action',result['name'])
                values=dict(name=journal.name,input_hash=journal.input_hash,scope_fingerprint=journal.scope_fingerprint)
                values.update(overrides)
                return request('flows.actions.approve',values)
            def denied(call):
                try: call()
                except (ValueError,frappe.PermissionError): frappe.db.rollback()
                else: raise AssertionError('Expected denial')

            run,ticket=new_run('Approval')
            pending=execute(run)
            assert pending['status']=='Awaiting approval' and not calls
            response=approval(pending,input_hash='changed')
            assert response.status_code==417 and response.json['exc_type']=='ValidationError', (response.status_code,response.json.get('exc_type'))
            response=approval(pending)
            assert response.status_code==200 and response.json['message']==dict(name=pending['name'],status='Approved')
            assert not calls, 'Approval must not execute or send'
            result=execute(run)
            assert result['status']=='Completed' and len(calls)==1
            draft=frappe.get_doc('Payment Entry',result['result']['name'])
            journal=frappe.get_doc('Relay Flow Action',result['name'])
            assert draft.docstatus==0 and draft.paid_amount==1250 and journal.ticket==ticket.name
            assert journal.target_name==draft.name and journal.target_doctype=='Payment Entry'
            assert json.loads(journal.input_snapshot)=={'paid_amount':1250}
            assert json.loads(journal.approval_evidence)['actor']==actor.name
            assert execute(run)==result and len(calls)==1
            print('PASS real 1250 draft, episode reference, approval HTTP status/shape, duplicate replay')

            run,ticket=new_run('Stale')
            pending=execute(run)
            frappe.db.set_value('Supplier',supplier.name,'supplier_name','Sim Changed Supplier '+stamp)
            frappe.db.commit()
            response=approval(pending)
            assert response.status_code==417 and response.json['exc_type']=='ValidationError'
            denied(lambda: execute(run))
            print('PASS changed business version invalidates pending approval')

            run,ticket=new_run('Takeover')
            pending=execute(run)
            assert approval(pending).status_code==200
            frappe.db.set_value('Relay Ticket',ticket.name,{'ai_disabled':1,'generation':1});frappe.db.commit()
            denied(lambda: execute(run))
            frappe.db.set_value('Relay Ticket',ticket.name,{'ai_disabled':0,'generation':2});frappe.db.commit()
            denied(lambda: execute(run))
            print('PASS staff hold and changed ownership generation reject approved execution')

            registered['approval_policy']='None'
            run,ticket=new_run('Recovery')
            failure='exit'
            try: execute(run)
            except SystemExit: pass
            else: raise AssertionError('Worker did not exit')
            frappe.db.rollback()
            assert not frappe.db.exists('Payment Entry',{'name':'Sim Action Draft '+str(len(calls))+' '+stamp})
            failure=None
            result=execute(run)
            assert len(calls)==3 and calls[-1]==calls[-2]
            assert execute(run)==result and len(calls)==3
            print('PASS crash rollback and retry use the same command key with one local draft')

            for fault in ('commit','submitted'):
                run,ticket=new_run(fault)
                failure=fault
                denied(lambda:execute(run))
                assert not frappe.db.exists('Payment Entry',{'name':'Sim Action Draft '+str(len(calls))+' '+stamp})
            failure=None
            print('PASS independent commit and submitted result roll back local writes')

            run,ticket=new_run('Order',steps=2)
            denied(lambda: execute(run,1))
            denied(lambda: execute(run,0))
            run,ticket=new_run('Immutable')
            execute(run,0)
            plan=json.loads(run.decision);plan['actions'][0]['parameters']['paid_amount']=2000
            frappe.db.set_value('Relay Automation Run',run.name,'decision',json.dumps(plan));frappe.db.commit()
            denied(lambda:execute(run))
            print('PASS ordered steps and immutable input under the same command key')

            for amount in ('1250',True,-1):
                run,ticket=new_run('Wrong type '+str(amount),amount)
                denied(lambda:execute(run))
            run,ticket=new_run('Identity')
            frappe.db.set_value('Supplier',supplier.name,'alias','not-the-sender');frappe.db.commit()
            denied(lambda:execute(run))
            frappe.db.set_value('Supplier',supplier.name,'alias',endpoint);frappe.db.commit()
            print('PASS wrong types and revoked sender identity fail before mutation')

            run,ticket=new_run('Permissions')
            registered['permissions']['User']='create'
            denied(lambda:execute(run))
            del registered['permissions']['User']
            event.allowed_actions=json.dumps([dict(action='draft_payment',doctype='User',fields=['paid_amount'])])
            frappe.db.set_value('Relay AI Skill',event.name,'allowed_actions',event.allowed_actions,update_modified=False)
            frappe.db.commit()
            denied(lambda:execute(run))
            event.allowed_actions=json.dumps([dict(action='draft_payment',doctype='Payment Entry',fields=['paid_amount'])])
            frappe.db.set_value('Relay AI Skill',event.name,'allowed_actions',event.allowed_actions,update_modified=False)
            frappe.db.commit()
            print('PASS real execution-user permission denial and unauthorized target rejection')

            from concurrent.futures import ThreadPoolExecutor
            from threading import Barrier
            run,ticket=new_run('Concurrent')
            barrier=Barrier(2)
            before=len(calls)
            def concurrent_execute():
                connect()
                try:
                    barrier.wait(timeout=10)
                    return execute(run)
                finally:
                    frappe.db.rollback();frappe.destroy()
            with ThreadPoolExecutor(max_workers=2) as pool:
                first=pool.submit(concurrent_execute);second=pool.submit(concurrent_execute)
                left,right=first.result(timeout=30),second.result(timeout=30)
            assert left==right and len(calls)==before+1
            print('PASS concurrent duplicate execution creates one local draft')

            # The normal worker consumes the stored decision; pending approvals send nothing.
            registered['approval_policy']='Required'
            run,ticket=new_run('Worker')
            with patch.object(ai,'send_reply',return_value={'status':'Submitted'}) as send:
                service.process(run.name)
                run.reload()
                assert run.status=='Deciding' and not send.called
                journal=frappe.get_doc('Relay Flow Action',{'automation_run':run.name})
                assert approval({'name':journal.name}).status_code==200
                service.process(run.name)
                run.reload()
                assert run.status=='Completed' and send.call_count==0, (run.status,run.reason)
                service.process(run.name)
                assert send.call_count==0
            print('PASS draft-only worker waits for approval, executes without an undeclared reply, and does not replay')

            response=request('flows.actions.catalog',verb='GET')
            assert response.status_code==200 and isinstance(response.json['message'],list)
            assert set(response.json['message'][0])=={'key','label','description','parameters'}
            response=request('flows.actions.catalog',authenticated=False,verb='GET')
            assert response.status_code in (401,403) and response.json['exc_type']=='PermissionError'
            for method in ('flows.actions.proposal','flows.actions.execute','flows.actions.execute_ai',
                           'flows.actions._ai_context','flows.actions._journal','flows.actions._perform',
                           'flows.action_contracts.ai_inputs','flows.action_contracts.ai_contract'):
                response=request(method)
                assert response.status_code==403 and response.json['exc_type']=='PermissionError', (method,response.status_code)
            response=request('flows.actions.approve',{'name':result['name']},authenticated=False)
            assert response.status_code in (401,403) and response.json['exc_type']=='PermissionError'
            response=request('flows.actions.approve',verb='GET')
            assert response.status_code==403
            response=request('flows.actions.approve',{'name':result['name'],'input_hash':'x','scope_fingerprint':'x'})
            assert response.status_code==417 and response.json['exc_type']=='ValidationError'
            frappe.db.commit();frappe.destroy()
            response=client.get('/api/resource/Relay Flow Action/'+result['name'],headers={'Authorization':auth},base_url='http://yrp.site')
            connect()
            assert response.status_code==403 and response.json['exc_type']=='PermissionError'
            print('PASS HTTP catalog, internal helper denial, approval method/guest denial and private journal REST')

            flow=raw('Relay Flow Run','Action Flow',relay_contact=contact.name,business_doctype='Supplier',business_name=supplier.name)
            frappe.db.commit()
            with as_user(actor.name):
                flow_result=actions.execute(flow,dict(action='draft_payment',arguments={'paid_amount':1250}),{},'sim-flow-'+stamp)
            frappe.db.rollback()
            assert not frappe.db.exists('Payment Entry',flow_result['name'])
            with as_user(actor.name):
                flow_result=actions.execute(flow,dict(action='draft_payment',arguments={'paid_amount':1250}),{},'sim-flow-'+stamp)
            frappe.db.commit()
            before=len(calls)
            with as_user(actor.name):
                assert actions.execute(flow,dict(action='draft_payment',arguments={'paid_amount':1250}),{},'sim-flow-'+stamp)==flow_result
            assert len(calls)==before
            flow_journal=frappe.get_doc('Relay Flow Action',{'run':flow.name})
            assert flow_journal.status=='Completed' and not flow_journal.automation_run
            print('PASS legacy flow execution shares atomic journal and replay behavior')

        finally:
            connect(); frappe.db.rollback()
            for doctype,name in reversed(created):
                frappe.db.delete('__Auth', {'doctype':doctype, 'name':name})
                frappe.db.delete(doctype, {'name':name})
            frappe.db.commit()
            assert all(not frappe.db.exists(dt,name) for dt,name in created)
            frappe.destroy()
            print('CLEANUP all created fixtures deleted, including Companies and draft Payment Entries')


if __name__=='__main__':
    main()
