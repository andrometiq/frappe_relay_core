"""Local yrp.site HTTP acceptance; only worktree code, no external delivery.

Run with the bench Python and PYTHONDONTWRITEBYTECODE=1 FRAPPE_STREAM_LOGGING=1.
Fixtures are clearly named, reusable local records. API credentials are ephemeral.
"""
import json
import os
from pathlib import Path
import secrets
import sys
import threading
from contextlib import ExitStack
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler

ROOT = Path(__file__).resolve().parents[1]
SITES = '/home/sakthi/development/pilot/benches/version_16/sites'
os.environ['SITES_PATH'] = SITES
os.environ['FRAPPE_STREAM_LOGGING'] = '1'
sys.path.insert(0, str(ROOT))
import frappe
import frappe.app
import relay_core
import requests
assert Path(relay_core.__file__).resolve().is_relative_to(ROOT)


def connect():
    frappe.init(site='yrp.site', sites_path=SITES)
    frappe.connect()
    frappe.set_user('Administrator')
    frappe.flags.mute_emails = True
    frappe.conf.relay_automation_enabled = 0


def fixture(doctype, filters, values):
    name = frappe.db.get_value(doctype, filters, 'name')
    return frappe.get_doc(doctype, name) if name else frappe.get_doc(dict(doctype=doctype, **values)).insert()


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


