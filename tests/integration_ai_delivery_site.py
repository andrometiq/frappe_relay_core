"""Step 10 delivery fencing through real yrp.site HTTP and worker paths.

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
    for name in ('relay_ticket', 'relay_automation_run', 'relay_business_event_delivery'):
        frappe.reload_doc('relay_core', 'doctype', name, force=True)
    frappe.db.commit()
    print('RELOADED Relay Ticket, Relay Automation Run, Relay Business Event Delivery from worktree JSON')
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
        stack.enter_context(patch('relay_core.messaging.connection_value', return_value='Sim Delivery '+stamp))
        stack.enter_context(patch('relay_core.conversation_start.connection_value', return_value='Sim Delivery '+stamp))
        stack.enter_context(patch('relay_core.whatsapp.client', side_effect=AssertionError('External delivery forbidden')))
        stack.enter_context(patch('frappe.core.doctype.user.user.throttle_user_creation'))
        # No outbound email, including fixture provisioning notifications.
        stack.enter_context(patch.object(frappe, 'sendmail'))
        try:
            company = raw('Company', 'Delivery Company', company_name='Sim Delivery Company '+stamp,
                          abbr='SM', country='India', default_currency='INR')
            actor = frappe.get_doc(dict(doctype='User', email='sim-delivery-'+stamp.lower()+'@example.invalid',
                first_name='Sim Delivery Operator '+stamp, send_welcome_email=0,
                roles=[{'role':r} for r in ('Relay Communication Manager','Relay Communication User',
                                          'Accounts Manager','Purchase Manager','Sales Manager')])).insert()
            actor.api_key, actor.api_secret = secrets.token_hex(12), secrets.token_hex(24)
            auth = 'token '+actor.api_key+':'+actor.api_secret
            actor.save()
            endpoint = phone(stamp)
            supplier = raw('Supplier', 'Delivery Supplier', supplier_name='Sim Delivery Supplier '+stamp,
                           supplier_type='Company', alias=endpoint)
            person = frappe.get_doc(dict(doctype='Contact', first_name='Sim Delivery Person '+stamp,
                links=[dict(link_doctype='Supplier',link_name=supplier.name)])).insert()
            contact = frappe.get_doc(dict(doctype='Relay Contact',contact=person.name,
                                         display_name='Sim Delivery Contact '+stamp)).insert()
            channel = frappe.get_doc(dict(doctype='Relay Channel',channel='WhatsApp',account='Sim Delivery '+stamp,
                company=company.name,triage_owner=actor.name,enabled=1)).insert(set_name=sequential_name('channel'))
            frappe.get_doc(dict(doctype='Relay Contact Endpoint',channel=channel.name,endpoint=endpoint,
                               relay_contact=contact.name,verified=1)).insert()
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
            from relay_core import tickets, messaging, business_events, email
            from concurrent.futures import ThreadPoolExecutor
            from unittest.mock import Mock
            doc = source('Supplier delivery amount 1250')
            ticket = tickets.ensure_episode(doc, owner=actor.name)
            frappe.db.commit(); doc.reload()
            order = raw('Purchase Order', 'Delivery Order', supplier=supplier.name, company=company.name,
                        grand_total=1250, total_qty=25, transaction_date='2026-10-25')
            rule = raw('Relay Business Event Rule', 'Delivery Notice', title='Sim Delivery Notice '+stamp,
                enabled=1, source_doctype='Purchase Order', event='on_submit', recipient_field='supplier',
                business_doctype='Supplier', contact=person.name, channel=channel.name,
                run_as_user=actor.name, template='Sim Delivery Template '+stamp,
                parameter_mapping=json.dumps(['grand_total','total_qty']))
            approved = stack.enter_context(patch.object(business_events, 'approved', return_value=frappe._dict(
                template_name='sim_delivery_notice', language='en')))
            order.reload()
            sequence = 0
            def capture():
                nonlocal sequence
                sequence += 1
                # Distinct source events, immutable non-zero document values.
                business_events.capture(rule, order, 'sim_notice_'+str(sequence))
                frappe.db.commit()
                name = frappe.db.get_value('Relay Business Event Delivery',
                    {'source_name':order.name, 'event':'sim_notice_'+str(sequence)}, 'name')
                return frappe.get_doc('Relay Business Event Delivery', name)
            def ownership(method):
                response=request('tickets.'+method, {'name':ticket.name})
                assert response.status_code==200, (method,response.status_code,response.json.get('exc_type'))
                assert set(response.json['message'])=={'name','ai_disabled','generation'}
                return response.json['message']
            def receipt(tool, args):
                assert tool in ('whatsapp.execute','email.send'), tool
                return {'delivery':{'state':'queued'}}
            hub=Mock();hub.call_tool.side_effect=receipt
            stack.enter_context(patch('relay_core.whatsapp.client',return_value=hub))

            # Starting from the business composer must join the existing episode.
            from relay_core import conversation_start
            for provider in ('WhatsApp', 'Telegram'):
                start_channel = channel
                start_ticket = ticket
                if provider == 'Telegram':
                    start_channel = frappe.get_doc(dict(doctype='Relay Channel',channel='Telegram',account=channel.account,
                        company=company.name,triage_owner=actor.name,enabled=1)).insert(set_name=sequential_name('channel'))
                    frappe.get_doc(dict(doctype='Relay Contact Endpoint',channel=start_channel.name,endpoint=endpoint,
                        relay_contact=contact.name,verified=1)).insert()
                    context=dict(provider='Telegram',chat_id=int(endpoint),chat_type='private',message_id=1,participant_id=int(endpoint))
                    incoming=frappe.get_doc(dict(doctype='Relay Message',relay_contact=contact.name,channel=start_channel.name,
                        sender_endpoint=endpoint,direction='Incoming',message_type='text',content='Check 1250',status='Sent',
                        business_doctype='Supplier',business_name=supplier.name,provider_context=json.dumps(context),
                        conversation_key=conversation_key(start_channel.name,endpoint,context))).insert()
                    start_ticket=tickets.ensure_episode(incoming,owner=actor.name)
                start_args=dict(contact=person.name,channel=start_channel.name,kind='text',data={'text':'Staff checking 1250'},
                    request_key='sim-start-'+provider+'-'+stamp,business_doctype='Supplier',business_name=supplier.name)
                original=conversation_start.internal_save
                def assert_hold(action, **kwargs):
                    assert frappe.db.get_value('Relay Ticket',start_ticket.name,'ai_disabled')
                    assert json.loads(action.payload)['ticket']==start_ticket.name
                    return original(action,**kwargs)
                hub.call_tool.side_effect=lambda *a: {'delivery':{'state':'queued'}}
                with patch.object(conversation_start.service_window,'require_open'), patch.object(conversation_start,'internal_save',side_effect=assert_hold):
                    response=request('conversation_start.send_business',start_args)
                assert response.status_code==200 and response.json['message']['status']=='Queued', (provider,response.status_code)
                action_name=response.json['message']['action']
                assert request('conversation_start.send_business',start_args,authenticated=False).status_code in (401,403)
                # Delayed receipt uses the stored episode, after staff ownership.
                result={'messages':[{'id':'sim-start-'+stamp}]} if provider=='WhatsApp' else {'message_id':2}
                hub.call_tool.side_effect=lambda tool,args: {'deliveries':[{'key':args['request_key'],'operation':'telegram.message' if provider=='Telegram' else 'whatsapp.execute','state':'submitted','result':result}]}
                response=request('messaging.reconcile',{'action':action_name})
                assert response.status_code==200 and response.json['message']['status']=='Submitted', (provider,response.status_code)
                outgoing=frappe.get_doc('Relay Message',response.json['message']['message'])
                assert outgoing.ticket==start_ticket.name
                assert request('tickets.resume_ai',{'name':start_ticket.name}).status_code==200
                def fail_journal(*args,**kwargs): raise frappe.ValidationError('Sim journal rollback')
                start_args['request_key']+='-failed'
                with patch.object(conversation_start.service_window,'require_open'),patch.object(conversation_start,'internal_save',side_effect=fail_journal):
                    response=request('conversation_start.send_business',start_args)
                assert response.status_code==417
                start_ticket.reload(); assert not start_ticket.ai_disabled
            hub.call_tool.side_effect=receipt
            print('PASS WhatsApp/Telegram business-start HTTP hold, journal rollback, guest denial and delayed outbound episode recovery')

            happy=capture()
            business_events.dispatch(happy.name);happy.reload()
            assert happy.status=='Queued' and happy.action, (happy.status,happy.action)
            sent=hub.call_tool.call_args.args
            assert sent[0]=='whatsapp.execute'
            assert [p['text'] for p in sent[1]['components'][0]['parameters']]==['1250.0','25.0']
            print('PASS populated lifecycle capture -> conversation start -> durable queued transport')

            # Lifecycle notices are independent of AI ownership, before or during a hold.
            pending=capture(); ownership('claim'); during=capture()
            hub.reset_mock()
            for delivery in (pending,during):
                business_events.dispatch(delivery.name);delivery.reload()
                assert delivery.status=='Queued' and delivery.action, (delivery.status,delivery.action)
                action=frappe.get_doc('Relay Message Action',delivery.action)
                assert action.status=='Queued' and not json.loads(action.result).get('suppressed')
            assert hub.call_tool.call_count==2
            response=request('tickets.deliveries',{'name':ticket.name},verb='GET')
            assert response.status_code==200, response.status_code
            states={row['name']:row['status'] for row in response.json['message']['items']}
            assert all(states[delivery.name]=='Queued' for delivery in (happy,pending,during))
            ownership('resume_ai')
            for delivery in (pending,during): business_events.dispatch(delivery.name)
            assert hub.call_tool.call_count==2  # Dispatch replay never sends accepted notices again.
            fresh=capture();business_events.dispatch(fresh.name);fresh.reload();assert fresh.status=='Queued'
            print('PASS lifecycle notices deliver during hold; resume does not resend them; fresh notice allowed')

            # Recovery reads accepted transport state even after takeover, never resending.
            ownership('claim')
            hub.reset_mock();hub.call_tool.side_effect=lambda tool,args: {'deliveries':[{
                'key':args['request_key'],'state':'submitted','result':{'messages':[{'id':'sim-recovered-'+stamp}]}}]}
            response=request('messaging.reconcile', {'action':happy.action})
            assert response.status_code==200 and response.json['message']['status']=='Submitted', response.status_code
            assert set(response.json['message'])=={'action','status','message'}
            assert hub.call_tool.call_count==1 and hub.call_tool.call_args.args[0]=='whatsapp.deliveries'
            response=request('messaging.reconcile', {'action':happy.action},authenticated=False)
            assert response.status_code in (401,403)
            ownership('resume_ai')
            print('PASS HTTP recovery status/shape/guest denial; accepted delivery remains receipt-only after takeover')

            # Independent connection takes ownership exactly after journal commit.
            def claim_worker():
                connect();frappe.set_user(actor.name)
                try:
                    result=tickets.claim(ticket.name);frappe.db.commit();return result
                finally:frappe.destroy()
            def claim_after_commit():
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(claim_worker).result(timeout=15)
            save=messaging.internal_save
            def racing_save(action, **kwargs):
                result=save(action,**kwargs)
                if action.doctype=='Relay Message Action' and kwargs.get('new'):
                    frappe.db.after_commit.add(claim_after_commit)
                return result
            racing=capture();hub.reset_mock();hub.call_tool.side_effect=receipt
            with patch('relay_core.conversation_start.internal_save',side_effect=racing_save):
                business_events.dispatch(racing.name)
            racing.reload();assert racing.status=='Queued',racing.status
            hub.call_tool.assert_called_once()
            ownership('resume_ai')
            print('PASS takeover between journaling and dispatch preserves lifecycle notice admission')

            # Lifecycle notice admission does not need to serialize a staff claim.
            from threading import Event
            started=Event()
            winner=capture()
            def waiting_claim():
                started.set()
                return claim_worker()
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending_claim=[]
                def admitted(tool,args):
                    pending_claim.append(pool.submit(waiting_claim))
                    assert started.wait(2)
                    assert pending_claim[0].result(timeout=15)['ai_disabled']
                    return {'delivery':{'state':'queued'}}
                hub.call_tool.side_effect=admitted
                business_events.dispatch(winner.name)
                assert pending_claim[0].result(timeout=15)['ai_disabled']
            frappe.db.rollback();winner.reload();assert winner.status=='Queued'
            ownership('resume_ai')
            print('PASS lifecycle send allows concurrent takeover; accepted transport remains outstanding')

            # A lifecycle notice left Dispatching can recover after claim/resume,
            # using the same journal identity after checking for a Hub receipt.
            crashed=capture()
            class SimulatedCrash(BaseException): pass
            def crash_after_journal(action, **kwargs):
                result=save(action,**kwargs)
                if action.doctype=='Relay Message Action' and kwargs.get('new'):
                    frappe.db.commit();raise SimulatedCrash()
                return result
            try:
                with patch('relay_core.conversation_start.internal_save',side_effect=crash_after_journal):
                    business_events.dispatch(crashed.name)
            except SimulatedCrash: pass
            key=business_events.action_key(crashed,rule)
            action_name=frappe.db.get_value('Relay Message Action',{'request_key':key},'name')
            assert action_name
            ownership('claim');ownership('resume_ai')
            hub.reset_mock();hub.call_tool.side_effect=lambda tool,args: (
                {'deliveries':[]} if tool=='whatsapp.deliveries' else receipt(tool,args))
            response=request('messaging.reconcile',{'action':action_name})
            assert response.status_code==200 and response.json['message']['status']=='Queued',response.status_code
            assert [call.args[0] for call in hub.call_tool.call_args_list]==['whatsapp.deliveries','whatsapp.execute']
            assert all(call.args[1]['request_key']==key for call in hub.call_tool.call_args_list)
            crashed.reload();assert crashed.status=='Queued'
            print('PASS lifecycle crash recovery keeps its original request key after claim/resume')

            # A claimed unresolved triage has no active business scope key.
            from relay_core import business_routing_prompt
            event=raw('Relay Hub Event','Delivery Routing Event',account=channel.account,
                event_id='sim-routing-'+stamp,event_type='message',payload='{}')
            triage=tickets.ensure_episode(event=event,channel=channel.name,row={
                'from':endpoint,'id':'sim-routing-'+stamp,'provider_context':{'provider':'WhatsApp','message_id':'sim-routing-'+stamp}})
            assert triage and not triage.active_scope_key
            assert request('tickets.claim',{'name':triage.name}).status_code==200
            state=frappe.get_doc('Relay Business Routing',{'conversation_key':doc.conversation_key})
            choices=[dict(id='sim-supplier',title='Sim Supplier',description='Supplier account',doctype='Supplier',name=supplier.name)]
            state.choices=json.dumps(choices)
            state.prompt_expires_at=frappe.utils.add_to_date(frappe.utils.now_datetime(),minutes=10)
            state.prompt_action=business_routing_prompt.create(state,choices)
            messaging.internal_save(state);frappe.db.commit()
            hub.reset_mock();hub.call_tool.side_effect=lambda *a: {'deliveries':[]}
            with patch.object(business_routing_prompt,'connection_value',return_value=channel.account):
                response=request('messaging.reconcile',{'action':state.prompt_action})
                assert response.status_code==403  # Internal routing journal remains private.
                result=business_routing_prompt.dispatch(state.prompt_action)
            assert result['status']=='Rejected' and 'staff' in result['error']
            assert hub.call_tool.call_count==1 and hub.call_tool.call_args.args[0]=='whatsapp.deliveries'
            print('PASS HTTP claim/deny and routing worker: unresolved triage fences queued business-choice prompt')

            # Real email auto-reply journal; claim occurs after prepare commits.
            email_channel=frappe.get_doc(dict(doctype='Relay Channel',channel='Email',account=channel.account,
                company=company.name,triage_owner=actor.name,enabled=1)).insert(set_name=sequential_name('channel'))
            address='sim-delivery-'+stamp.lower()+'@example.invalid'
            frappe.get_doc(dict(doctype='Relay Contact Endpoint',channel=email_channel.name,endpoint=address,
                relay_contact=contact.name,verified=1)).insert()
            context=dict(provider='Email',message_id='<sim-email-'+stamp+'@example.invalid>',
                email_thread_id='<sim-email-'+stamp+'@example.invalid>',authentication={'status':'pass'})
            email_source=frappe.get_doc(dict(doctype='Relay Message',relay_contact=contact.name,channel=email_channel.name,
                sender_endpoint=address,direction='Incoming',message_type='text',content='Amount 1250',
                business_doctype='Supplier',business_name=supplier.name,provider_context=json.dumps(context),
                conversation_key=conversation_key(email_channel.name,address,context))).insert()
            email_ticket=tickets.ensure_episode(email_source,owner=actor.name);frappe.db.commit()
            stack.enter_context(patch.object(email,'connection_value',return_value=channel.account))
            def email_claim():
                connect();frappe.set_user(actor.name)
                try: tickets.claim(email_ticket.name);frappe.db.commit()
                finally:frappe.destroy()
            def prepared_claim(*args,**kwargs):
                result=original_prepare(*args,**kwargs)
                def after():
                    with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(email_claim).result(timeout=15)
                frappe.db.after_commit.add(after)
                return result
            original_prepare=email.prepare
            payload=dict(to=[address],subject='Amount review',body='Amount 1250 quantity 25',
                message=email_source.name,auto_submitted=1,request_key='sim-email-'+stamp)
            hub.reset_mock();hub.call_tool.side_effect=receipt
            with patch.object(email,'prepare',side_effect=prepared_claim):
                response=request('email.send',payload)
            assert response.status_code==200 and response.json['message']['status']=='Rejected', (response.status_code,response.json.get('exc_type'))
            assert set(response.json['message'])=={'action','status','message','error'}
            hub.call_tool.assert_not_called()
            assert request('email.send',payload,authenticated=False).status_code in (401,403)
            rejected=response.json['message']['action']
            retry=request('messaging.retry',{'action':rejected})
            assert retry.status_code==403 and retry.json['exc_type']=='PermissionError'
            actions=request('messaging.actions',{'contact':contact.name},verb='GET')
            assert actions.status_code==200
            item=next(item for item in actions.json['message']['items'] if item['name']==rejected)
            assert not item['can_retry'] and 'staff' in item['error']
            # Resume does not unlock a fixed-rule queue item whose inbound source
            # predates ownership, even when its first action is journaled later.
            resumed=request('tickets.resume_ai',{'name':email_ticket.name})
            assert resumed.status_code==200
            payload.update(request_key='sim-email-pending-'+stamp)
            response=request('email.send',payload)
            assert response.status_code==200 and response.json['message']['status']=='Rejected'
            hub.call_tool.assert_not_called()
            from relay_core import email_preferences
            raw('Relay Email Rule','Delivery Fixed Reply',channel=email_channel.name,enabled=1,
                execution_user=actor.name,subject='Amount review',body='Staff will check amount 1250')
            frappe.db.set_value('Relay Message',email_source.name,'email_reply_status','Pending')
            frappe.db.commit()
            result=email_preferences.auto_reply(email_source.name)
            assert result['status']=='Rejected'
            assert frappe.db.get_value('Relay Message',email_source.name,'email_reply_status')=='Complete'
            hub.call_tool.assert_not_called()
            # A manual reply is still admitted while the hold is active.
            assert request('tickets.claim',{'name':email_ticket.name}).status_code==200
            payload.update(auto_submitted=0,request_key='sim-email-staff-'+stamp)
            response=request('email.send',payload)
            assert response.status_code==200 and response.json['message']['status']=='Queued',response.status_code
            email_action=response.json['message']['action']
            stored=frappe.get_doc('Relay Message Action',email_action)
            assert json.loads(stored.payload)['ticket']==email_ticket.name
            hub.call_tool.side_effect=lambda tool,args: {'deliveries':[{'key':args['request_key'],'operation':'email.send',
                'state':'submitted','result':{'message_id':'<sim-outgoing-'+stamp+'@example.invalid>'}}]}
            response=request('messaging.reconcile',{'action':email_action})
            assert response.status_code==200 and response.json['message']['status']=='Submitted', response.status_code
            projected=frappe.get_doc('Relay Message',response.json['message']['message'])
            assert projected.ticket==email_ticket.name and projected.conversation_key==email_source.conversation_key
            transcript=request('tickets.transcript',{'name':email_ticket.name},verb='GET')
            assert transcript.status_code==200 and {row['direction'] for row in transcript.json['message']['items']}=={'Incoming','Outgoing'}
            print('PASS HTTP automatic email fence; manual email and delayed recovery preserve episode transcript; guest denied')

            # Fence helpers cannot be invoked through HTTP.
            for method in ('delivery_fence','delivery_snapshot','delivery_episodes','suppress_delivery'):
                assert request('messaging.'+method).status_code==403
            print('PASS internal delivery helpers denied over HTTP')
        finally:
            connect();frappe.db.rollback()
            for doctype,name in reversed(created):
                frappe.db.delete('__Auth',{'doctype':doctype,'name':name})
                frappe.db.delete(doctype,{'name':name})
            frappe.db.commit()
            assert all(not frappe.db.exists(dt,name) for dt,name in created)
            frappe.destroy()
            print('CLEANUP all inserted fixtures deleted, including Companies and ledger entries')


if __name__=='__main__':
    main()
