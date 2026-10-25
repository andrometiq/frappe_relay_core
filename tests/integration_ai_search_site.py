"""Step 6 declared searches through real yrp.site HTTP, drain and worker paths.

External models, sends, queues and notifications are intercepted. Every inserted
fixture (including children and Companies) is removed in finally.
"""
import json
import os
from pathlib import Path
import secrets
import sys
from contextlib import ExitStack, contextmanager
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
    from relay_core.ai.tools import Reader
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
    @contextmanager
    def fixture_admin():
        previous=frappe.session.user
        frappe.set_user('Administrator')
        try: yield
        finally: frappe.set_user(previous)
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
        stack.enter_context(patch('relay_core.messaging.connection_value', return_value='Sim Search '+stamp))
        stack.enter_context(patch('relay_core.whatsapp.client', side_effect=AssertionError('External delivery forbidden')))
        stack.enter_context(patch('frappe.core.doctype.user.user.throttle_user_creation'))
        # No outbound email, including fixture provisioning notifications.
        stack.enter_context(patch.object(frappe, 'sendmail'))
        try:
            company = raw('Company', 'Search Company', company_name='Sim Search Company '+stamp,
                          abbr='SM', country='India', default_currency='INR')
            actor = frappe.get_doc(dict(doctype='User', email='sim-search-'+stamp.lower()+'@example.invalid',
                first_name='Sim Search Operator '+stamp, send_welcome_email=0,
                roles=[{'role':r} for r in ('Relay Communication Manager','Relay Communication User',
                                          'Accounts Manager','Purchase Manager','Sales Manager')])).insert()
            actor.api_key, actor.api_secret = secrets.token_hex(12), secrets.token_hex(24)
            auth = 'token '+actor.api_key+':'+actor.api_secret
            actor.save()
            endpoint = phone(stamp)
            supplier = raw('Supplier', 'Search Supplier', supplier_name='Sim Search Supplier '+stamp,
                           supplier_type='Company', alias=endpoint)
            person = frappe.get_doc(dict(doctype='Contact', first_name='Sim Search Person '+stamp,
                links=[dict(link_doctype='Supplier',link_name=supplier.name)])).insert()
            contact = frappe.get_doc(dict(doctype='Relay Contact',contact=person.name,
                                         display_name='Sim Search Contact '+stamp)).insert()
            channel = frappe.get_doc(dict(doctype='Relay Channel',channel='WhatsApp',account='Sim Search '+stamp,
                company=company.name,triage_owner=actor.name,enabled=1)).insert(set_name=sequential_name('channel'))
            frappe.get_doc(dict(doctype='Relay Contact Endpoint',channel=channel.name,endpoint=endpoint,
                               relay_contact=contact.name,verified=1)).insert()
            contract = dict(name='supplier_ledger', method='get_list', doctype='GL Entry', scope_field='party',
                fields=['name','company','posting_date','debit','credit'], identity_anchor='Supplier',
                identity_fields={'WhatsApp':'alias'}, company_field='company')
            raw('GL Entry','Search Debit',company=company.name,party_type='Supplier',party=supplier.name,
                posting_date='2026-10-01',debit=1250,credit=0,is_cancelled=0)
            raw('GL Entry','Search Credit',company=company.name,party_type='Supplier',party=supplier.name,
                posting_date='2026-10-02',debit=0,credit=250,is_cancelled=0)
            event = raw('Relay AI Skill','Search Ledger',title='Sim Search Ledger '+stamp,enabled=1,
                channel=channel.name,business_doctype='Supplier',run_as_user=actor.name,handoff_owner=actor.name,
                mode='Automatic',daily_limit=100,search_confirmation='When required',target='Explain supplier ledger',instructions='Use my ledger only',
                execution_policy='Execute',allowed_tools=json.dumps([contract]),allowed_actions='[{"action":"reply"}]')
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
            from types import SimpleNamespace
            from frappe_tools.ai import client as model_client
            from relay_core import messaging
            from relay_core.ai.tools import as_user
            plan = dict(purpose='Review your ledger', reference=contract['name'], fields=contract['fields'],
                arguments={'filters':{'posting_date':['between',['2026-10-01','2026-10-31']]}})
            desired = dict(plan)
            legacy = False
            change_read = False
            chain = False
            mutation_fault = None
            outbound = []
            transport_status = 'Submitted'
            def transport(tool, arguments):
                assert tool == 'whatsapp.execute'
                outbound.append(arguments)
                if transport_status != 'Submitted':
                    return {'delivery':{'state':transport_status.lower()}}
                return {'messages':[{'id':'sim-search-'+str(len(outbound))}]}
            provider = SimpleNamespace(
                user_message=lambda text, images: {'text':text},
                continuation=lambda result, outputs: [{'outputs':outputs}],
                build_turn=lambda credentials, model, system, messages, schema, options, definitions, final:
                    dict(messages=messages,definitions=definitions))
            def model(account, model, build, options, context, deadline):
                turn = build(provider,None,model)
                assert [tool['name'] for tool in turn['definitions']] == ['SEARCH', 'EXECUTE']
                run = frappe.get_doc('Relay Automation Run',context['run_id'])
                calls=[]
                if run.search_plan and run.stage=='Event':
                    if len(turn['messages']) == 1:
                        arguments=json.loads(run.search_plan)['plan']['arguments']
                        if change_read: arguments={'filters':{'posting_date':['between',['2026-09-01','2026-09-30']]}}
                        calls=[{'id':'read','name':contract['name'] if legacy else 'SEARCH',
                            'arguments':json.dumps(arguments if legacy else dict(purpose=json.loads(run.search_plan)['plan']['purpose'],
                                reference=contract['name'], arguments=arguments))}]
                        data=None
                    elif chain and len(turn['messages']) == 2:
                        calls = [dict(id='reply', name='EXECUTE', arguments=dict(action='reply',
                            parameters={'text': 'Invented closing balance 999999'})),
                            dict(id='draft', name='EXECUTE', arguments=dict(action='create_draft', parameters=draft_values))]
                        data = None
                    else:
                        data=dict(reply='' if chain else 'Invented total 999999',handoff=False,reason='')
                else:
                    data=dict(reply='Please confirm 2026-10-01 to 2026-10-31',handoff=False,reason='')
                    if not legacy: data['search']=desired
                return {'ok':True,'result':{'data':data,'tool_calls':calls,'response':{}}}
            def classify(ai_model,targets,*args,**kwargs):
                return {'human_request':False,'scores':[{'id':t['id'],'score':.98} for t in targets]}
            read_calls=[]
            original_read=Reader._read
            def reading(reader, reference, arguments):
                read_calls.append((reference['name'],arguments))
                return original_read(reader,reference,arguments)
            def run_message(text):
                doc=source(text)
                response=request('automation.service.enqueue',{'message':doc.name})
                assert response.status_code==200, ('enqueue',response.status_code,response.json.get('exc_type'))
                assert set(response.json['message'])=={'name','status'}
                service.process(response.json['message']['name'])
                return doc,frappe.get_doc('Relay Automation Run',response.json['message']['name'])
            def deny_read(run):
                with as_user(actor.name):
                    user,business,scope=ai.context(event,frappe.get_doc('Relay Message',run.message))
                    reader=Reader(event,user,business,scope,authorize=lambda ref,args:ai.authorize_search(run.name,event,ref,args))
                    try: reader.read(contract,**plan['arguments'])
                    except ValueError: pass
                    else: raise AssertionError('Undeclared read succeeded')
            def reset_hold():
                from relay_core.tickets import resume_ai
                for name in frappe.get_all('Relay Ticket', filters={'company':company.name,
                        'ai_disabled':1, 'active_scope_key':['is','set']}, pluck='name'):
                    resume_ai(name)
                frappe.db.commit()
            with patch.object(adapter,'match',side_effect=classify), \
                    patch.object(adapter,'route',return_value=(frappe._dict(provider='Sim'),frappe._dict(model_id='Sim'),[],
                        dict(timeout=20,max_tokens=1200,attempts=1))), \
                    patch.dict(model_client.PROVIDERS,Sim=provider), \
                    patch.object(model_client,'try_model',side_effect=model), \
                    patch('relay_core.whatsapp.client',return_value=SimpleNamespace(call_tool=transport)), \
                    patch.object(Reader,'_read',reading):
                doc,offer=run_message('Explain my October ledger')
                assert offer.status=='Completed' and offer.stage=='Search', (offer.status,offer.reason)
                assert json.loads(offer.decision)['reads']==[] and not read_calls
                deny_read(offer)
                assert len(outbound)==1 and 'confirm' in outbound[-1]['body']
                announcement=frappe.get_doc('Relay Message Action',{'source_message':doc.name})
                assert announcement.status=='Submitted'
                from relay_core.flows import service as flows
                competing=raw('Relay Flow','Search Competing Flow',title='Sim Search Flow '+stamp,enabled=1,
                    channel=channel.name,business_doctype='Supplier',execution_user=actor.name,command='yes',
                    trigger_key=flows.digest(channel.name,'yes'))
                version=raw('Relay Flow Version','Search Competing Version',flow=competing.name,
                    nodes=json.dumps([dict(id='end',kind='end',text='Flow reply')]),
                    channel=channel.name,business_doctype='Supplier',execution_user=actor.name,definition_hash='local')
                frappe.db.set_value('Relay Flow',competing.name,'published_version',version.name)
                doc,confirmed=run_message('yes')
                assert not frappe.db.exists('Relay Flow Event',{'message':doc.name})
                frappe.db.set_value('Relay Flow',competing.name,'enabled',0)
                assert confirmed.status=='Completed' and confirmed.stage=='Event', (confirmed.status,confirmed.reason)
                evidence=json.loads(confirmed.decision)
                assert len(evidence['reads'])==1
                rendered=evidence['actions'][0]['parameters']['text']
                assert '1250' in rendered and '250' in rendered and '999999' not in rendered
                assert len(outbound)==2 and read_calls
                count=len(read_calls)
                replay=request('automation.service.enqueue',{'message':doc.name})
                assert replay.status_code==200 and replay.json['message']['name']==confirmed.name
                queue._process(doc.name); frappe.db.commit(); service.process(confirmed.name)
                assert len(outbound)==2 and len(read_calls)==count
                ai.complete_delivery(announcement.name)
                confirmed.reload(); assert confirmed.status=='Completed'
                print('PASS HTTP admission/status/shape, real journal, no premature reads, confirmed non-zero ledger, flow exclusion and replay')

                # Range changes get a new declaration and cannot borrow prior approval.
                doc,old=run_message('Explain October again')
                count=len(read_calls)
                desired=dict(plan,arguments={'filters':{'posting_date':['between',['2026-10-01','2026-10-02']]}})
                doc,changed=run_message('Change the range to October 1 through October 2')
                assert changed.stage=='Search' and json.loads(changed.search_plan)['plan']==desired
                assert len(read_calls)==count
                doc,confirmed=run_message('yes')
                assert confirmed.status=='Completed' and len(read_calls)>count
                assert json.loads(confirmed.decision)['reads'][0]['arguments']==desired['arguments']
                print('PASS changed date range gets a new announcement and exact confirmation')

                desired=dict(plan)
                transport_status='Uncertain'
                doc,uncertain=run_message('Explain my October ledger')
                assert uncertain.status=='Delivering' and uncertain.stage=='Search'
                count=len(read_calls); deny_read(uncertain); assert len(read_calls)==count
                action=frappe.get_doc('Relay Message Action',{'source_message':doc.name})
                # Receipt recovery uses the real message journal completion path.
                transport_status='Submitted'
                with as_user(actor.name):
                    src,ch,ctx=messaging.action_target(action)
                    messaging.finish(action,src,ch,ctx,json.loads(action.payload)['content'],{'messages':[{'id':'sim-recovered'}]})
                ai.complete_delivery(action.name)
                uncertain.reload(); assert uncertain.status=='Completed' and uncertain.stage=='Search'
                doc,confirmed=run_message('yes')
                assert confirmed.status=='Completed' and len(read_calls)>count
                print('PASS uncertain announcement blocks reads and submitted receipt recovery unlocks exact confirmation')

                # Existing single-event Hub ledger conversation: text offer and named reference call.
                legacy=True
                doc,offer=run_message('I have a doubt in my ledger')
                assert offer.stage=='Search' and offer.status=='Completed'
                doc,confirmed=run_message('yes')
                assert confirmed.status=='Completed' and len(json.loads(confirmed.decision)['reads'])==1
                legacy=False
                print('PASS existing single-event supplier ledger offer/yes/reference-tool protocol')

                # A confirmed model trying a different date range cannot query or send a result.
                doc,offer=run_message('Explain my October ledger')
                count=len(read_calls); sent=len(outbound); change_read=True
                doc,denied=run_message('yes')
                assert denied.status=='Handoff' and len(read_calls)==count and len(outbound)==sent
                change_read=False; reset_hold()
                print('PASS changed model range denied before a business read or result send')

                # A clear non-ledger search can continue in the same run after submission.
                nonledger=dict(contract,name='payment_status',doctype='Payment Entry',
                    fields=['name','company','paid_amount'])
                raw('Payment Entry','Search Payment',company=company.name,party_type='Supplier',party=supplier.name,
                    paid_amount=1250,docstatus=0)
                frappe.db.set_value('Relay AI Skill',event.name,'allowed_tools',json.dumps([nonledger]))
                event.reload(); contract=nonledger
                desired=dict(purpose='Review your draft payment',reference=contract['name'],fields=contract['fields'],arguments={})
                count=len(read_calls); sent=len(outbound)
                doc,clear=run_message('Show my draft payment')
                assert clear.status=='Completed' and clear.stage=='Event', (clear.status,clear.reason)
                assert len(outbound)==sent+2 and len(read_calls)>count
                assert len(frappe.get_all('Relay Message Action',filters={'source_message':doc.name}))==2
                assert json.loads(clear.decision)['reads']
                # A late announcement callback cannot complete a pending final result.
                announcement=frappe.get_doc('Relay Message Action',{'request_key':ai.search_request_key(doc,actor.name)})
                frappe.db.set_value('Relay Automation Run',clear.name,'status','Delivering')
                final_action=frappe.get_doc('Relay Message Action',{'source_message':doc.name,'name':['!=',announcement.name]})
                frappe.enqueue.reset_mock(); ai.recover_deliveries()
                recovered={call.kwargs.get('action') for call in frappe.enqueue.call_args_list}
                assert final_action.name in recovered and announcement.name not in recovered
                ai.complete_delivery(announcement.name); clear.reload(); assert clear.status=='Delivering'
                frappe.db.set_value('Relay Automation Run',clear.name,'status','Completed')
                print('PASS same-turn non-ledger announcement/read with separate journal keys; late receipt is harmless')

                # Crash after Hub submission but before run advancement reuses the same action.
                actual_send=ai.send_reply
                sent=len(outbound)
                def crash_after_send(*args,**kwargs):
                    actual_send(*args,**kwargs)
                    raise KeyboardInterrupt('Simulated worker exit after durable send')
                doc=source('Review my payment again')
                response=request('automation.service.enqueue',{'message':doc.name})
                run_name=response.json['message']['name']
                with patch.object(ai,'send_reply',side_effect=crash_after_send):
                    try: service.process(run_name)
                    except KeyboardInterrupt: pass
                    else: raise AssertionError('Worker exit was not simulated')
                frappe.db.rollback()
                interrupted=frappe.get_doc('Relay Automation Run',run_name)
                assert interrupted.status=='Deciding' and interrupted.stage=='Search'
                assert len(outbound)==sent+1
                service.process(run_name); interrupted.reload()
                assert interrupted.status=='Completed' and len(outbound)==sent+2
                print('PASS worker exit after submission recovers without duplicate announcement')

                # Clear searches also resume via the existing receipt completion queue.
                transport_status='Queued'; count=len(read_calls)
                doc,queued=run_message('Review my draft payment once more')
                assert queued.status=='Delivering' and len(read_calls)==count
                action=frappe.get_doc('Relay Message Action',{'source_message':doc.name})
                transport_status='Submitted'
                with as_user(actor.name):
                    src,ch,ctx=messaging.action_target(action)
                    messaging.finish(action,src,ch,ctx,json.loads(action.payload)['content'],{'messages':[{'id':'sim-clear-recovery'}]})
                frappe.enqueue.reset_mock()
                ai.recover_deliveries()
                assert any(call.kwargs.get('action')==action.name for call in frappe.enqueue.call_args_list)
                ai.complete_delivery(action.name); queued.reload()
                assert queued.status=='Pending' and queued.stage=='Event'
                service.process(queued.name); queued.reload()
                assert queued.status=='Completed' and len(read_calls)>count
                print('PASS queued non-ledger search resumes after its Submitted receipt')

                # Execute the actual reply and draft chain using persisted, non-zero ledger evidence.
                from relay_core.ai.actions import PAYMENT_SCHEMA
                from relay_core.ai import actions as handlers
                bank=raw('Account', 'Search Bank', account_name='Sim Search Bank '+stamp, company=company.name,
                    account_type='Bank', root_type='Asset', report_type='Balance Sheet', account_currency='INR', is_group=0)
                payable=raw('Account', 'Search Payable', account_name='Sim Search Payable '+stamp, company=company.name,
                    account_type='Payable', root_type='Liability', report_type='Balance Sheet', account_currency='INR', is_group=0)
                frappe.db.set_value('Company', company.name, dict(default_payable_account=payable.name, default_bank_account=bank.name))
                contract=dict(name='supplier_ledger', method='get_list', doctype='GL Entry', scope_field='party',
                    fields=['name','company','posting_date','debit','credit'], identity_anchor='Supplier',
                    identity_fields={'WhatsApp':'alias'}, company_field='company')
                ledger_row=frappe.get_all('GL Entry', filters={'company':company.name}, pluck='name', order_by='name asc')[0]
                frappe.db.set_value('GL Entry', ledger_row, dict(debit=100.10, credit=40.05))
                declared=[dict(action='reply'), dict(action='create_draft', doctype='Payment Entry', fields=list(PAYMENT_SCHEMA['properties']))]
                frappe.db.set_value('Relay AI Skill', event.name, dict(allowed_tools=json.dumps([contract]), allowed_actions=json.dumps(declared)))
                event.reload()
                desired=dict(purpose='Review your ledger', reference=contract['name'], fields=contract['fields'],
                    arguments={'filters':{'posting_date':['between',['2026-10-01','2026-10-31']]}, 'limit':1})
                draft_values=dict(payment_type='Pay', posting_date='2026-10-25', paid_amount=1250, received_amount=1250,
                    paid_from=bank.name, paid_to=payable.name, source_exchange_rate=1, target_exchange_rate=1,
                    reference_no='Sim Search Evidence '+stamp, reference_date='2026-10-25')
                chain=True
                doc,offer=run_message('Search then execute the owner chain')
                before=frappe.db.count('Payment Entry', {'company':company.name})
                doc,executed=run_message('yes')
                assert executed.status=='Completed', (executed.status, executed.reason)
                assert frappe.db.count('Payment Entry', {'company':company.name})==before+1
                assert '60.05' in outbound[-1]['body'] and 'Partial totals' in outbound[-1]['body']
                assert '999999' not in outbound[-1]['body']
                assert [r.action for r in frappe.get_all('Relay Flow Action', filters={'automation_run':executed.name},
                    fields=['action'], order_by='step asc')] == ['reply', 'create_draft']
                print('PASS delivered EXECUTE reply contains calculated 60.05 and partial-results notice; declared draft follows')
                original_dispatch=ai.dispatch_reply
                verified_faults=[]
                def revoke_after_reply(*args, **kwargs):
                    result=original_dispatch(*args, **kwargs)
                    if kwargs.get('slot') == 'event_reply_0':
                        assert result['status']=='Submitted'
                        if mutation_fault == 'data':
                            frappe.db.set_value('GL Entry', ledger_row, 'debit', 9000)
                        elif mutation_fault == 'permission':
                            with fixture_admin():
                                actor.reload()
                                actor.roles = [r for r in actor.roles if r.role not in ('Accounts Manager', 'Accounts User', 'Auditor')]
                                actor.save()
                                frappe.clear_cache(user=actor.name)
                            assert not frappe.has_permission('GL Entry', 'read', user=actor.name)
                        frappe.db.commit()
                        verified_faults.append(mutation_fault)
                    return result
                original_create=handlers.create_draft
                def change_during_write(**kwargs):
                    result=original_create(**kwargs)
                    frappe.db.set_value('GL Entry', ledger_row, 'debit', 9000)
                    return result
                for mutation_fault in ('permission', 'data', 'during_write'):
                    reset_hold()
                    doc,offer=run_message('Verify fresh evidence for '+mutation_fault)
                    before=frappe.db.count('Payment Entry', {'company':company.name})
                    with patch.object(handlers, 'create_draft', side_effect=change_during_write if mutation_fault=='during_write' else original_create) as create, \
                            patch.object(ai, 'dispatch_reply', side_effect=revoke_after_reply):
                        doc,denied=run_message('yes')
                    assert mutation_fault in verified_faults
                    assert create.call_count == (1 if mutation_fault=='during_write' else 0)
                    assert denied.status=='Handoff', (mutation_fault, denied.status, denied.reason)
                    assert frappe.db.count('Payment Entry', {'company':company.name})==before
                    assert not frappe.db.exists('Relay Flow Action', {'automation_run':denied.name, 'action':'create_draft', 'status':'Completed'})
                    with fixture_admin():
                        actor.reload()
                        if not any(r.role=='Accounts Manager' for r in actor.roles):
                            actor.append('roles', {'role':'Accounts Manager'}); actor.save()
                            frappe.clear_cache(user=actor.name)
                        frappe.db.set_value('GL Entry', ledger_row, 'debit', 100.10)
                        frappe.db.commit()
                mutation_fault=None
                print('PASS revoked ledger permission and changed evidence after reply block the next draft; change during insert rolls back draft and journal')

                for method in ('ai.service.declare_search','ai.service.check_search','ai.service.authorize_search',
                    'ai.service.continue_search','ai.service.search_delivered','ai.service.search_scope',
                    'ai.service.search_request_key','ai.service.confirmation_required','ai.adapter.complete',
                    'ai.service.decide','ai.service.process','ai.service.delivery_scope','ai.service.send_reply',
                    'ai.service.complete_delivery','ai.service.recover_deliveries','automation.contracts.action_key',
                    'automation.contracts.validate_search','ai.tools.recheck'):
                    response=request(method)
                    assert response.status_code==403 and response.json['exc_type']=='PermissionError', (method,response.status_code)
                response=request('automation.service.enqueue',{'message':doc.name},authenticated=False)
                assert response.status_code in (401,403) and response.json['exc_type']=='PermissionError'
                response=request('automation.service.enqueue',{'message':doc.name},verb='GET')
                assert response.status_code==403
                print('PASS internal search helpers deny HTTP, enqueue denies guests and wrong method')
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
