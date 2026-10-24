"""Backend review acceptance on yrp.site, with local records and mocked delivery."""
import json
import os
from pathlib import Path
import secrets
import threading
import time
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler


def main():
    from integration_ai_permissions_site import confine_writes
    import sys
    sys.addaudithook(confine_writes)
    os.environ['FRAPPE_STREAM_LOGGING']='1'
    import frappe
    import frappe.app
    import requests
    from channel_site_fixtures import init, user
    from channel_identity_fixtures import scenario, configured, endpoint
    from relay_core import cases, collaboration, topics, messaging, business_groups, delivery, permissions
    from relay_core.automation import service as automation
    from relay_core.flows import service as flows
    init()
    assert frappe.local.site=='yrp.site'
    f=scenario()
    system=user('relay-be-system-'+f.stamp+'@example.invalid',manager=True)
    frappe.get_doc('User',system).add_roles('System Manager')
    for row in frappe.get_all('User Permission',filters={'user':f.actor},fields=['allow','for_value']):
        frappe.get_doc(dict(doctype='User Permission',user=system,allow=row.allow,for_value=row.for_value,apply_to_all_doctypes=1)).insert()
    unassigned=user('relay-be-unassigned-'+f.stamp+'@example.invalid')
    credentials={}
    for actor in (f.actor,system,unassigned):
        key, secret=secrets.token_hex(12),secrets.token_hex(24)
        doc=frappe.get_doc('User',actor);doc.api_key=key;doc.api_secret=secret;doc.save()
        credentials[actor]={'Authorization':'token '+key+':'+secret}
    account=frappe.get_doc(dict(doctype='AI Provider Account',name='Local backend account '+f.stamp,
        account_label='Local backend account '+f.stamp,provider='OpenRouter',enabled=1));account.db_insert()
    model=frappe.get_doc(dict(doctype='AI Model',name='Local backend model '+f.stamp,model_label='Local backend model '+f.stamp,
        account=account.name,provider='OpenRouter',model_id='local-no-network',enabled=1));model.db_insert()
    sources={}; tickets={}; case_rows={}; notes={}; runs={}; topic_rows={}
    schema={'fields':{'type':'object','properties':{'quantity':{'type':'number'}}},'initial_stage':'open',
            'stages':[{'key':'open','label':'Open','state':'open'},{'key':'done','label':'Done','state':'done'}]}
    kind=frappe.get_doc(dict(doctype='Relay Case Type',type_key='local.be.'+f.stamp,title='Local backend cases '+f.stamp,enabled=1,definition=json.dumps(schema))).insert()
    sender='919555'+f.stamp[-7:]
    endpoint(f,'WhatsApp',sender)
    flow=frappe.get_doc(dict(doctype='Relay Flow',title='Local backend flow '+f.stamp,command='/be'+f.stamp[-12:],
                           channel=f.channels['WhatsApp'].name,business_doctype='Customer',execution_user=f.actor,
                           enabled=0,nodes=json.dumps([{'id':'end','kind':'end','text':'Done'}]))).insert()
    version=frappe.get_doc(dict(doctype='Relay Flow Version',flow=flow.name,channel=flow.channel,business_doctype='Customer',
                              execution_user=f.actor,nodes=flow.nodes,definition_hash=flows.digest(flow.nodes)))
    automation.internal_save(version,new=True)
    for business in (f.customer,f.supplier):
        source=frappe.get_doc(dict(doctype='Relay Message',relay_contact=f.contact.name,channel=f.channels['WhatsApp'].name,
            sender_endpoint=sender,direction='Incoming',content=business.doctype+' PRIVATE quantity 25 amount 1250',message_type='text',
            provider_id='local-be-'+business.doctype+f.stamp,provider_context=json.dumps({'provider':'WhatsApp','message_id':'local-be-'+business.doctype+f.stamp}),
            business_doctype=business.doctype,business_name=business.name)).insert()
        sources[business.doctype]=source
        ticket=frappe.get_doc(dict(doctype='Relay Ticket',subject='Local backend '+business.doctype,brief=source.content,
            category='Support',status='Open',assigned_to='Administrator',business_doctype=business.doctype,business_name=business.name,
            messages=[{'message':source.name}])).insert()
        tickets[business.doctype]=ticket
        case_rows[business.doctype]=cases.create_manual(kind.name,f.contact.name,'Local case '+business.doctype,
            {'quantity':25},'case-'+business.doctype+f.stamp,business.doctype,business.name)
        notes[business.doctype]=collaboration.add(f.contact.name,source.content,'note-'+business.doctype+f.stamp,
            messages=[source.name],business_doctype=business.doctype,business_name=business.name)
        topic_rows[business.doctype]=topics.save(f.contact.name,dict(title='Local '+business.doctype,summary=source.content,
            messages=[source.name],business_doctype=business.doctype,business_name=business.name),request_key='topic-'+business.doctype+f.stamp)
        run=frappe.get_doc(dict(doctype='Relay Flow Run',flow=flow.name,version=version.name,relay_contact=f.contact.name,
            start_message=source.name,last_message=source.name,conversation_key='local-be-'+business.doctype+f.stamp,
            business_doctype=business.doctype,business_name=business.name,status='Waiting',values='{"quantity":25}',step=0,generation=0))
        automation.internal_save(run,new=True);runs[business.doctype]=run
    # Historical owner/assignee access must still honor later business revocation.
    frappe.db.set_value('Relay Ticket',tickets['Supplier'].name,{'owner':f.actor,'assigned_to':f.actor})
    from relay_core import summaries
    summary=frappe.get_doc(dict(doctype='Relay Conversation Summary',name='LOCAL-BE-SUMMARY-'+f.stamp,
        relay_contact=f.contact.name,business_doctype='Customer',business_name=f.customer.name,channel=f.channels['WhatsApp'].name,
        status='Ready',sources=json.dumps([sources['Customer'].name]),result=json.dumps({'overview':'PRIVATE summary amount 4500'})))
    summary.input_hash=summaries.digest(summaries.existing_sources(summary));summary.db_insert()
    auxiliary=[]
    for dt,values in [('Relay Automation Outbox',{'payload':'{"amount":4500}','run':'local-old-run'}),
                      ('Relay Message Translation',{'result':'{"text":"PRIVATE Supplier"}','message':sources['Supplier'].name})]:
        doc=frappe.get_doc(dict(doctype=dt,name='LOCAL-BE-'+dt.replace(' ','-')+'-'+f.stamp,**values));doc.db_insert();auxiliary.append(doc)
    notification=frappe.get_doc(dict(doctype='Relay Notification',name='RELAY-NOTIFY-'+f.stamp[-10:],user=f.actor,
        relay_contact=f.contact.name,comment=notes['Supplier']['name'],kind='Mention',event_key='local-be-'+f.stamp));notification.db_insert()
    # Framework insert validates and stores full email identities.
    long_id='<'+('a'*120)+'@'+('b'*120)+'>'
    address='a'*64+'@'+'b'*63+'.'+'c'*63+'.invalid'
    assert len(address)<=200 and len(address)>140
    endpoint(f,'Email',address)
    long_message=frappe.get_doc(dict(doctype='Relay Message',relay_contact=f.contact.name,channel=f.channels['Email'].name,
        sender_endpoint=address,provider_id=long_id,direction='Incoming',content='Local long ID quantity 25',
        business_doctype='Customer',business_name=f.customer.name)).insert()
    long_message.reload();assert long_message.provider_id==long_id and long_message.sender_endpoint==address
    # Supplier-only contact must disappear even for managers.
    person=frappe.get_doc(dict(doctype='Contact',first_name='Local hidden backend '+f.stamp,
        links=[dict(link_doctype='Supplier',link_name=f.supplier.name)])).insert()
    hidden=frappe.get_doc(dict(doctype='Relay Contact',contact=person.name,display_name='Local hidden backend '+f.stamp)).insert()
    group=endpoint(f,'Telegram','-'+f.stamp[-12:],contact=hidden.name)
    shared_group=endpoint(f,'Telegram','-8'+f.stamp[-12:])
    frappe.db.commit()
    server=None
    class Quiet(WSGIRequestHandler):
        def log_message(self,*args): pass
    def application(environ,start_response):
        environ['HTTP_X_FRAPPE_SITE_NAME']='yrp.site';environ['HTTP_HOST']='127.0.0.1:8001'
        return frappe.app.application(environ,start_response)
    def call(path,values=None,*,actor=f.actor,write=False,status=200):
        response=requests.request('POST' if write else 'GET',base+path,headers=credentials[actor],
            **({'json':values or {}} if write else {'params':values or {}}),timeout=30)
        payload=response.json()
        assert response.status_code==status,(path,response.status_code,payload.get('exc_type'))
        if status==200:
            assert 'message' in payload or 'data' in payload,(path,payload.keys())
            return payload.get('message',payload.get('data'))
        assert payload.get('exc_type')=='PermissionError',(path,payload.get('exc_type'))
    def rpc(name,values=None,**kw):return call('/api/method/relay_core.'+name,values,**kw)
    try:
        os.environ['SITES_PATH']=os.environ['RELAY_AUTOMATION_TEST_SITES']
        with configured(f), patch('relay_core.telegram.client') as hub:
            server=make_server('127.0.0.1',0,application,handler_class=Quiet)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            base=f'http://127.0.0.1:{server.server_port}'
            for actor in (f.actor,system):
                own=call('/api/resource/Relay Ticket/'+tickets['Customer'].name,actor=actor)
                assert own['brief']==sources['Customer'].content
                call('/api/resource/Relay Ticket/'+tickets['Supplier'].name,actor=actor,status=403)
                rows=call('/api/resource/Relay Ticket',{'filters':json.dumps({'name':['in',[t.name for t in tickets.values()]]})},actor=actor)
                assert [r['name'] for r in rows]==[tickets['Customer'].name]
                for dt,name in [('Relay Flow Run',runs['Supplier'].name),('Relay Internal Comment',notes['Supplier']['name']),
                                ('Relay Conversation Summary',summary.name),*[(doc.doctype,doc.name) for doc in auxiliary]]:
                    call('/api/resource/'+dt+'/'+name,actor=actor,status=403)
                for name,values,write in [
                    ('flows.service.responses',{'name':runs['Supplier'].name},False),('flows.service.cancel',{'name':runs['Supplier'].name},True),
                    ('cases.read',{'name':case_rows['Supplier']['name']},False),
                    ('cases.move',{'name':case_rows['Supplier']['name'],'stage':'done','values':{},'modified':str(case_rows['Supplier']['modified'])},True),
                    ('cases.assign',{'name':case_rows['Supplier']['name'],'user':actor,'modified':str(case_rows['Supplier']['modified'])},True),
                    ('cases.agents',{'name':case_rows['Supplier']['name']},False),
                    ('collaboration.edit',{'name':notes['Supplier']['name'],'body':'unauthorized'},True),
                    ('collaboration.task_status',{'name':notes['Supplier']['name'],'status':'Done'},True),
                    ('topics.save',{'contact':f.contact.name,'name':topic_rows['Supplier']['name'],
                        'values':{'title':'Unauthorized','business_doctype':'Customer','business_name':f.customer.name}},True),
                    ('automation.service.takeover',{'contact':hidden.name},True),
                    ('delivery.page',{},True),('delivery.resolve',{'delivery_id':'1','outcome':'rejected','note':'Local verified evidence'},True),
                    ('whatsapp.deliveries',{},True),('telegram.groups',{'operation':'members.ban','arguments':{'chat_id':int(group.endpoint),'user_id':25}},True),
                    ('telegram.execute',{'operation':'count','arguments':{'chat_id':int(group.endpoint)}},True)]:
                    rpc(name,values,actor=actor,write=write,status=403)
            for operation, args in [('topics.delete',{'message_thread_id':25}),('members.ban',{'user_id':25}),('count',{})]:
                rpc('telegram.groups',{'operation':operation,'arguments':dict(chat_id=int(shared_group.endpoint),**args)},write=True,status=403)
            hub.assert_not_called()
            with patch('relay_core.ai.adapter.complete_json',return_value={'title':'Local draft','command':'/localdraft','nodes':[{'id':'end','kind':'end','text':'Done'}]}):
                discovered=rpc('flows.service.providers',{'query':'local-no-network'},actor=system)
                assert model.name in [row['name'] for row in discovered['items']]
                draft=rpc('flows.authoring.draft',{'requirement':'Collect a local quantity then finish','provider':model.name},actor=system,write=True)
                assert draft['command']=='/localdraft'
            rpc('flows.service.providers',{},status=403)
            assert [r['name'] for r in rpc('flows.service.runs',{'flow':flow.name})['items']]==[runs['Customer'].name]
            assert rpc('flows.service.responses',{'name':runs['Customer'].name})['status']=='Waiting'
            assert rpc('flows.service.cancel',{'name':runs['Customer'].name},write=True)['status']=='Cancelled'
            assert [r['name'] for r in rpc('cases.directory',{'contact':f.contact.name})['items']]==[case_rows['Customer']['name']]
            assert len(rpc('cases.workspace',{'query':'Local case'})['items'])>=1
            created=rpc('cases.create_manual',dict(case_type=kind.name,contact=f.contact.name,title='Local HTTP case',
                field_values={'quantity':27},request_key='http-case-'+f.stamp,business_doctype='Customer',business_name=f.customer.name),write=True)
            assert created['business_name']==f.customer.name and created['field_values']['quantity']==27
            rpc('cases.create_manual',dict(case_type=kind.name,contact=f.contact.name,title='Denied HTTP case',field_values={'quantity':27},
                request_key='http-deny-'+f.stamp,business_doctype='Supplier',business_name=f.supplier.name),write=True,status=403)
            moved=rpc('cases.move',dict(name=case_rows['Customer']['name'],stage='done',values={'quantity':26},modified=str(case_rows['Customer']['modified'])),write=True)
            assert moved['state']=='done' and moved['field_values']['quantity']==26
            assert [r['name'] for r in rpc('collaboration.comments',{'contact':f.contact.name})['items']]==[notes['Customer']['name']]
            assert [r['name'] for r in rpc('topics.directory',{'contact':f.contact.name})['items']]==[topic_rows['Customer']['name']]
            assert hidden.name not in {r['name'] for r in rpc('api.contacts')['items']}
            assert rpc('collaboration.edit',{'name':notes['Customer']['name'],'body':'Updated local quantity 26'},write=True)['body']=='Updated local quantity 26'
            restricted=rpc('business_groups.records',{'doctype':'Customer','query':f.customer.name},actor=unassigned)['items']
            assert restricted and all(not row.get('last_message') and not row.get('summary') and not row.get('unread') for row in restricted)
            assert not rpc('collaboration.notifications')['items']
            note=rpc('collaboration.add',dict(contact=f.contact.name,body='Local HTTP task quantity 25',request_key='note-http-'+f.stamp,
                assigned_to=f.actor,business_doctype='Customer',business_name=f.customer.name),write=True)
            reply=rpc('collaboration.add',dict(contact=f.contact.name,body='Local reply without selected messages',
                request_key='note-reply-'+f.stamp,reply_to=note['name']),write=True)
            assert reply['reply_to']==note['name']
            assert rpc('collaboration.task_status',{'name':note['name'],'status':'Done'},write=True)['task_status']=='Done'
            rpc('collaboration.add',dict(contact=f.contact.name,body='Denied HTTP note',request_key='note-deny-'+f.stamp,
                business_doctype='Supplier',business_name=f.supplier.name),write=True,status=403)
            topic=rpc('topics.save',dict(contact=f.contact.name,request_key='topic-http-'+f.stamp,
                values={'title':'Local HTTP topic','summary':'Quantity 25','business_doctype':'Customer','business_name':f.customer.name}),write=True)
            assert topic['summary']=='Quantity 25' and topic['message_count']==0
            rpc('topics.save',dict(contact=f.contact.name,request_key='topic-deny-'+f.stamp,
                values={'title':'Denied topic','business_doctype':'Supplier','business_name':f.supplier.name}),write=True,status=403)
            assert f.actor in [row['name'] for row in rpc('cases.agents',{'name':created['name'],'query':f.actor})]
            assigned=rpc('cases.assign',dict(name=created['name'],user=f.actor,modified=str(created['modified'])),write=True)
            assert assigned['assigned_to']==f.actor and rpc('cases.read',{'name':created['name']})['field_values']['quantity']==27
            # DocShare remains present while business permission is revoked.
            from frappe.share import add as share
            from channel_site_fixtures import business
            frappe.set_user('Administrator')
            share('Relay Contact',f.contact.name,f.actor,read=1)
            other=business('Revoked contact '+f.stamp)
            permission=frappe.get_doc('User Permission',{'user':f.actor,'allow':'Customer'})
            permission.for_value=other.name;permission.save();frappe.db.commit();frappe.clear_cache(user=f.actor)
            rpc('automation.service.takeover',{'contact':f.contact.name},write=True,status=403)
            assert not permissions.can_read_contact_as(f.contact.name,f.actor)
            assert f.contact.name not in {row['name'] for row in rpc('api.contacts')['items']}
            assert frappe.db.exists('DocShare',{'share_doctype':'Relay Contact','share_name':f.contact.name,'user':f.actor,'read':1})
            permission.for_value=f.customer.name;permission.save();frappe.db.commit();frappe.clear_cache(user=f.actor)
            print('PASS HTTP native ticket scope; flow/case/note/group/delivery/takeover 403 and happy-path response shapes')
        frappe.set_user(f.actor)
        assert not permissions.contact_permission(hidden)
        assert not frappe.get_list('Relay Contact',filters={'name':hidden.name})
        try: collaboration.recipients(f.contact.name,[f.actor],frappe.get_doc('Relay Internal Comment',notes['Supplier']['name']))
        except frappe.PermissionError:pass
        else:raise AssertionError('Supplier notification recipient was accepted')
        frappe.set_user('Administrator')
        with configured(f): runtime_cases(f, flow, sender)
        concurrent_skills(f, model)
        legacy_ledger(f)
        print('PASS native contact discovery and cross-business notification recipient deny; long identifiers inserted intact')
    finally:
        if server:server.shutdown();server.server_close()
        frappe.db.rollback();frappe.destroy()


