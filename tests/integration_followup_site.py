"""Follow-up regressions through yrp.site storage, queue, HTTP and built UI."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler

from integration_ai_permissions_site import confine_writes
sys.addaudithook(confine_writes)
os.environ['FRAPPE_STREAM_LOGGING'] = '1'
import frappe
import frappe.app
import requests
from channel_site_fixtures import init, user
from channel_identity_fixtures import scenario, configured, cleanup
from relay_core.automation import queue
from relay_core.ai import configuration
from site_labels import phone

ROOT = Path(__file__).resolve().parents[1]
TEXT = 'Quantity 30 Total 1500 Local & team <review> "yes" \'ok\' &amp; literal <script>alert(1)</script>'


def main():
    init()
    assert frappe.local.site == 'yrp.site'
    f = scenario()
    server = None
    model = account = None
    try:
        operator = user('sim-review-' + f.stamp + '@example.invalid', manager=True)
        frappe.get_doc('User', operator).add_roles('System Manager')
        for row in frappe.get_all('User Permission', filters={'user': f.actor}, fields=['allow', 'for_value']):
            frappe.get_doc(dict(doctype='User Permission', user=operator, allow=row.allow,
                               for_value=row.for_value, apply_to_all_doctypes=1)).insert()
        credentials = {}
        for actor in (f.actor, operator):
            key, secret = secrets.token_hex(12), secrets.token_hex(24)
            doc = frappe.get_doc('User', actor); doc.api_key = key; doc.api_secret = secret; doc.save()
            credentials[actor] = 'token ' + key + ':' + secret
        messages = []
        for provider in ('WhatsApp', 'Telegram', 'Email'):
            for business in (f.customer, f.supplier):
                doc = frappe.get_doc(dict(doctype='Relay Message', relay_contact=f.contact.name,
                    channel=f.channels[provider].name, direction='Incoming', content=TEXT, message_type='text',
                    sender_endpoint=phone(f.stamp), business_doctype=business.doctype, business_name=business.name,
                    provider_context=json.dumps({'provider':provider}))).insert()
                doc.reload()
                assert doc.content == TEXT and json.loads(doc.message_data)['text'] == TEXT, provider
                messages.append(doc)
        hidden_person = frappe.get_doc(dict(doctype='Contact', first_name='Sim Supplier Contact '+f.stamp,
            links=[dict(link_doctype='Supplier', link_name=f.supplier.name)])).insert()
        hidden = frappe.get_doc(dict(doctype='Relay Contact', contact=hidden_person.name,
            display_name='Sim Supplier Contact '+f.stamp)).insert()
        hidden_message = frappe.get_doc(dict(doctype='Relay Message', relay_contact=hidden.name,
            channel=f.channels['WhatsApp'].name, direction='Incoming', content='Private supplier amount 4500',
            business_doctype='Supplier', business_name=f.supplier.name)).insert()
        messages.append(hidden_message)
        account = frappe.get_doc(dict(doctype='AI Provider Account', name='Sim Provider '+f.stamp,
            account_label='Sim Provider '+f.stamp, provider='OpenRouter', enabled=1)); account.db_insert()
        model = frappe.get_doc(dict(doctype='AI Model', name='Sim Model '+f.stamp, model_label='Sim Model '+f.stamp,
            account=account.name, provider='OpenRouter', model_id='local-no-network', enabled=1)); model.db_insert()
        skills = []
        for title, provider in (('Primary', 'WhatsApp'), ('Backup', 'WhatsApp'), ('Telegram', 'Telegram')):
            skill = frappe.get_doc(dict(doctype='Relay AI Skill', name='Sim ' + title + ' ' + f.stamp,
                title='Sim ' + title + ' ' + f.stamp, enabled=1, channel=f.channels[provider].name,
                business_doctype='Customer', run_as_user=f.actor, handoff_owner=f.actor,
                mode='Shadow', daily_limit=10, instructions='Read only this customer.', ai_model=model.name, allowed_tools='[]'))
            skill.db_insert(); skills.append(skill)
        with patch.object(configuration, 'contracts'), patch.object(configuration, 'require_access'):
            try: configuration.validate_skill(skills[0])
            except ValueError as error:
                assert skills[1].name in str(error) and f.channels['WhatsApp'].name in str(error), str(error)
            else: raise AssertionError('Existing duplicate scope was accepted')
        case_type = frappe.get_doc(dict(doctype='Relay Case Type', type_key='sim.'+f.stamp, title='Sim Orders '+f.stamp,
            enabled=1, definition=json.dumps({'fields':{'type':'object','properties':{'quantity':{'type':'number'}}},
            'initial_stage':'open','stages':[{'key':'open','label':'Open','state':'open'}]}))).insert()
        ticket = frappe.get_doc(dict(doctype='Relay Ticket', subject='Sim Order Review '+f.stamp, brief='Quantity 30, total 1500',
            category='Support', status='Open', business_doctype='Customer', business_name=f.customer.name,
            assigned_to=operator, messages=[{'message':messages[0].name}])).insert()
        frappe.db.commit()
        # Run the real whole-site drain, limiting admission to this test's messages.
        real_get_all = frappe.get_all
        def local_messages(doctype, *args, **kwargs):
            if doctype == 'Relay Message' and kwargs.get('filters') == {'automation_status':'Pending'}:
                kwargs['filters'] = {**kwargs['filters'], 'name':['in',[doc.name for doc in messages]]}
            return real_get_all(doctype, *args, **kwargs)
        frappe.conf.relay_automation_enabled = 1
        with patch.object(frappe, 'get_all', side_effect=local_messages):
            assert queue.drain() == len(messages)
            assert queue.drain() == 0
        bad = frappe.get_doc('Relay Automation Run', {'message':messages[0].name})
        assert bad.status == 'Handoff' and skills[1].name in bad.reason and not bad.skill
        good = frappe.get_doc('Relay Automation Run', {'message':messages[2].name})
        assert good.status == 'Pending' and good.skill == skills[2].name
        assert all(frappe.db.get_value('Relay Message', m.name, 'automation_status') == 'Complete' for m in messages)
        frappe.conf.relay_automation_enabled = 0
        print('PASS plain-text persistence on three channels; duplicate validation; isolated handoff, healthy channel and replay')

        class Quiet(WSGIRequestHandler):
            def log_message(self, *args): pass
        def application(environ, start_response):
            from werkzeug.wrappers import Response
            path = environ['PATH_INFO']
            if path == '/' or path.startswith('/assets/relay_core/relay/'):
                asset = ROOT / 'relay_core/public/relay' / ('site.html' if path == '/' else path.split('/assets/relay_core/relay/',1)[1])
                if not asset.resolve().is_relative_to(ROOT / 'relay_core/public/relay') or not asset.is_file():
                    return Response(status=404)(environ,start_response)
                import mimetypes
                body = asset.read_bytes()
                if path == '/': body = body.replace(b'id="app"', ('id="app" data-user="'+operator+'"').encode())
                return Response(body, content_type=mimetypes.guess_type(asset)[0])(environ,start_response)
            environ['HTTP_X_FRAPPE_SITE_NAME']='yrp.site'
            environ.setdefault('HTTP_AUTHORIZATION', credentials[operator])
            return frappe.app.application(environ,start_response)
        os.environ['SITES_PATH'] = os.environ['RELAY_AUTOMATION_TEST_SITES']
        server = make_server('127.0.0.1',0,application,handler_class=Quiet)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        def rpc(method, values=None, status=200, write=False):
            response = requests.request('POST' if write else 'GET',base+'/api/method/relay_core.'+method,
                headers={'Authorization':credentials[f.actor]}, **({'json':values} if write else {'params':values}), timeout=20)
            result = response.json()
            assert response.status_code == status, (method,response.status_code,result.get('exc_type'))
            if status==200: assert 'message' in result; return result['message']
            assert result['exc_type']=='PermissionError'
        directory = rpc('inbox.directory', {'query':f.contact.display_name})
        row = next(row for row in directory['items'] if row['name']==f.contact.name)
        assert row['latest_preview']==TEXT
        rpc('api.messages',{'contact':hidden.name},status=403)
        page = rpc('api.messages',{'contact':f.contact.name})
        assert all(row['relay_contact']==f.contact.name and row['business_doctype']=='Customer' and row['content']==TEXT for row in page['items'])
        for business, status in ((f.customer,200),(f.supplier,403)):
            scope={'business_doctype':business.doctype,'business_name':business.name}
            note=rpc('collaboration.add',dict(contact=f.contact.name,body='Quantity 30 total 1500',request_key='sim-note-'+business.doctype+f.stamp,**scope),status,True)
            case=rpc('cases.create_manual',dict(contact=f.contact.name,case_type=case_type.name,title='Sim Manual Order',field_values={'quantity':30},request_key='sim-case-'+business.doctype+f.stamp,**scope),status,True)
            topic=rpc('topics.save',dict(contact=f.contact.name,request_key='sim-topic-'+business.doctype+f.stamp,values={'title':'Sim Empty Topic',**scope}),status,True)
            if status==200:
                assert note['name'] and case['field_values']['quantity']==30 and topic['message_count']==0
        # Configuration diagnostics report legacy conflicts through the public API too.
        denied = requests.post(base+'/api/method/relay_core.ai.configuration.save',
            headers={'Authorization':credentials[f.actor]},json={'name':skills[0].name,'values':{'enabled':1}},timeout=20)
        assert denied.status_code==403 and denied.json()['exc_type']=='PermissionError'
        conflict = requests.post(base+'/api/method/relay_core.ai.configuration.save',
            headers={'Authorization':credentials[operator]},json={'name':skills[0].name,'values':{'enabled':1}},timeout=20)
        assert conflict.status_code==500 and conflict.json()['exc_type']=='ValueError'
        assert skills[1].name in conflict.json()['exception']
        print('PASS HTTP inbox/message shape and scoped preview; unreferenced notes, manual cases and empty topics allow Customer and deny Supplier')
        legacy = messages[0]
        frappe.db.set_value('Relay Message', legacy.name, {'content':'relay-business:'+'a'*32,
            'message_data':json.dumps({'kind':'text','text':'relay-business:'+'a'*32})})
        frappe.db.commit()
        legacy_row = next(row for row in rpc('api.messages',{'contact':f.contact.name})['items'] if row['name']==legacy.name)
        assert legacy_row['content']=='Chose: Customer' and legacy_row['message_data']['text']=='Chose: Customer'
        # Restore this fixture so the browser verifies identical text on all three channels.
        frappe.db.set_value('Relay Message', legacy.name, {'content':TEXT,'message_data':json.dumps({'kind':'text','text':TEXT})})
        frappe.db.commit()
        with configured(f):
            subprocess.run(['node',str(ROOT/'frontend/tests/browser/followupSite.mjs')],cwd=ROOT,
                input=json.dumps({'base':base,'contact':f.contact.name,'contactTitle':f.contact.display_name,
                    'customer':f.customer.name,'caseType':case_type.name,'caseTitle':case_type.title,
                    'ticket':ticket.subject,'skill':skills[0].title,'text':TEXT}),text=True,check=True)
        print('PASS built UI on yrp.site through HTTP at desktop and mobile sizes')
    finally:
        if server: server.shutdown(); server.server_close()
        cleanup(f)
        for doc in (model, account):
            if doc and frappe.db.exists(doc.doctype, doc.name):
                frappe.db.set_value(doc.doctype, doc.name, 'enabled', 0)
        frappe.db.commit()
        frappe.destroy()


if __name__=='__main__': main()
