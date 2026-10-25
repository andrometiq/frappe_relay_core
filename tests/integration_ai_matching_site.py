"""Step 5 admission through real yrp.site HTTP, drain and worker paths.

External models, sends, queues and notifications are intercepted. Every inserted
fixture (including children and Companies) is removed in finally.
"""
import json
import os
from pathlib import Path
import secrets
import sys
import time
from contextlib import ExitStack
from unittest.mock import patch

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
    from relay_core.automation import service, queue
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
        stack.enter_context(patch('relay_core.messaging.connection_value', return_value='Sim Matching '+stamp))
        stack.enter_context(patch('relay_core.whatsapp.client', side_effect=AssertionError('External delivery forbidden')))
        stack.enter_context(patch('frappe.core.doctype.user.user.throttle_user_creation'))
        # No outbound email, including fixture provisioning notifications.
        stack.enter_context(patch.object(frappe, 'sendmail'))
        try:
            company = raw('Company', 'Matching Company', company_name='Sim Matching Company '+stamp,
                          abbr='SM', country='India', default_currency='INR')
            actor = frappe.get_doc(dict(doctype='User', email='sim-matching-'+stamp.lower()+'@example.invalid',
                first_name='Sim Matching Operator '+stamp, send_welcome_email=0,
                roles=[{'role':r} for r in ('Relay Communication Manager','Relay Communication User',
                                          'Accounts Manager','Purchase Manager','Sales Manager')])).insert()
            actor.api_key, actor.api_secret = secrets.token_hex(12), secrets.token_hex(24)
            auth = 'token '+actor.api_key+':'+actor.api_secret
            actor.save()
            endpoint = phone(stamp)
            supplier = raw('Supplier', 'Matching Supplier', supplier_name='Sim Matching Supplier '+stamp,
                           supplier_type='Company', alias=endpoint)
            person = frappe.get_doc(dict(doctype='Contact', first_name='Sim Matching Person '+stamp,
                links=[dict(link_doctype='Supplier',link_name=supplier.name)])).insert()
            contact = frappe.get_doc(dict(doctype='Relay Contact',contact=person.name,
                                         display_name='Sim Matching Contact '+stamp)).insert()
            channel = frappe.get_doc(dict(doctype='Relay Channel',channel='WhatsApp',account='Sim Matching '+stamp,
                company=company.name,triage_owner=actor.name,enabled=1)).insert(set_name=sequential_name('channel'))
            frappe.get_doc(dict(doctype='Relay Contact Endpoint',channel=channel.name,endpoint=endpoint,
                               relay_contact=contact.name,verified=1)).insert()
            contract = dict(name='supplier_ledger', method='get_list', doctype='GL Entry', scope_field='party',
                fields=['name','company','posting_date','debit','credit'], identity_anchor='Supplier',
                identity_fields={'WhatsApp':'alias'}, company_field='company')
            raw('GL Entry','Matching Debit',company=company.name,party_type='Supplier',party=supplier.name,
                posting_date='2026-10-01',debit=1250,credit=0,is_cancelled=0)
            raw('GL Entry','Matching Credit',company=company.name,party_type='Supplier',party=supplier.name,
                posting_date='2026-10-02',debit=0,credit=250,is_cancelled=0)
            event = raw('Relay AI Skill','Matching Ledger',title='Sim Matching Ledger '+stamp,enabled=1,
                channel=channel.name,business_doctype='Supplier',run_as_user=actor.name,handoff_owner=actor.name,
                mode='Automatic',daily_limit=100,target='Explain supplier ledger',instructions='Use my ledger only',
                execution_policy='Execute',allowed_tools=json.dumps([contract]),allowed_actions='[]')
            ticket_event = raw('Relay AI Skill','Matching Support',title='Sim Matching Support '+stamp,enabled=1,
                channel=channel.name,business_doctype='Supplier',run_as_user=actor.name,handoff_owner=actor.name,
                mode='Automatic',daily_limit=100,target='Open support ticket',instructions='Ticket only',
                execution_policy='Ticket only',exact_trigger='/support',allowed_tools='[]',allowed_actions='[]')
            frappe.db.commit()
            client = Client(frappe.app.application, Response)
            def request(method, data=None, authenticated=True, verb='POST'):
                frappe.db.commit(); frappe.destroy()
                response = client.open('/api/method/relay_core.'+method, method=verb, data=data,
                    headers={'Authorization':auth} if authenticated else {}, base_url='http://yrp.site')
                connect()
                return response
            def source(text):
                # Each failure case starts fresh work on the same episode. Triage
                # now holds that episode until an explicit staff resume.
                from relay_core.tickets import resume_ai
                for held in frappe.get_all('Relay Ticket', filters={'company': company.name,
                        'ai_disabled': 1, 'active_scope_key': ['is', 'set']}, pluck='name'):
                    resume_ai(held)
                frappe.db.commit()
                provenance = dict(provider='WhatsApp',participant_id=endpoint)
                doc = frappe.get_doc(dict(doctype='Relay Message',relay_contact=contact.name,channel=channel.name,
                    sender_endpoint=endpoint,direction='Incoming',message_type='text',content=text,status='Sent',
                    business_doctype='Supplier',business_name=supplier.name,provider_context=json.dumps(provenance),
                    conversation_key=conversation_key(channel.name,endpoint,provenance))).insert()
                frappe.db.commit()
                return doc
            def classified(model, targets, text, run_id, deadline, **kwargs):
                assert set(targets[0]) == {'id','target'} and deadline > time.monotonic()
                return {'human_request':False,'scores':[{'id':t['id'],'score':.95 if t['id']==event.name else .1}
                                                       for t in targets]}
            def answer(skill, user, business, text, run_id, *, scope, deadline=None):
                run = frappe.get_doc('Relay Automation Run',run_id)
                assert run.ticket and run.skill_version == str(skill.modified)
                # Admission declares the search; step 6 exercises confirmed reads
                # through the real journal in integration_ai_search_site.py.
                return dict(reply='Confirm your ledger search',handoff=False,reason='',user=user,reads=[],
                    search=dict(purpose='Review your ledger',reference=contract['name'],fields=contract['fields'],
                        arguments={'filters':{'posting_date':['between',['2026-10-01','2026-10-31']]}}))
            with patch.object(adapter,'match',autospec=True,side_effect=classified) as model, \
                    patch.object(adapter,'complete',side_effect=answer) as complete, \
                    patch.object(ai,'send_reply',return_value={'status':'Submitted'}) as send:
                doc=source('Explain my October ledger')
                denied=request('automation.service.enqueue',{'message':doc.name},authenticated=False)
                assert denied.status_code in (401,403) and denied.json['exc_type']=='PermissionError'
                response=request('automation.service.enqueue',{'message':doc.name})
                assert response.status_code==200, ('enqueue',response.status_code,response.json.get('exc_type'))
                wrong_method=request('automation.service.enqueue',{'message':doc.name},verb='GET')
                assert wrong_method.status_code==403
                value=response.json['message']; assert set(value)=={'name','status'} and value['status']=='Pending'
                run=frappe.get_doc('Relay Automation Run',value['name'])
                assert run.ticket and not run.skill and model.call_count==0
                assert frappe.db.get_value('Relay Message',doc.name,'ticket')==run.ticket
                service.process(run.name); run.reload()
                assert run.status=='Completed', ('worker',run.status,run.reason)
                assert run.skill==event.name and json.loads(run.match_result)['selected']==event.name
                ticket=frappe.get_doc('Relay Ticket',run.ticket)
                assert ticket.skill==event.name and ticket.skill_version==run.skill_version
                assert model.call_count==1 and complete.call_count==1 and send.call_count==1
                # Replaying either the HTTP endpoint or drain cannot create a second handler.
                replay=request('automation.service.enqueue',{'message':doc.name})
                assert replay.status_code==200 and replay.json['message']['name']==run.name
                queue._process(doc.name); frappe.db.commit(); service.process(run.name)
                assert send.call_count==1 and frappe.db.count('Relay Automation Run',{'message':doc.name})==1
                transcript=request('tickets.transcript',{'name':run.ticket},verb='GET')
                assert transcript.status_code==200 and set(transcript.json['message'])=={'items','next'}
                print('PASS HTTP admission/deny/replay, durable drain, worker and supplier ledger declaration before reads')

                doc=source('/support')
                queue._process(doc.name); frappe.db.commit()
                name=frappe.db.get_value('Relay Automation Run',{'message':doc.name},'name')
                service.process(name)
                exact=frappe.get_doc('Relay Automation Run',name)
                assert exact.status=='Completed' and exact.skill==ticket_event.name and exact.ticket==run.ticket
                assert model.call_count==1 and complete.call_count==1
                # Low confidence, malformed output and provider failure always keep the episode.
                for output in ({'human_request':False,'scores':[{'id':event.name,'score':.5},
                                    {'id':ticket_event.name,'score':.2}]}, {'selected':event.name}, TimeoutError()):
                    model.side_effect=output if isinstance(output,Exception) else None
                    model.return_value=output
                    doc=source('Unclear message amount 1250')
                    queue._process(doc.name); frappe.db.commit()
                    name=frappe.db.get_value('Relay Automation Run',{'message':doc.name},'name')
                    service.process(name)
                    failed=frappe.get_doc('Relay Automation Run',name)
                    assert failed.status=='Handoff' and failed.ticket==run.ticket and not failed.skill
                assert complete.call_count==1 and send.call_count==1
                print('PASS exact Ticket only, low confidence, malformed output and timeout triage without tools or sends')

                # Disable all events: a resolved source still receives assigned triage.
                for name in (event.name,ticket_event.name):
                    frappe.db.set_value('Relay AI Skill',name,'enabled',0)
                doc=source('No configured event')
                queue._process(doc.name); frappe.db.commit()
                name=frappe.db.get_value('Relay Automation Run',{'message':doc.name},'name')
                service.process(name)
                empty=frappe.get_doc('Relay Automation Run',name)
                assert empty.status=='Handoff' and json.loads(empty.match_result)['method']=='none'
                for name in (event.name,ticket_event.name):
                    frappe.db.set_value('Relay AI Skill',name,'enabled',1)
                # Shadow admission records a proposal without executing or delivering it.
                frappe.db.set_value('Relay AI Skill',event.name,'mode','Shadow')
                model.side_effect=classified
                doc=source('Explain ledger in shadow')
                queue._process(doc.name); frappe.db.commit()
                name=frappe.db.get_value('Relay Automation Run',{'message':doc.name},'name')
                service.process(name)
                shadow=frappe.get_doc('Relay Automation Run',name)
                assert shadow.status=='Shadow' and json.loads(shadow.decision)['search']
                assert shadow.search_plan and shadow.ticket
                assert complete.call_count==2 and send.call_count==1
                frappe.db.set_value('Relay AI Skill',event.name,'mode','Automatic')
                # A delayed model response cannot authorize a changed event or takeover.
                for change,status in (('version','Handoff'),('takeover','Cancelled'),('identity','Handoff')):
                    def delayed(*args, **kwargs):
                        result=classified(*args,**kwargs)
                        if change=='version':
                            frappe.db.set_value('Relay AI Skill',event.name,'target','Updated ledger target')
                        elif change=='takeover':
                            frappe.db.set_value('Relay Ticket',run.ticket,'ai_disabled',1)
                        else:
                            frappe.db.set_value('Relay Contact Endpoint',{'channel':channel.name,'endpoint':endpoint},'verified',0)
                        return result
                    model.side_effect=delayed
                    doc=source('Explain ledger while scope changes')
                    queue._process(doc.name); frappe.db.commit()
                    name=frappe.db.get_value('Relay Automation Run',{'message':doc.name},'name')
                    service.process(name)
                    assert frappe.db.get_value('Relay Automation Run',name,'status')==status
                    frappe.db.set_value('Relay Ticket',run.ticket,'ai_disabled',0)
                    frappe.db.set_value('Relay Contact Endpoint',{'channel':channel.name,'endpoint':endpoint},'verified',1)
                assert complete.call_count==2 and send.call_count==1
                print('PASS no events, Shadow, changed event version, takeover and revoked identity during matching')

                # A linked accounting user can still read Supplier/Company after losing Relay access.
                restricted = frappe.get_doc(dict(doctype='User', email='sim-matching-denied-'+stamp.lower()+'@example.invalid',
                    first_name='Sim Matching Denied '+stamp, send_welcome_email=0,
                    roles=[{'role': role} for role in ('Accounts Manager', 'Purchase Manager')])).insert()
                frappe.db.set_value('Contact', person.name, 'user', restricted.name)
                frappe.db.commit()
                assert frappe.has_permission('Supplier', 'read', supplier, user=restricted.name)
                assert frappe.has_permission('Company', 'read', company, user=restricted.name)
                assert not frappe.has_permission('Relay Message', 'read', user=restricted.name)
                before = model.call_count
                doc=source('Private source must never reach classifier')
                response=request('automation.service.enqueue', {'message': doc.name})
                assert response.status_code == 200 and set(response.json['message']) == {'name', 'status'}
                service.process(response.json['message']['name'])
                denied=frappe.get_doc('Relay Automation Run', response.json['message']['name'])
                assert denied.status == 'Handoff' and model.call_count == before
                frappe.db.set_value('Contact', person.name, 'user', None)
                frappe.db.commit()
                # Exercise Frappe's actual field-level filter with a local metadata copy.
                from copy import deepcopy
                message_meta = deepcopy(frappe.get_meta('Relay Message'))
                message_meta.get_field('content').permlevel = 1
                actual_meta = frappe.get_meta
                def restricted_meta(doctype, *args, **kwargs):
                    return message_meta if doctype == 'Relay Message' else actual_meta(doctype, *args, **kwargs)
                doc=source('Private content field must never reach classifier')
                response=request('automation.service.enqueue', {'message': doc.name})
                with patch.object(frappe, 'get_meta', side_effect=restricted_meta):
                    service.process(response.json['message']['name'])
                denied=frappe.get_doc('Relay Automation Run', response.json['message']['name'])
                assert denied.status == 'Handoff' and model.call_count == before
                print('PASS linked-user message denial and real field filtering prevent classifier disclosure')

                # Matching has its own channel budget; the alphabetically first event may be exhausted.
                frappe.db.set_value('Relay AI Skill', event.name, 'daily_limit', 1)
                frappe.db.set_value('Relay AI Skill', ticket_event.name, 'exact_trigger', '')
                event.reload()
                try: service.reserve_attempt(event)
                except ValueError: pass  # Earlier event proposals already consumed this allowance.
                def match_support(ai_model, targets, *args, **kwargs):
                    return {'human_request': False, 'scores': [dict(id=t['id'], score=.98 if t['id']==ticket_event.name else .1) for t in targets]}
                model.side_effect=match_support
                doc=source('A different support event with its own allowance')
                response=request('automation.service.enqueue', {'message': doc.name})
                service.process(response.json['message']['name'])
                budget_run=frappe.get_doc('Relay Automation Run', response.json['message']['name'])
                assert budget_run.status == 'Completed' and budget_run.skill == ticket_event.name
                frappe.db.set_value('Relay AI Skill', event.name, 'daily_limit', 100)
                frappe.db.set_value('Relay AI Skill', ticket_event.name, 'exact_trigger', '/support')
                print('PASS exhausted first event does not block classification of another event')

                from concurrent.futures import ThreadPoolExecutor
                doc=source('Concurrent ledger admission')
                def concurrent_admission(_):
                    connect()
                    try:
                        for attempt in range(6):
                            try:
                                result=service.create_run(frappe.get_doc('Relay Message',doc.name))
                                frappe.db.commit()
                                return result
                            except frappe.QueryDeadlockError:
                                # Same transaction retry as Frappe's worker runner.
                                frappe.db.rollback()
                                if attempt==5: raise
                    finally:
                        frappe.destroy()
                with ThreadPoolExecutor(max_workers=6) as pool:
                    results=list(pool.map(concurrent_admission,range(12)))
                assert len({result['name'] for result in results})==1
                frappe.db.rollback()
                assert frappe.db.count('Relay Automation Run',{'message':doc.name})==1
                assert frappe.db.get_value('Relay Message',doc.name,'ticket')==run.ticket
                print('PASS twelve competing admissions share one run and episode')

                # A real explicit flow competes with the exact event trigger.
                from relay_core.flows import service as flows
                flow=raw('Relay Flow','Matching Flow',title='Sim Matching Flow '+stamp,enabled=1,
                    channel=channel.name,business_doctype='Supplier',execution_user=actor.name,command='/support',
                    trigger_key=flows.digest(channel.name,'/support'))
                nodes=json.dumps([dict(id='ticket',kind='ticket',text='Staff check amount 1250'),
                                  dict(id='end',kind='end',text='Flow completed')])
                version=raw('Relay Flow Version','Matching Flow Version',flow=flow.name,nodes=nodes,
                    channel=channel.name,business_doctype='Supplier',execution_user=actor.name,definition_hash='local')
                frappe.db.set_value('Relay Flow',flow.name,'published_version',version.name)
                doc=source('/support')
                response=request('flows.service.enqueue',{'message':doc.name})
                assert response.status_code==200 and set(response.json['message'])=={'event'}
                flow_event=response.json['message']['event']; assert flow_event
                admitted=frappe.get_doc('Relay Automation Run',{'message':doc.name})
                assert admitted.stage=='Flow' and admitted.ticket==run.ticket and not admitted.skill
                with patch.object(flows,'send') as flow_send:
                    flows.process(flow_event)
                    assert frappe.db.get_value('Relay Flow Event',flow_event,'status')=='Complete'
                    flow_send.assert_called_once()
                queue._process(doc.name); frappe.db.commit()
                assert frappe.db.count('Relay Flow Event',{'message':doc.name})==1
                doc=source('Talk to a human')
                queue._process(doc.name); frappe.db.commit()
                human=frappe.get_doc('Relay Automation Run',{'message':doc.name})
                assert human.status=='Handoff' and human.ticket==run.ticket
                assert not frappe.db.exists('Relay Flow Event',{'message':doc.name})
                print('PASS real flow/event exclusion through manual API and drain; human request triage')

                # Internal admission/model entry points never become HTTP RPC APIs.
                for method in ('ai.matching.select','ai.matching.candidates','ai.matching.validate_result',
                               'ai.adapter.match','ai.service.admit','automation.service.create_run',
                               'automation.service.episode','automation.service.triage','flows.service.create_event','flows.service.flow_ticket'):
                    response=request(method)
                    assert response.status_code==403, (method,response.status_code)
                response=request('flows.service.enqueue',{'message':doc.name},authenticated=False)
                assert response.status_code in (401,403) and response.json['exc_type']=='PermissionError'
                print('PASS HTTP private-function denial and flow enqueue guest denial')
        finally:
            connect(); frappe.db.rollback()
            # Only exact records inserted by this process are deleted. No retained
            # local businesses or configuration are selected by broad name filters.
            for doctype,name in reversed(created):
                frappe.db.delete('__Auth', {'doctype':doctype, 'name':name})
                frappe.db.delete(doctype, {'name':name})
            frappe.db.commit()
            assert all(not frappe.db.exists(dt,name) for dt,name in created)
            frappe.destroy()
            print('CLEANUP all created fixtures deleted, including Company and ledger entries')


if __name__=='__main__':
    main()
