"""Step 11 HTTP authoring/preview with real scoped fixtures and no external effects."""
import json
from unittest.mock import patch
from integration_ai_actions_site import main


def exercise(*, stack, raw, actor, company, supplier, contact, event, source, request, stamp):
    import frappe
    from relay_core.ai import adapter
    from relay_core.ai.actions import PAYMENT_SCHEMA
    actor.append('roles', {'role':'System Manager'}); actor.save()
    # Test configuration is saved through the same endpoint used by the editor.
    frappe.db.set_value('Relay AI Skill', event.name, dict(enabled=0, exact_trigger='/ledger', execution_policy='Execute'))
    prefix='ai.configuration.'
    def options(kind, **values):
        response=request(prefix+'editor_options',dict(kind=kind,**values),verb='GET')
        assert response.status_code==200, (kind,response.status_code,response.json.get('exc_type'))
        assert set(response.json['message'])=={'items'}
        return response.json['message']['items']
    def keys(kind, **values): return {row['value'] for row in options(kind,**values)}
    assert 'Supplier' in keys('doctype',query='Supplier')
    assert 'User' not in keys('doctype',query='User')
    assert 'alias' in keys('identity',doctype='Supplier')
    assert 'company' in keys('company',doctype='GL Entry')
    assert 'party' in keys('scope',doctype='GL Entry',business_doctype='Supplier')
    assert 'debit' in keys('field',doctype='GL Entry',query='Debit')
    assert keys('draft_doctype',action='create_draft')=={'Payment Entry'}
    fields=options('draft_field',action='create_draft',doctype='Payment Entry')
    required={row['value'] for row in fields if row['required']}
    assert required==set(PAYMENT_SCHEMA['required'])
    assert {'docstatus','owner','company','party'}.isdisjoint({row['value'] for row in fields})
    assert all(row['description'] in ('string','number') for row in fields)
    assert keys('action')=={'create_draft','reply'}
    assert options('user',selected=json.dumps([actor.name]))[0]['label'].startswith('Sim Action Operator')
    for kind in ('doctype','field','identity','company','scope','draft_doctype','draft_field','action','user','model','message'):
        response=request(prefix+'editor_options',dict(kind=kind),authenticated=False,verb='GET')
        assert response.status_code in (401,403) and response.json['exc_type']=='PermissionError'
    assert request(prefix+'editor_options',{'kind':'field','doctype':'User'},verb='GET').status_code==500
    assert request(prefix+'editor_options',{'kind':'doctype'}).status_code==403
    print('PASS HTTP readable metadata shape, identity/company/business constraints, typed registered drafts and guest/method denial')

    allowed=[dict(action='create_draft',doctype='Payment Entry',fields=list(PAYMENT_SCHEMA['required'])),dict(action='reply')]
    response=request(prefix+'save', {'name':event.name,'values':json.dumps(dict(target='Review payment evidence',
        reply_style='Brief and precise',allowed_actions=json.dumps(allowed)))})
    assert response.status_code==200 and response.json['message']=={'name':event.name}
    assert json.loads(frappe.get_doc('Relay AI Skill',event.name).allowed_actions)==allowed
    for values in ({'allowed_actions':'[{"action":"submit"}]'}, {'execution_policy':'Ticket only'},
                   {'allowed_actions':json.dumps([dict(action='create_draft',doctype='Payment Entry',fields=['paid_amount'])])}):
        response=request(prefix+'save',{'name':event.name,'values':json.dumps(values)})
        assert response.status_code==500 and response.json['exc_type']=='ValueError'
    assert json.loads(frappe.get_doc('Relay AI Skill',event.name).allowed_actions)==allowed
    print('PASS HTTP event save preserves text and ordered actions; ticket-only, submit and missing required fields denied')

    message=source('/ledger')
    assert options('message',skill=event.name,selected=json.dumps([message.name]))==[{'value':message.name,'label':'/ledger'}]
    monitored=('Relay Ticket','Relay Flow Action','Payment Entry','Relay Message','Relay Automation Run')
    before={dt:frappe.db.count(dt) for dt in monitored}
    plan=dict(purpose='Review your October ledger',reference='supplier_ledger',fields=['debit','credit'],
              arguments={'filters':{'posting_date':['between',['2026-10-01','2026-10-31']]}})
    # Only inference is replaced. Identity, permissions, matching, preview orchestration,
    # metadata, save validation and real HTTP dispatch all execute from the worktree.
    with patch.object(adapter,'complete',return_value=dict(reply='Shall I check October?',handoff=False,reason='',search=plan,reads=[])) as model:
        response=request(prefix+'test_skill',{'name':event.name,'message':message.name})
        assert response.status_code==200, ('preview',response.status_code)
        result=response.json['message']
        assert result['mode']=='Shadow' and result['search']==plan and result['identity_scope']['company']==company.name
        assert result['match']['selected']==event.title and result['match']['method']=='exact'
        assert model.call_count==1
        proposals=[dict(action='create_draft',parameters={'paid_amount':1250}),dict(action='reply',parameters={'text':'Received payment evidence'})]
        model.return_value=dict(reply='',handoff=False,reason='',actions=proposals,reads=[])
        response=request(prefix+'test_skill',{'name':event.name,'message':message.name})
        assert response.status_code==200 and response.json['message']['actions']==proposals
        frappe.db.set_value('Relay AI Skill',event.name,dict(execution_policy='Ticket only',allowed_actions='[]'))
        response=request(prefix+'test_skill',{'name':event.name,'message':message.name})
        assert response.status_code==200 and response.json['message']['actions']==[] and model.call_count==2
        assert response.json['message']['reason']=='Would raise the episode ticket only'
        frappe.db.set_value('Relay Message',message.name,'sender_endpoint','unverified')
        response=request(prefix+'test_skill',{'name':event.name,'message':message.name})
        assert response.status_code==200 and response.json['message']['identity_scope'] is None
        assert model.call_count==2
    assert {dt:frappe.db.count(dt) for dt in monitored}==before
    for authenticated in (False,):
        response=request(prefix+'test_skill',{'name':event.name,'message':message.name},authenticated=authenticated)
        assert response.status_code in (401,403)
    assert request(prefix+'test_skill',{'name':event.name,'message':message.name},verb='GET').status_code==403
    frappe.db.set_value('Relay Message',message.name,'sender_endpoint',json.loads(message.provider_context)['participant_id'])
    browser_site(actor, event, company)
    assert {dt:frappe.db.count(dt) for dt in monitored}==before
    account=raw('AI Provider Account','Editor Provider',account_name='Sim Editor Provider '+stamp,
                provider='OpenRouter',auth_type='API Key',enabled=1)
    model=raw('AI Model','Editor Model',model_label='Sim Editor Model '+stamp,account=account.name,
              provider='OpenRouter',model_id='sim-no-network',enabled=1)
    response=request(prefix+'save',{'name':event.name,'values':json.dumps(dict(enabled=1,mode='Shadow',
        ai_model=model.name,execution_policy='Execute',allowed_actions='[{"action":"reply"}]',
        exact_trigger='Sim Shadow payment INR 1250'))})
    assert response.status_code==200, ('shadow activation',response.status_code)
    shadow_source=source('Sim Shadow payment INR 1250')
    from relay_core.automation import service
    proposal=dict(reply='',handoff=False,reason='',reads=[],user=actor.name,
                  actions=[dict(action='reply',parameters={'text':'Payment evidence received'})])
    with patch.object(adapter,'complete',return_value=proposal):
        response=request('automation.service.enqueue',{'message':shadow_source.name})
        assert response.status_code==200
        service.process(response.json['message']['name'])
        run=frappe.get_doc('Relay Automation Run',response.json['message']['name'])
        assert run.status=='Shadow' and run.ticket, (run.status,run.reason)
        assert json.loads(run.decision)['actions']==proposal['actions']
    assert not frappe.db.exists('Relay Flow Action',{'automation_run':run.name})
    assert frappe.db.count('Payment Entry')==before['Payment Entry']
    assert frappe.db.count('Relay Message')==before['Relay Message']+1
    print('PASS enabled Shadow event through real HTTP admission and worker: ticket and proposals, no draft or outbound message')
    from frappe_tools.ai import agent
    from types import SimpleNamespace
    reply_style='Use short Tamil sentences with the amount first.'
    response=request(prefix+'save',{'name':event.name,'values':json.dumps(dict(mode='Automatic',reply_style=reply_style))})
    assert response.status_code==200
    prompts=[]
    def inference(account, model_id, supplied, options, context):
        prompts.append(supplied[0])
        assert reply_style in supplied[0] and 'Owner reply style:' in supplied[0]
        return {'ok':True,'result':{'data':dict(reply='',handoff=True,reason='Staff review requested'),'tool_calls':[]}}
    with patch.object(adapter,'route',return_value=(None,SimpleNamespace(model_id='sim-no-network'),[],{'max_tokens':1200})), \
            patch.object(agent.AgentRun,'run_route',side_effect=inference):
        response=request(prefix+'test_skill',{'name':event.name,'message':shadow_source.name})
        assert response.status_code==200 and response.json['message']['handoff']
        # Shadow's conservative hold must be explicitly resumed for new live work.
        assert request('tickets.resume_ai',{'name':run.ticket}).status_code==200
        live_source=source('Sim Shadow payment INR 1250')
        response=request('automation.service.enqueue',{'message':live_source.name})
        assert response.status_code==200
        service.process(response.json['message']['name'])
        live=frappe.get_doc('Relay Automation Run',response.json['message']['name'])
        assert live.status=='Handoff', (live.status,live.reason)
    assert len(prompts)==2
    print('PASS saved reply style reaches trusted model prompt through HTTP preview and live event worker')
    actor.roles=[row for row in actor.roles if row.role!='System Manager']; actor.save()
    for method, values, verb in [('editor_options',{'kind':'doctype'},'GET'),('test_skill',{'name':event.name,'message':message.name},'POST'),('save',{'name':event.name,'values':'{}'},'POST')]:
        response=request(prefix+method,values,verb=verb)
        assert response.status_code==403 and response.json['exc_type']=='PermissionError'
    print('PASS HTTP non-sending preview: authenticated scope, match, search, ordered proposals, Ticket only, identity denial; zero operational writes')
    print('PASS HTTP staff/guest and GET preview denial')