def runtime_cases(f, flow, sender):
    import frappe
    from channel_identity_fixtures import endpoint, email_raw
    from relay_core import messaging, whatsapp, email_preferences
    from relay_core.automation import queue, service as automation
    from relay_core.flows import service as flows
    from relay_core.automation.provenance import conversation_key
    from relay_core.message_updates import provider_key
    flow.nodes=json.dumps([{'id':'quantity','kind':'input','input_type':'number','variable':'quantity','text':'Enter quantity'},
                           {'id':'handoff','kind':'handoff','text':'A person will help with {{quantity}}'}])
    flow.save();flows.publish(flow.name);flow.reload();flow.enabled=1;flow.save();frappe.db.commit()
    def source(text, provider='WhatsApp', address=sender):
        identifier='local-be-runtime-'+str(time.time_ns())
        context={'provider':provider,'message_id':identifier}
        if provider=='Email':
            identifier='<'+identifier+'@example.invalid>'
            context=dict(email_raw(identifier),provider='Email',subject='Local quantity 25')
        doc=frappe.get_doc(dict(doctype='Relay Message',relay_contact=f.contact.name,channel=f.channels[provider].name,
            direction='Incoming',message_type='text',status='Delivered',content=text,sender_endpoint=address,
            business_doctype='Customer',business_name=f.customer.name,provider_id=identifier,
            provider_context=json.dumps(context),provider_message_key=provider_key(f.channels[provider].name,address,identifier),
            conversation_key=conversation_key(f.channels[provider].name,address,context))).insert()
        frappe.db.commit();return doc
    first=source(flow.command);second=source('25')
    for doc in (first,second):queue._process(doc.name);frappe.db.commit()
    events=[frappe.db.get_value('Relay Flow Event',{'message':doc.name},'name') for doc in (first,second)]
    assert all(events) and not frappe.db.exists('Relay Automation Run',{'message':second.name})
    with patch.object(whatsapp,'client') as client:
        client.return_value.call_tool.side_effect=lambda *args: {'messages':[{'id':'local-be-sent-'+str(time.time_ns())}]}
        flows.process(events[0]);flows.process(events[1]);flows.process(events[1])
        run=frappe.get_doc('Relay Flow Run',frappe.db.get_value('Relay Flow Event',events[0],'run'))
        assert run.status=='Handoff',(run.status,run.reason)
        rows=frappe.get_all('Relay Ticket',filters={'source_action_key':flows.digest('flow-'+run.name+'-handoff')},fields=['assigned_to','business_doctype','business_name'])
        assert len(rows)==1 and rows[0].assigned_to==f.actor and rows[0].business_name==f.customer.name
        assert frappe.db.get_value('Relay Contact',f.contact.name,'automation_paused')==1
        automation.takeover(f.contact.name,0);frappe.db.commit()
        trigger=source(flow.command);queue._process(trigger.name);frappe.db.commit()
        event=frappe.db.get_value('Relay Flow Event',{'message':trigger.name},'name')
        client.return_value.call_tool.side_effect=SystemExit('Local crash before provider admission')
        try:flows.process(event)
        except SystemExit:pass
        else:raise AssertionError('Crash boundary not exercised')
        action=frappe.get_doc('Relay Message Action',{'source_message':trigger.name})
        pending=frappe.db.get_value('Relay Flow Event',event,'run')
        flows.cancel(pending)
        client.return_value.call_tool.side_effect=None
        client.return_value.call_tool.return_value={'deliveries':[]}
        assert messaging.reconcile(action.name)['status']=='Rejected'
        assert all(c.args[0]=='whatsapp.deliveries' for c in client.return_value.call_tool.call_args_list[-1:])
    frappe.set_user('Administrator')
    flow.nodes=json.dumps([{'id':'wait','kind':'wait','text':'','seconds':86400},
                           {'id':'handoff','kind':'handoff','text':'A person will help'}])
    flow.save();flows.publish(flow.name);flow.reload();frappe.db.commit()
    closed_sender='91888'+f.stamp[-9:];endpoint(f,'WhatsApp',closed_sender)
    trigger=source(flow.command,address=closed_sender);queue._process(trigger.name);frappe.db.commit()
    event=frappe.db.get_value('Relay Flow Event',{'message':trigger.name},'name')
    flows.process(event)
    old=frappe.utils.add_to_date(frappe.utils.now_datetime(),hours=-25)
    frappe.db.set_value('Relay Message',trigger.name,{'creation':old,'sent_at':old},update_modified=False)
    frappe.db.set_value('Relay Flow Event',event,'next_attempt',old);frappe.db.commit()
    with patch.object(whatsapp,'client') as client:
        flows.process(event);flows.process(event)
        client.assert_not_called()
    run=frappe.get_doc('Relay Flow Run',frappe.db.get_value('Relay Flow Event',event,'run'))
    assert run.status=='Handoff'
    rows=frappe.get_all('Relay Ticket',filters={'source_action_key':flows.digest('flow-'+run.name+'-handoff')},fields=['assigned_to','business_name'])
    assert len(rows)==1 and rows[0].assigned_to==f.actor and rows[0].business_name==f.customer.name
    assert frappe.db.get_value('Relay Contact',f.contact.name,'automation_paused')==1
    assert not frappe.db.exists('Relay Message Action',{'source_message':trigger.name})
    print('PASS burst flow input, assigned business handoff replay, and cancelled-flow journal recovery')
    frappe.set_user('Administrator')
    address='local-be-auto-'+f.stamp+'@example.invalid';endpoint(f,'Email',address)
    rule=frappe.get_doc(dict(doctype='Relay Email Rule',channel=f.channels['Email'].name,execution_user=f.actor,
        enabled=1,subject='Local acknowledgement',body='We received quantity 25')).insert();frappe.db.commit()
    message=source('Local fixed acknowledgement',provider='Email',address=address)
    queue._process(message.name);frappe.db.commit()
    assert frappe.db.get_value('Relay Message',message.name,'email_reply_status')=='Pending'
    with patch.object(frappe,'enqueue') as enqueue:
        email_preferences.recover()
        assert any(c.kwargs.get('message')==message.name for c in enqueue.call_args_list)
    with patch.object(whatsapp,'client') as client:
        client.return_value.call_tool.side_effect=SystemExit('Local email crash before admission')
        try:email_preferences.auto_reply(message.name)
        except SystemExit:pass
        else:raise AssertionError('Email crash boundary not exercised')
        assert frappe.db.get_value('Relay Message',message.name,'email_reply_status')=='Pending'
        client.return_value.call_tool.side_effect=None
        client.reset_mock()
        email_preferences.auto_reply(message.name);frappe.db.commit()
        assert frappe.db.get_value('Relay Message',message.name,'email_reply_status')=='Complete'
        client.return_value.call_tool.assert_not_called()
        assert frappe.db.count('Relay Message Action',{'source_message':message.name})==1
    # Thirty permanent failures cannot starve a later valid reply.
    failed=[]
    for index in range(30):
        doc=source('Denied auto reply '+str(index),provider='Email',address=address)
        frappe.db.set_value('Relay Message',doc.name,{'business_doctype':'Supplier','business_name':f.supplier.name,'email_reply_status':'Pending'})
        failed.append(doc.name)
    healthy_address='healthy-'+address;endpoint(f,'Email',healthy_address)
    healthy=source('Healthy reply behind failures',provider='Email',address=healthy_address)
    frappe.db.set_value('Relay Message',healthy.name,'email_reply_status','Pending');frappe.db.commit()
    for name in failed:email_preferences.auto_reply(name);frappe.db.commit()
    assert all(frappe.db.get_value('Relay Message',name,'email_reply_status')=='Failed' for name in failed)
    with patch.object(frappe,'enqueue') as enqueue:
        email_preferences.recover()
        assert any(c.kwargs.get('message')==healthy.name for c in enqueue.call_args_list)
    with patch.object(whatsapp,'client') as client:
        client.return_value.call_tool.return_value={'message_id':'<healthy-'+f.stamp+'@example.invalid>'}
        assert email_preferences.auto_reply(healthy.name)['status']=='Submitted'
        client.return_value.call_tool.assert_called_once()
        frappe.db.commit()
    assert frappe.db.get_value('Relay Message',healthy.name,'email_reply_status')=='Complete'
    print('PASS permanent email denials do not starve a healthy intent behind 30 failures')
    from relay_core import business_routing
    from relay_core.automation import projection
    action=frappe.get_doc('Relay Message Action',{'source_message':message.name})
    email_id='<local-be-receipt-'+f.stamp+'@example.invalid>'
    frappe.set_user(f.actor)
    with patch.object(whatsapp,'client') as client:
        client.return_value.call_tool.side_effect=[{'deliveries':[]},{'message_id':email_id}]
        assert messaging.reconcile(action.name)['status']=='Submitted'
    frappe.set_user('Administrator');action.reload()
    binding=endpoint(f,'Telegram','9555000789')
    context={'provider':'Telegram','chat_type':'private','chat_id':int(binding.endpoint),
             'participant_id':int(binding.endpoint),'message_id':71}
    business_routing.resolve(f.contact.name,binding.channel,binding.endpoint,context,
        {'id':'71','text':{'body':'Which business?'}},frappe._dict(name='local-choice-'+f.stamp,creation=frappe.utils.now_datetime()))
    prompt=frappe.get_doc('Relay Message Action',{'target_channel':binding.channel,'operation':'business_prompt'})
    binding.verified=0;binding.save()
    rows=[dict(id=1,request_key=prompt.request_key,operation='telegram.message',state='submitted',receipt={'message_id':72}),
          dict(id=2,request_key=action.request_key,operation='email.send',state='bounced',
               receipt={'message_id':email_id,'recipient':address,'delivery_status':'bounced'})]
    import hashlib
    import hmac
    from types import SimpleNamespace
    from relay_core import inbound
    rows[1]['receipt']['status_code']='5.1.1'
    for row in rows:row.update(delivery_id=row['id'],occurred_at='2026-10-25T00:00:00Z')
    payload={'account':f.account,'statuses':rows};raw=json.dumps(payload).encode();timestamp=str(int(time.time()))
    secret='local-backend-receipt-secret-fixture-only'
    request=SimpleNamespace(get_data=lambda:raw,headers={'X-Relay-Timestamp':timestamp,
        'X-Relay-Signature':hmac.new(secret.encode(),timestamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()})
    with patch.object(inbound,'connection_value',side_effect=lambda key:secret if key=='relay_callback_secret' else f.account),patch.object(frappe,'request',request):
        assert inbound.receive_channel_statuses()['accepted']==2
    key='channel-statuses:'+hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    event=frappe.get_doc('Relay Hub Event',{'event_key':key})
    frappe.db.commit();projection.project(event.name);frappe.db.commit();projection.project(event.name);frappe.db.commit()
    assert frappe.db.get_value('Relay Hub Event',event.name,'projection_status')=='Uncategorized'
    assert frappe.db.get_value('Relay Message',action.outbound_message,'status')=='Failed'
    print('PASS revoked prompt receipt cannot poison an email bounce in the same replayed batch')
    rule.enabled=0;rule.save();flow.enabled=0;flow.save();frappe.db.commit()
    print('PASS durable fixed-email intent survives job loss and crash without duplicate journal admission')


def legacy_ledger(f):
    import frappe
    from channel_site_fixtures import user
    from relay_core.ai.tools import Reader, contracts
    from relay_core.ai.samples import LEDGER_TOOL
    frappe.set_user('Administrator')
    actor=user('relay-be-ledger-'+f.stamp+'@example.invalid',manager=True)
    frappe.get_doc('User',actor).add_roles('Accounts User')
    company=frappe.db.get_value('Company',{},'name')
    row=frappe.get_doc(dict(doctype='GL Entry',name='LOCAL-BE-LEDGER-'+f.stamp,company=company,
        party_type='Supplier',party=f.supplier.name,debit=1250,credit=250,is_cancelled=0,
        posting_date=frappe.utils.nowdate(),voucher_type='Journal Entry',voucher_no='LOCAL-BE-'+f.stamp,
        remarks='Local-only old ledger contract test'))
    row.db_insert()
    old_contract=dict(LEDGER_TOOL,fields=[field for field in LEDGER_TOOL['fields'] if field!='company'])
    skill=frappe.get_doc(dict(doctype='Relay AI Skill',name='LOCAL-BE-OLD-LEDGER-'+f.stamp,
        title='Local old ledger contract',enabled=0,business_doctype='Supplier',allowed_tools=json.dumps([old_contract])))
    skill.db_insert();skill=frappe.get_doc('Relay AI Skill',skill.name)
    result=Reader(skill,actor,('Supplier',f.supplier.name)).read(contracts(skill)[0])
    assert result['totals']=={'debit':'1250.0','credit':'250.0','net_debit':'1000.0'}
    assert result['rows'][0]['company']==company
    assert 'company' not in json.loads(skill.allowed_tools)[0]['fields']
    frappe.db.rollback()
    print('PASS old persisted ledger contract reads permission-checked company and non-zero totals')


def concurrent_skills(f, model):
    import frappe
    from concurrent.futures import ThreadPoolExecutor
    barrier=threading.Barrier(2)
    names=[]
    for index in range(2):
        skill=frappe.get_doc(dict(doctype='Relay AI Skill',title='Local competing skill '+str(index)+' '+f.stamp,enabled=0,
            channel=f.channels['WhatsApp'].name,business_doctype='Customer',ai_model=model.name,run_as_user=f.actor,
            handoff_owner=f.actor,mode='Shadow',daily_limit=10,instructions='Read this customer only.',
            allowed_tools=json.dumps([dict(name='customer',method='get_doc',doctype='Customer',fields=['name'],scope_field='name')]))).insert()
        names.append(skill.name)
    frappe.db.commit()
    def enable(name):
        frappe.init(site='yrp.site',sites_path=os.environ['RELAY_AUTOMATION_TEST_SITES']);frappe.connect();frappe.set_user('Administrator')
        try:
            doc=frappe.get_doc('Relay AI Skill',name)
            frappe.get_doc('Relay Channel',doc.channel)  # Establish both pre-activation snapshots.
            barrier.wait(timeout=10)
            doc.enabled=1
            try:doc.save();frappe.db.commit();return 'enabled'
            except (ValueError,frappe.DuplicateEntryError,frappe.UniqueValidationError) as error:
                assert isinstance(error,(frappe.DuplicateEntryError,frappe.UniqueValidationError)) or 'Disable the existing skill' in str(error)
                frappe.db.rollback();return 'denied'
        finally:frappe.destroy()
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(enable,names))
    assert sorted(results)==['denied','enabled'],results
    frappe.db.rollback()
    for name in names:
        doc=frappe.get_doc('Relay AI Skill',name);doc.enabled=0;doc.save()
    frappe.db.commit()
    print('PASS concurrent skill activation from stale snapshots permits exactly one owner')


if __name__=='__main__': main()