with ExitStack() as stack:
    stack.enter_context(patch.object(frappe, 'enqueue'))
    stack.enter_context(patch.object(frappe, 'publish_realtime'))
    stack.enter_context(patch.object(frappe, 'sendmail'))
    from relay_core import whatsapp
    stack.enter_context(patch.object(whatsapp, 'client', side_effect=AssertionError('External delivery blocked')))
    connect()
    assert frappe.local.site == 'yrp.site'
    assert frappe.db.exists('Relay Contact Type', {'business_doctype':'Customer', 'enabled':1})
    user = fixture('User', {'email':'relay-ui-display@example.invalid'}, {'email':'relay-ui-display@example.invalid',
        'first_name':'Local UI display verifier', 'send_welcome_email':0, 'roles':[{'role':'System Manager'}]})
    api_key, api_secret = secrets.token_hex(12), secrets.token_hex(24)
    user.api_key = api_key; user.api_secret = api_secret; user.enabled = 1; user.save()
    business = fixture('Customer', {'customer_name':'Local UI title verification'}, {
        'customer_name':'Local UI title verification', 'customer_type':'Company',
        'customer_group':frappe.db.get_value('Customer Group', {'is_group':0}, 'name'),
        'territory':frappe.db.get_value('Territory', {'is_group':0}, 'name')})
    person = fixture('Contact', {'first_name':'Local UI Maya'}, {'first_name':'Local UI Maya',
        'links':[{'link_doctype':'Customer', 'link_name':business.name}]})
    contact = fixture('Relay Contact', {'contact':person.name}, {'contact':person.name, 'display_name':'Local UI Maya'})
    channel = fixture('Relay Channel', {'title':'Local UI support'}, {'title':'Local UI support', 'channel':'Email',
        'account':'local-ui-display', 'enabled':0, 'mailbox_address':'support@example.invalid',
        'mailbox_aliases':'help@example.invalid\norders@example.invalid'})
    assert channel.name.startswith('Local UI support-')
    duplicate = fixture('Relay Channel', {'title':'Local UI duplicate support', 'account':'local-ui-display-secondary'},
        {'title':'Local UI duplicate support','channel':'Email','account':'local-ui-display-secondary','enabled':0})
    same_title = fixture('Relay Channel', {'title':'Local UI duplicate support', 'account':'local-ui-display-tertiary'},
        {'title':'Local UI duplicate support','channel':'Email','account':'local-ui-display-tertiary','enabled':0})
    assert duplicate.name != same_title.name
    assert all(value.startswith('Local UI duplicate support-') for value in (duplicate.name, same_title.name))
    print('PASS title-based configuration naming permits duplicate titles with readable suffixes')
    message = fixture('Relay Message', {'channel':channel.name, 'content':'Local UI order 42, amount 1250'}, {
        'relay_contact':contact.name, 'channel':channel.name, 'direction':'Outgoing', 'status':'Sent',
        'content':'Local UI order 42, amount 1250', 'sender_endpoint':'maya@example.invalid',
        'provider_context':json.dumps({'provider':'Email', 'to':['support@example.invalid','help@example.invalid','colleague@example.invalid'],
            'cc':['orders@example.invalid'], 'mailbox_addresses':['forged@example.invalid']}),
        'message_type':'text', 'message_data':json.dumps({'kind':'text','text':'Local UI order 42, amount 1250'})})
    # New readable names coexist with an old channel, without renaming any data.
    legacy = frappe.db.get_value('Relay Channel', {'name':['like','RELAY-CH-%']}, 'name')
    frappe.db.commit()
    args = {'contact':contact.name, 'channel':channel.name}
    name, contact_name, business_name = message.name, contact.name, business.name
    user_name = user.name
    frappe.destroy()
    original_init = frappe.app.init_request
    def init_request(request):
        original_init(request)
        frappe.flags.mute_emails = True
        frappe.conf.relay_automation_enabled = 0
    stack.enter_context(patch.object(frappe.app, 'init_request', init_request))
    def application(environ, start_response):
        environ['HTTP_X_FRAPPE_SITE_NAME'] = 'yrp.site'
        return frappe.app.application(environ, start_response)
    server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f'http://127.0.0.1:{server.server_port}/api/method/relay_core.'
    headers = {'Authorization':'token '+api_key+':'+api_secret}
    checks = [
        ('api.messages', args),
        ('api.message_snapshots', {'contact':contact_name, 'names':json.dumps([name])}),
        ('api.message_context', {'message':name}),
        ('business_inbox.messages', {'doctype':'Customer', 'name':business_name, 'channel':channel.name}),
        ('business_inbox.message_context', {'doctype':'Customer', 'name':business_name, 'message':name}),
    ]
    try:
        for method, params in checks:
            response = requests.get(url+method, params=params, headers=headers, timeout=20)
            assert response.status_code == 200, (method, response.status_code)
            data = response.json()['message']; assert isinstance(data['items'], list)
            row = next(row for row in data['items'] if row['name'] == name)
            assert row['channel_title'] == 'Local UI support'
            assert row['provider_context']['mailbox_addresses'] == ['help@example.invalid','orders@example.invalid','support@example.invalid']
            assert 'api_secret' not in row and 'mailbox_aliases' not in row
            denied = requests.get(url+method, params=params, timeout=20)
            assert denied.status_code in (401,403), (method, denied.status_code)
            print('PASS HTTP status, shape, mailbox provenance and guest denial:', method)
        refs = [{'doctype':'Relay Channel','name':channel.name}, {'doctype':'Customer','name':business_name}, {'doctype':'Contact','name':person.name}]
        response = requests.get(url+'display.titles', params={'records':json.dumps(refs)}, headers=headers, timeout=20)
        assert response.status_code == 200
        assert [row['title'] for row in response.json()['message']['items']] == ['Local UI support','Local UI title verification','Local UI Maya']
        denied = requests.get(url+'display.titles', params={'records':json.dumps(refs)}, timeout=20)
        assert denied.status_code in (401,403)
        invalid = requests.get(url+'display.titles', params={'records':json.dumps(refs*17)}, headers=headers, timeout=20)
        assert invalid.status_code == 417
        print('PASS HTTP permission-filtered titles, guest denial and 50-record bound')
        for channel_name in (channel.name, legacy):
            if not channel_name: continue
            response = requests.get(url+'api.channel_settings', params={'name':channel_name}, headers=headers, timeout=20)
            assert response.status_code == 200
            assert set(response.json()['message']) == {'name','channel','account','enabled'}
            assert requests.get(url+'api.channel_settings', params={'name':channel_name}, timeout=20).status_code in (401,403)
        print('PASS readable and legacy channel references coexist')
        response = requests.post(url+'api.update_channel', json={'name':channel.name, 'account':'local-ui-display', 'enabled':0}, headers=headers, timeout=20)
        assert response.status_code == 200
        assert response.json()['message']['name'] == channel.name and response.json()['message']['enabled'] == 0
        denied = requests.post(url+'api.update_channel', json={'name':channel.name, 'account':'local-ui-display', 'enabled':0}, timeout=20)
        assert denied.status_code in (400,401,403)
        print('PASS HTTP readable channel update status, shape and deny case')
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        connect()
        user = frappe.get_doc('User', user_name)
        user.api_key = None; user.api_secret = None; user.enabled = 0; user.save()
        frappe.db.commit(); frappe.destroy()
