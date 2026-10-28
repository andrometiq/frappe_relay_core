"""Real loopback HTTP into Frappe for the WhatsApp forms list: shape, a calm read error, and denial for non-managers.
Synthetic users only; they are disabled afterwards. Hub is a fixture; no provider requests.
Run from the bench sites folder: PYTHONPATH=<worktree>:<worktree>/tests CI=1 ../env/bin/python -B <this file>
"""
import secrets, threading
from pathlib import Path
from unittest.mock import Mock, patch
from wsgiref.simple_server import make_server, WSGIRequestHandler
import requests
import frappe
import frappe.app
from relay_core import meta_flows
from relay_core.hub import HubError

SITE = 'yrp.site'
frappe.init(site=SITE)
frappe.connect()
frappe.set_user('Administrator')
assert Path(meta_flows.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1]), 'Run with this checkout first on PYTHONPATH'


def fixture_user(email, role):
    key, secret = secrets.token_hex(12), secrets.token_hex(24)
    if frappe.db.exists('User', email):
        frappe.get_doc('User', email).update({'enabled': 1, 'api_key': key, 'api_secret': secret}).save()
    else:
        frappe.get_doc({'doctype': 'User', 'email': email, 'first_name': 'Forms fixture', 'send_welcome_email': 0,
                        'roles': [{'role': role}], 'api_key': key, 'api_secret': secret}).insert()
    return {'Authorization': f'token {key}:{secret}'}


users = {'relay-forms-manager-fixture@example.invalid': 'Relay Communication Manager',
         'relay-forms-agent-fixture@example.invalid': 'Relay Communication Team User'}
manager, agent = (fixture_user(email, role) for email, role in users.items())
frappe.db.commit()


class Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def application(environ, start_response):
    environ['HTTP_X_FRAPPE_SITE_NAME'] = SITE
    return frappe.app.application(environ, start_response)


server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
url = f'http://127.0.0.1:{server.server_port}/api/method/relay_core.meta_flows.execute'
try:
    hub = Mock()
    with patch.object(meta_flows, 'checked_client', return_value=(hub, {'flows': True})), \
            patch.object(meta_flows, 'choose'), patch.object(meta_flows, 'hub_arguments', side_effect=lambda channel, arguments: arguments):
        hub.execute.return_value = {'data': [{'id': '1', 'name': 'Feedback', 'status': 'PUBLISHED'}], 'paging': {}}
        response = requests.post(url, json={'operation': 'list'}, headers=manager, timeout=20)
        assert response.status_code == 200, (response.status_code, response.text[:300])
        assert response.json()['message']['data'][0]['name'] == 'Feedback', response.text[:300]
        hub.execute.side_effect = HubError('Hub operation was rejected')
        response = requests.post(url, json={'operation': 'list'}, headers=manager, timeout=20)
        assert response.status_code == 417, response.status_code
        assert 'WhatsApp forms could not be loaded right now' in response.json()['exception'], response.text[:300]
        assert 'retrying a change' not in response.text
        calls = hub.execute.call_count
        for headers in ({}, agent):
            response = requests.post(url, json={'operation': 'list'}, headers=headers, timeout=20)
            assert response.status_code == 403, response.status_code
        assert hub.execute.call_count == calls, 'Denied requests must not reach Hub'
    print('PASS forms list HTTP: manager gets the list shape, a failed read says the forms could not load, guests and agents are denied')
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    frappe.db.rollback()
    for email in users:
        frappe.db.set_value('User', email, {'enabled': 0, 'api_key': None})
    frappe.db.commit()
    frappe.destroy()
