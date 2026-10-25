"""HTTP contracts for enabled channels and template rejection text on yrp.site; the Hub is faked."""
import os
import secrets
import threading
from unittest.mock import Mock, patch
from wsgiref.simple_server import make_server, WSGIRequestHandler

import requests
import frappe
import frappe.app
from channel_site_fixtures import init, user
from relay_core import whatsapp, whatsapp_templates
from relay_core.hub import HubError, tool_detail

init()
os.environ['SITES_PATH'] = os.environ['RELAY_AUTOMATION_TEST_SITES']
manager = user('relay-template-manager@example.invalid', manager=True)
operator = user('relay-template-operator@example.invalid')
outsider = 'relay-template-outsider@example.invalid'
if not frappe.db.exists('User', outsider):
    with patch('frappe.core.doctype.user.user.throttle_user_creation'):
        frappe.get_doc({'doctype': 'User', 'email': outsider, 'first_name': 'Template Outsider', 'send_welcome_email': 0}).insert()
credentials = {}
for actor in (manager, operator, outsider):
    key, secret = secrets.token_hex(12), secrets.token_hex(24)
    doc = frappe.get_doc('User', actor); doc.api_key = key; doc.api_secret = secret; doc.save()
    credentials[actor] = {'Authorization': 'token ' + key + ':' + secret}
frappe.db.commit()
audited = frappe.db.table_exists('Relay WhatsApp Template Request')


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


def application(environ, start_response):
    environ['HTTP_X_FRAPPE_SITE_NAME'] = 'yrp.site'
    environ['HTTP_HOST'] = '127.0.0.1:8001'
    return frappe.app.application(environ, start_response)


def call(method, actor, values=None, write=False):
    response = requests.request('POST' if write else 'GET', base + method, headers=credentials[actor],
        **({'json': values or {}} if write else {'params': values or {}}), timeout=30)
    return response.status_code, response.json()


detail = "Variables can't be at the start or end of the template"
hub = Mock()
hub.execute.side_effect = HubError('rejected', detail=tool_detail({'content': [{'type': 'text', 'text': detail + ' Bearer ' + 'x' * 40}]}))
template = {'name': 'relay_template_http_check', 'language': 'en_US', 'category': 'UTILITY',
            'parameter_format': 'named', 'components': [{'type': 'BODY', 'text': '{{customer_name}} hello'}]}
server = None
try:
    stubs = [patch.object(whatsapp, 'checked_client', return_value=(hub, {'templates': True}))]
    if not audited:  # The new audit DocType needs a reload before rows can persist.
        stubs.append(patch.multiple(whatsapp_templates, record_request=Mock(), apply_request=Mock()))
    for stub in stubs: stub.start()
    server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}/api/method/relay_core.'

    status, body = call('api.capabilities', operator)
    assert status == 200 and body['message'] == {'manage': False, 'configure': False, 'enabled_channels': ['WhatsApp']}, body
    status, body = call('api.capabilities', manager)
    assert status == 200 and body['message']['manage'] and body['message']['enabled_channels'] == ['WhatsApp'], body
    assert call('api.capabilities', outsider)[0] == 403

    status, body = call('whatsapp.execute', manager, {'operation': 'templates.create', 'arguments': template}, True)
    assert status == 417 and 'Hub rejected this operation: ' + detail in body.get('_server_messages', ''), body
    assert 'x' * 40 not in str(body) and 'Bearer' not in str(body), body
    assert call('whatsapp.execute', operator, {'operation': 'templates.create', 'arguments': template}, True)[0] == 403
    assert call('whatsapp.execute', outsider, {'operation': 'templates.list'}, True)[0] == 403
    status, body = call('whatsapp.execute', operator, {'operation': 'templates.list'}, True)
    assert status == 417 and whatsapp.FAILURE.split('.')[0] in body.get('_server_messages', '') and detail not in str(body), body
    if audited:
        rows = frappe.get_all('Relay WhatsApp Template Request', filters={'template_name': template['name']},
                              fields=['owner', 'status', 'error', 'operation'])
        assert rows and rows[0].owner == manager and rows[0].status == 'Failed' and rows[0].error.startswith(detail), rows
    synced_key = whatsapp_templates.SYNCED + (whatsapp_templates.connection_value('relay_hub_account') or '')
    previous_sync = frappe.cache.get_value(synced_key)
    frappe.cache.set_value(synced_key, {'synced_at': '2026-10-26 09:00:00', 'templates': 17})
    try:
        status, body = call('whatsapp_templates.sync_status', operator)
        assert status == 200 and body['message'] == {'synced_at': '2026-10-26 09:00:00', 'templates': 17}, body
        assert call('whatsapp_templates.sync_status', outsider)[0] == 403
        assert call('whatsapp_templates.sync_status', operator, write=True)[0] in (403, 405)
        frappe.cache.delete_value(synced_key)
        status, body = call('whatsapp_templates.sync_status', manager)
        assert status == 200 and body['message'] == {'synced_at': None, 'templates': 0}, body
    finally:
        if previous_sync: frappe.cache.set_value(synced_key, previous_sync)
    print('template HTTP contracts passed' + ('' if audited else ' (audit persistence untested: DocType not reloaded)'))
finally:
    if server: server.shutdown()
    patch.stopall()
    frappe.db.rollback()  # The server thread updated these users after this snapshot.
    if audited:
        frappe.db.delete('Relay WhatsApp Template Request', {'template_name': template['name']})
    for actor in (manager, operator, outsider):
        frappe.delete_doc('User', actor, force=True, ignore_permissions=True)
    frappe.db.commit()
