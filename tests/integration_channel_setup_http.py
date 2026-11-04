"""Real loopback HTTP into Frappe for the channel setup endpoints: who may read, who may configure, who is refused.
Run from the bench sites folder with this checkout first on PYTHONPATH and RELAY_HTTP_TEST_SITE set to a test site.
The Hub is never called: readers get a fake Hub answer and every refusal happens before the Hub.
"""
import os, secrets, threading, time
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler

import requests
import frappe
import frappe.app
from relay_core.channel_setup import whatsapp

site = os.environ['RELAY_HTTP_TEST_SITE']
assert 'test' in site and 'live' not in site, 'Use a throwaway test site'
frappe.init(site=site); frappe.connect(); frappe.set_user('Administrator'); frappe.flags.mute_emails = True
assert 'relay_core' in frappe.get_installed_apps()
stamp = str(time.time_ns()); users = {}


def person(kind, roles):
    key, secret = secrets.token_hex(12), secrets.token_hex(24)
    doc = frappe.get_doc({'doctype': 'User', 'email': f'setup-{kind}-{stamp}@example.com', 'first_name': 'Sam Customer',
                          'send_welcome_email': 0, 'roles': [{'role': role} for role in roles], 'api_key': key, 'api_secret': secret}).insert()
    users[kind] = (doc.name, 'token ' + key + ':' + secret)


person('agent', ['Relay Communication User'])
person('manager', ['Relay Communication Manager'])
person('admin', ['System Manager', 'Relay Communication Manager'])
frappe.db.commit()


class Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def application(environ, start_response):
    environ['HTTP_X_FRAPPE_SITE_NAME'] = site
    return frappe.app.application(environ, start_response)


server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
base = f'http://127.0.0.1:{server.server_port}/api/method/relay_core.'
WRITES = [('channels_api.check_number', {'channel': 'missing'}), ('channels_api.save_number_settings', {'channel': 'missing', 'settings': {'templates': 1}}),
          ('channels_api.set_default', {'channel': 'missing'}), ('channels_api.reset_pin', {'channel': 'missing'}),
          ('channels_api.remove_number', {'channel': 'missing', 'confirm': 1}), ('channels_api.save_number_profile', {'channel': 'missing', 'profile': {'about': 'Acme Textiles'}}),
          ('onboarding.api.disconnect_hub', {'confirm': 0})]


def call(method, values=None, kind=None, write=True):
    headers = {'Authorization': users[kind][1]} if kind else {}
    if write:
        return requests.post(base + method, json=values or {}, headers=headers, timeout=20)
    return requests.get(base + method, params=values or {}, headers=headers, timeout=20)


def fake_hub(tool, arguments):
    return {'channels': []} if tool == 'channels.list' else {}


try:
    with patch.object(whatsapp, 'hub_call', side_effect=fake_hub), patch('relay_core.onboarding.enrolment.HubClient', side_effect=AssertionError('Hub called')):
        for kind in (None, 'agent'):
            assert call('channels_api.accounts', kind=kind, write=False).status_code == 403, kind
            assert call('channels_api.number_profile', {'channel': 'missing'}, kind=kind, write=False).status_code == 403, kind
        for kind in (None, 'agent', 'manager'):
            for method, values in WRITES:
                assert call(method, values, kind).status_code == 403, (kind, method)
        response = call('channels_api.accounts', kind='manager', write=False)
        assert response.status_code == 200 and response.json()['message'] == {'accounts': [], 'can_configure': False}, response.text[:300]
        response = call('channels_api.accounts', kind='admin', write=False)
        assert response.status_code == 200 and response.json()['message']['can_configure'] is True, response.text[:300]
        # A System Manager passes the gate; an unknown number is refused without a Hub call.
        response = call('channels_api.check_number', {'channel': 'missing'}, 'admin')
        assert response.status_code not in (200, 403), response.status_code
        assert call('onboarding.api.disconnect_hub', {'confirm': 0}, 'admin').status_code not in (200, 403)
    print('PASS channel setup HTTP: guests and agents refused, managers read only, System Manager configures')
finally:
    server.shutdown(); server.server_close(); thread.join(timeout=5)
    for name, _ in users.values():
        frappe.delete_doc('User', name, force=True, ignore_permissions=True)
    frappe.db.commit(); frappe.destroy()
