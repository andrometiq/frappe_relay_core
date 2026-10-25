"""Step 12 ticket UI/HTTP evidence on yrp.site; all fixtures are cleaned by the shared harness."""
import json
from pathlib import Path
from unittest.mock import patch
from integration_ai_actions_site import main


def exercise(*, stack, raw, actor, company, supplier, contact, event, source, request, stamp):
    import frappe
    from relay_core.automation import service
    # Admit via HTTP and run the actual ticket-only worker before adding durable
    # historical journal fixtures for the read projection (no provider calls).
    frappe.db.set_value('Relay AI Skill', event.name, dict(exact_trigger='/support', execution_policy='Ticket only'))
    message = source('/support')
    response = request('automation.service.enqueue', {'message':message.name})
    assert response.status_code == 200
    run = frappe.get_doc('Relay Automation Run', response.json['message']['name'])
    service.process(run.name); run.reload()
    assert run.ticket and run.status == 'Completed'
    ticket = frappe.get_doc('Relay Ticket', run.ticket)
    ticket.subject = 'Sim History Review '+stamp; ticket.save()
    raw_secret = 'Sim private accounting values must stay private'
    run.search_plan = json.dumps({'plan':{'reference':'supplier_ledger','purpose':'Check your October ledger',
        'arguments':{'filters':{'private':raw_secret}}},'confirmed_by':message.name})
    run.decision = json.dumps({'reads':[{'tool':'supplier_ledger','arguments':{'private':raw_secret},'digest':raw_secret}],
        'reason':raw_secret, 'reply':raw_secret})
    service.internal_save(run)
    draft = raw('Payment Entry','History Draft', company=company.name, party_type='Supplier', party=supplier.name,
        payment_type='Pay', paid_amount=1250, received_amount=1250, docstatus=0)
    completed = raw('Relay Flow Action','History Completed', automation_run=run.name, ticket=ticket.name,
        action_key='sim-history-completed-'+stamp, action='create_draft', step=0, status='Completed',
        target_doctype=draft.doctype, target_name=draft.name, input_snapshot=raw_secret, result=raw_secret)
    pending = raw('Relay Flow Action','History Approval', automation_run=run.name, ticket=ticket.name,
        action_key='sim-history-approval-'+stamp, action='reply', step=1, status='Approved', approval_evidence=raw_secret)
    delivery = raw('Relay Message Action','History Delivery', source_message=message.name,
        request_key='sim-history-delivery-'+stamp, operation='send', status='Uncertain', payload_hash='sim', target_channel=message.channel,
        payload=json.dumps({'automation_run':run.name,'private':raw_secret}), result=json.dumps({'private':raw_secret}))
    def get(method, **kwargs):
        response = request('tickets.'+method, dict(name=ticket.name,**kwargs), verb='GET')
        assert response.status_code == 200, (method,response.status_code,response.json.get('exc_type'))
        return response.json['message']
    flow_delivery = raw('Relay Message Action','History Flow Reply',source_message=message.name,
        target_channel=message.channel,request_key='sim-history-flow-'+stamp,operation='text',status='Queued',
        payload_hash='sim',payload=json.dumps({'flow_run':{'name':'Sim Flow'},'ticket':ticket.name}))
    notice = raw('Relay Business Event Delivery','History Suppressed Notice',event_key='sim-history-notice-'+stamp,
        source_doctype=draft.doctype,source_name=draft.name,business_doctype='Supplier',business_name=supplier.name,
        channel=message.channel,status='Suppressed',payload=json.dumps({'delivery_episodes':[[ticket.name,0]]}))
    sent = get('deliveries')
    assert set(sent)=={'items','next'}
    states={row['name']:row['status'] for row in sent['items']}
    assert states[flow_delivery.name]=='Queued' and states[notice.name]=='Suppressed' and states[delivery.name]=='Uncertain'
    first=get('deliveries',limit=1)
    assert first['next'] and len(first['items'])==1
    second=get('deliveries',limit=1,**first['next'])
    assert second['items'][0]['name']!=first['items'][0]['name']
    assert request('tickets.deliveries',{'name':ticket.name,'before':'Other Delivery'},verb='GET').status_code==403
    result = get('ai_history')
    assert set(result) == {'items','next'} and len(result['items']) == 1
    history = result['items'][0]
    assert history['event'] == event.title and history['read_count'] == 1 and history['search']['confirmed']
    assert [row['status'] for row in history['actions']] == ['Completed','Approved']
    assert history['deliveries'] == [{'name':delivery.name,'status':'Uncertain'}]
    assert raw_secret not in json.dumps(result)
    detail = get('read')
    assert detail['can_take_over'] and not detail['ai_disabled']
    assert detail['linked_drafts'] == [dict(doctype=draft.doctype,name=draft.name,docstatus=0)]
    transcript = get('transcript')
    assert transcript['items'][0]['content'] == '/support'
    assert set(transcript) == {'items','next'}
    for method in ('ai_history','transcript','read','deliveries'):
        response = request('tickets.'+method, {'name':ticket.name}, verb='GET',authenticated=False)
        assert response.status_code in (401,403) and response.json['exc_type']=='PermissionError'
    for method in ('ai_history','deliveries','_delivery_rows','_read_delivery'):
        assert request('tickets.'+method,{'name':ticket.name}).status_code == 403
    for limit in ('0','51','bad'):
        response = request('tickets.ai_history',dict(name=ticket.name,limit=limit),verb='GET')
        assert response.status_code == 417 and response.json['exc_type']=='ValidationError'
        if limit != '51':
            assert request('tickets.deliveries',dict(name=ticket.name,limit=limit),verb='GET').status_code==417
    # Cross-episode cursors fail even when the viewer has access to both records.
    from frappe.model.naming import make_autoname
    other_run = frappe.get_doc(dict(doctype='Relay Automation Run',name=make_autoname('RELAY-AR-.##########'),
        event_key='sim-history-other-'+stamp,message=message.name,execution_user=actor.name,ticket='Other Episode'))
    other_run.db_insert()
    response=request('tickets.ai_history',dict(name=ticket.name,before=other_run.name),verb='GET')
    assert response.status_code==403
    print('PASS HTTP history/read/transcript shape, sanitized evidence, draft scope, method/guest/limit/cursor denial')

    # Real permission hooks deny the entire ticket and transcript after a company restriction.
    other = raw('Company','History Other Company',company_name='Sim History Other Company '+stamp,
        abbr='SH',country='India',default_currency='INR')
    permission = frappe.get_doc(dict(doctype='User Permission',user=actor.name,allow='Company',
        for_value=other.name,apply_to_all_doctypes=1)).insert()
    frappe.clear_cache(user=actor.name)
    for method in ('read','transcript','ai_history','deliveries'):
        response=request('tickets.'+method,dict(name=ticket.name),verb='GET')
        assert response.status_code==403 and response.json['exc_type']=='PermissionError', (method,response.status_code)
    frappe.delete_doc('User Permission',permission.name);frappe.clear_cache(user=actor.name)
    print('PASS real cross-company ticket, transcript and history denial')

    # Load multiple real pages before Socket.IO invalidates the detail.
    for index in range(59):
        item=source('Sim history line '+str(index+1))
        frappe.db.set_value('Relay Message',item.name,'ticket',ticket.name)
    for index in range(20):
        older=frappe.get_doc(dict(doctype='Relay Automation Run',name=make_autoname('RELAY-AR-.##########'),
            event_key='sim-history-page-'+stamp+'-'+str(index),message=message.name,execution_user=actor.name,
            ticket=ticket.name,status='Completed',stage='Event'))
        older.db_insert()
    frappe.db.commit()
    # Built UI talks to the actual site APIs. Socket frames exercise the production
    # client; the external socket transport is isolated from the shared bench.
    browser_site(actor, event, ticket, draft)
    ticket.reload(); assert ticket.ai_disabled and ticket.ownership_actor==actor.name
    result=next(row for row in get('ai_history',limit=50)['items'] if row['name']==run.name)
    assert result['actions'][1]['status']=='Stopped' and result['actions'][1]['approval']=='Invalidated'
    assert result['actions'][0]['status']=='Completed'
    for doc in (run,completed,delivery):
        frappe.publish_realtime.reset_mock()
        service.internal_save(doc)
        frappe.publish_realtime.assert_any_call('relay_changed',{'kind':'tickets'},
            room=frappe.realtime.get_doctype_room('Relay Ticket'),after_commit=True)
    assert frappe.db.get_value('Payment Entry',draft.name,'docstatus') == 0
    print('PASS takeover invalidates approval, preserves completed draft; journal Socket.IO invalidations contain only kind')


