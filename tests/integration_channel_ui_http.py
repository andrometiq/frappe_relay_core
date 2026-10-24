"""Worktree HTTP contracts on yrp.site; local fixtures and no external delivery."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler

import requests
import frappe
import frappe.app
from channel_site_fixtures import init, user
from channel_identity_fixtures import scenario, configured, endpoint, incoming, email_raw, telegram_raw
from relay_core import enrollment, messaging, email, settings

init()
os.environ['SITES_PATH'] = os.environ['RELAY_AUTOMATION_TEST_SITES']
fixture = scenario()
admin = user('relay-cu-admin-' + fixture.stamp + '@example.invalid')
frappe.get_doc('User', admin).add_roles('System Manager')
credentials = {}
for actor in (admin, fixture.actor):
    key, secret = secrets.token_hex(12), secrets.token_hex(24)
    doc = frappe.get_doc('User', actor); doc.api_key = key; doc.api_secret = secret; doc.save()
    credentials[actor] = {'Authorization': 'token ' + key + ':' + secret}
frappe.db.commit()

class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


def application(environ, start_response):
    prefix = '/assets/relay_core/relay/'
    if environ.get('PATH_INFO', '').startswith(prefix):
        from werkzeug.wrappers import Response
        import mimetypes
        root = Path(__file__).resolve().parents[1] / 'relay_core/public/relay'
        path = (root / environ['PATH_INFO'][len(prefix):]).resolve()
        if path.is_relative_to(root) and path.is_file():
            return Response(path.read_bytes(), mimetype=mimetypes.guess_type(str(path))[0])(environ,start_response)
    environ['HTTP_X_FRAPPE_SITE_NAME'] = 'yrp.site'
    environ['HTTP_HOST'] = '127.0.0.1:8001'
    return frappe.app.application(environ, start_response)


def request(method, values=None, actor=admin, write=False, status=200):
    response = requests.request('POST' if write else 'GET', base + method,
        headers=credentials.get(actor, {}), **({'json':values or {}} if write else {'params':values or {}}), timeout=30)
    assert response.status_code == status, (method, response.status_code, response.json().get('exc_type'))
    if status == 200:
        assert 'message' in response.json(), method
        return response.json()['message']


server = None
try:
    with configured(fixture), patch.object(settings, 'value', return_value=fixture.account):
        sources, bindings = {}, {}
        for provider, sender in [('WhatsApp','919555001234'),('Telegram','9555001234'),('Email','local-cu-' + fixture.stamp + '@example.invalid')]:
            for index, business in enumerate((fixture.customer, fixture.supplier)):
                text = ('Customer' if index == 0 else 'Supplier PRIVATE') + ' quantity 25'
                if provider == 'WhatsApp':
                    text += ' · Local & team <img src=x onerror=alert(1)>'
                raw = email_raw('<cu-' + str(index) + '-' + fixture.stamp + '@example.invalid>') if provider == 'Email' else telegram_raw(int(sender),100+index,text) if provider == 'Telegram' else None
                if index == 0:
                    event, identifier = incoming(fixture,provider,sender,text,raw=raw,identifier=str(100+index) if provider == 'Telegram' else None)
                    for attempt in range(3):
                        try:
                            enrollment.bind(event.name,identifier,fixture.contact.name,business.doctype,business.name)
                            break
                        except frappe.QueryDeadlockError:
                            frappe.db.rollback()
                            if attempt == 2:raise
                    message = frappe.get_doc('Relay Message', {'channel':fixture.channels[provider].name,'provider_id':identifier})
                else:
                    message = frappe.get_doc({'doctype':'Relay Message','relay_contact':fixture.contact.name,
                        'channel':fixture.channels[provider].name,'sender_endpoint':sender,'direction':'Incoming',
                        'content':text,'message_data':json.dumps({'kind':'text','text':text}),'message_type':'text','status':'Sent','business_doctype':business.doctype,
                        'business_name':business.name,'provider_context':json.dumps({'provider':provider,
                        'message_id':'<private-'+fixture.stamp+'@example.invalid>' if provider=='Email' else 'private-'+fixture.stamp})}).insert()
                sources[(provider,index)] = message.name
            bindings[provider] = frappe.db.get_value('Relay Contact Endpoint',{'channel':fixture.channels[provider].name,'relay_contact':fixture.contact.name},'name')
        cc=endpoint(fixture,'Email','cc-'+fixture.stamp+'@example.invalid')
        bcc=endpoint(fixture,'Email','bcc-'+fixture.stamp+'@example.invalid')
        frappe.db.commit()
        server = make_server('127.0.0.1',0,application,handler_class=Quiet)
        thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base = f'http://127.0.0.1:{server.server_port}/api/method/relay_core.'
        context = {'contact':fixture.person.name,'business_doctype':'Customer','business_name':fixture.customer.name}
        cases = [
            ('api.channel_options',{}), ('api.contact_directory',{'query':'Local C2 ' + fixture.stamp}),
            ('api.contact_profile',{'contact':fixture.contact.name}), ('api.contact_details',{'contact':fixture.person.name}),
            ('api.contact_preferences',context), ('inbox.directory',{'query':'Local C2 ' + fixture.stamp,'medium':'Telegram'}),
            ('business_inbox.messages',{'doctype':'Customer','name':fixture.customer.name}),
            ('email.send_status',{'message':sources[('Email',0)],'request_key':'local-cu-missing'})]
        for method, values in cases:
            result = request(method,values)
            assert isinstance(result,dict),method
            request(method,values,actor=None,status=403)
        assert {row['channel'] for row in request('api.channel_options')['items']} == {'WhatsApp','Telegram','Email'}
        profile=request('api.contact_profile',{'contact':fixture.contact.name})
        assert set(profile)=={'name','display_name','contact'}
        for medium in ('WhatsApp','Telegram','Email'):
            page=request('inbox.directory',{'query':'Local C2 '+fixture.stamp,'medium':medium},actor=fixture.actor)
            assert len(page['items'])==1
            row=page['items'][0]
            if medium == 'WhatsApp': assert 'Local & team' in row['latest_preview'] and '&amp;' not in row['latest_preview']
            assert row['provider']==medium and row['unread']==1 and 'PRIVATE' not in row['latest_preview'], (medium,row['provider'],row['unread'],row['latest_preview'])
            page=request('business_inbox.messages',{'doctype':'Customer','name':fixture.customer.name,'medium':medium},actor=fixture.actor)
            assert [row['name'] for row in page['items']]==[sources[(medium,0)]]
        page=request('business_inbox.messages',{'doctype':'Customer','name':fixture.customer.name},actor=fixture.actor)
        assert len(page['items'])==3
        request('business_inbox.messages',{'doctype':'Supplier','name':fixture.supplier.name},actor=fixture.actor,status=403)
        request('api.contact_preferences',dict(context,business_doctype='Supplier',business_name=fixture.supplier.name),actor=fixture.actor,status=403)
        values=dict(context,endpoint=bindings['Email'],consent='Granted',priority=2)
        saved=request('api.save_contact_preference',values,write=True)
        assert set(saved)=={'name','endpoint','consent','priority'} and saved['consent']=='Granted'
        assert request('api.contact_preferences',context)['items'][0]['name']==saved['name']
        request('api.save_contact_preference',values,actor=fixture.actor,write=True,status=403)
        request('api.save_contact_preference',values,actor=None,write=True,status=403)
        request('api.save_contact_preference',values,status=403)
        request('api.save_contact_preference',dict(values,priority=101),write=True,status=417)
        saved=request('api.save_contact_preference',dict(values,consent='Denied'),write=True)
        assert saved['consent']=='Denied'
        # Real admission and persisted action read through HTTP; provider is a local stub.
        with patch('relay_core.whatsapp.client') as hub:
            hub.return_value.call_tool.return_value={'delivery':{'state':'queued'}}
            send={'message':sources[('Email',0)],'to':['local-cu-'+fixture.stamp+'@example.invalid'],
                'subject':'Local quantity 25','body':'HTTP draft with 25 items','request_key':'cu-'+fixture.stamp}
            submitted=request('email.send',send,write=True)
            assert submitted['status']=='Queued',submitted
            status=request('email.send_status',{'message':send['message'],'request_key':send['request_key']})
            assert status['action']==submitted['action'] and status['status']=='Queued'
            request('email.send_status',{'message':sources[('Email',1)],'request_key':send['request_key']},actor=fixture.actor,status=403)
            assert hub.return_value.call_tool.call_count==1
            pending_scope={'business_doctype':'Customer','business_name':fixture.customer.name}
            page=request('messaging.pending_messages',pending_scope)
            assert [row['action'] for row in page['items']]==[submitted['action']]
            assert page['items'][0]['scope']=='Customer:'+fixture.customer.name
            assert page['items'][0]['frappe_contact']==fixture.person.name
            assert request('messaging.pending_messages',{'business_doctype':'Supplier','business_name':fixture.supplier.name})['items']==[]
            request('messaging.pending_messages',pending_scope,actor=None,status=403)
            request('messaging.pending_messages',{'business_doctype':'Supplier','business_name':fixture.supplier.name},actor=fixture.actor,status=403)
        print('PASS HTTP statuses/shapes/denials, three-channel unread and business history, consent isolation, durable email reload; no provider calls')
        if os.environ.get('RELAY_CU_BROWSER_FIXTURE'):
            fixture_path=Path(os.environ['RELAY_CU_BROWSER_FIXTURE'])
            frappe.set_user('Administrator')
            from frappe.www.login import _generate_temporary_login_link
            link = _generate_temporary_login_link(admin,10)
            fixture_path.touch(mode=0o600)
            fixture_path.write_text(json.dumps({'site':'yrp.site','person':fixture.person.name,'contact':fixture.contact.name,
                'customer':fixture.customer.name,'cc':cc.endpoint,'bcc':bcc.endpoint,'login':link[link.index('/api/'):], 'port':server.server_port,
                'sources':{provider:sources[(provider,0)] for provider in fixture.channels}}))
            if os.environ.get('RELAY_CU_BROWSER'):
                with patch('relay_core.whatsapp.client') as hub:
                    def provider_response(tool, args=None):
                        if tool == 'email.send': return {'message_id':'<browser-'+str(__import__('time').time_ns())+'@example.invalid>'}
                        if tool == 'channels.deliveries': return {'deliveries':[]}
                        return {'data':[], 'profile':{}, 'status':'local test', 'templates':True, 'site':frappe.utils.get_url(), 'account':fixture.account}
                    hub.return_value.call_tool.side_effect=provider_response
                    hub.return_value.execute.side_effect=lambda operation, arguments=None: provider_response(operation,arguments)
                    original_settings=frappe.get_system_settings
                    # Repeated local captures must not exhaust the shared login-link throttle.
                    with patch.object(frappe,'get_system_settings',side_effect=lambda *args,**kwargs:
                        1000 if args and args[0]=='rate_limit_email_link_login' else original_settings(*args,**kwargs)):
                        result=subprocess.run(['node',str(Path(__file__).resolve().parents[1]/'frontend/tests/browser/channelUI.mjs'),str(fixture_path)])
                    assert result.returncode==0,'Browser acceptance failed'
            fixture_path.unlink()

finally:
    if os.environ.get('RELAY_CU_BROWSER_FIXTURE'):
        Path(os.environ['RELAY_CU_BROWSER_FIXTURE']).unlink(missing_ok=True)
    if server:
        server.shutdown();server.server_close();thread.join(timeout=5)
    frappe.db.rollback()
    frappe.set_user('Administrator')
    for actor in credentials:
        frappe.db.set_value('User',actor,{'enabled':0,'api_key':None})
    frappe.db.commit();frappe.destroy()