def browser_site(actor, event, company):
    """Serve only this worktree's built assets and actual local-site HTTP APIs."""
    import subprocess
    from pathlib import Path
    from threading import Thread
    from werkzeug.middleware.shared_data import SharedDataMiddleware
    from werkzeug.serving import make_server, WSGIRequestHandler
    import frappe
    import frappe.app
    from relay_core import settings
    root=Path(__file__).resolve().parents[1]
    if not (root/'.runtime/browser/node_modules/playwright').exists():
        raise AssertionError('Install the local browser runner before site acceptance')
    auth='token '+actor.api_key+':'+actor.get_password('api_secret')
    account=frappe.db.get_value('Relay Channel',event.channel,'account')
    original_value=settings.value
    def local_value(key):
        return account if key=='relay_hub_account' else original_value(key)
    def application(environ,start_response):
        environ['HTTP_X_FRAPPE_SITE_NAME']='yrp.site'
        environ['HTTP_AUTHORIZATION']=auth
        return frappe.app.application(environ,start_response)
    class QuietHandler(WSGIRequestHandler):
        def log(self,*args,**kwargs): pass
    assets=root/'relay_core/public/relay'
    app=SharedDataMiddleware(application,{'/site.html':str(assets/'site.html'),'/assets/relay_core/relay':str(assets)})
    frappe.db.commit()
    with patch.object(settings,'value',side_effect=local_value):
        server=make_server('127.0.0.1',0,app,request_handler=QuietHandler)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            result=subprocess.run(['node',str(root/'frontend/tests/browser/eventEditorSite.mjs')],cwd=root,
                input=json.dumps(dict(origin='http://127.0.0.1:'+str(server.server_port),title=event.title,company=company.name)),
                text=True,capture_output=True,timeout=90)
            assert result.returncode==0, result.stderr[-3000:]
            print(result.stdout.strip())
        finally:
            server.shutdown();thread.join(timeout=5);server.server_close()
    frappe.db.rollback()


if __name__=='__main__':
    main(exercise)