def browser_site(actor, event, ticket, draft):
    import subprocess
    from threading import Thread
    from werkzeug.wrappers import Response
    from werkzeug.middleware.shared_data import SharedDataMiddleware
    from werkzeug.serving import make_server, WSGIRequestHandler
    import frappe
    import frappe.app
    from relay_core import settings
    root=Path(__file__).resolve().parents[1]
    auth='token '+actor.api_key+':'+actor.get_password('api_secret')
    account=frappe.db.get_value('Relay Channel',event.channel,'account')
    original=settings.value
    def application(environ,start_response):
        if environ.get('PATH_INFO') == '/site.html':
            html=(assets/'site.html').read_text().replace('id="app"','id="app" data-site="yrp.site"')
            return Response(html,content_type='text/html')(environ,start_response)
        environ['HTTP_X_FRAPPE_SITE_NAME']='yrp.site';environ['HTTP_AUTHORIZATION']=auth
        return frappe.app.application(environ,start_response)
    class QuietHandler(WSGIRequestHandler):
        def log(self,*args,**kwargs): pass
    assets=root/'relay_core/public/relay'
    app=SharedDataMiddleware(application,{'/assets/relay_core/relay':str(assets)})
    frappe.db.commit()
    with patch.object(settings,'value',side_effect=lambda key: account if key=='relay_hub_account' else original(key)):
        server=make_server('127.0.0.1',0,app,request_handler=QuietHandler,threaded=True)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            result=subprocess.run(['node',str(root/'frontend/tests/browser/ticketSimulation.mjs')],cwd=root,
                input=json.dumps(dict(origin='http://127.0.0.1:'+str(server.server_port),subject=ticket.subject,
                    event=event.title,draft=draft.name,actor=actor.name)),text=True,capture_output=True,timeout=90)
            assert result.returncode==0,result.stdout[-1000:]+result.stderr[-3000:]
            print(result.stdout.strip())
        finally:
            server.shutdown();thread.join(timeout=5);server.server_close()
    frappe.db.rollback()


if __name__=='__main__':
    main(exercise)
