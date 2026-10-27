"""HTTP contract of the event-rule template picker on yrp.site; no Hub call and no send."""
import os
import secrets
import threading
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler

import requests
import frappe
import frappe.app
from channel_site_fixtures import init, user
from relay_core import settings, whatsapp_templates

init()
os.environ['SITES_PATH'] = os.environ['RELAY_AUTOMATION_TEST_SITES']
run = secrets.token_hex(4)
account, waba, other_waba = 'picker-' + run, '9' + str(secrets.randbelow(10 ** 12)), '8' + str(secrets.randbelow(10 ** 12))
manager = user('relay-picker-manager@example.invalid', manager=True)
operator = user('relay-picker-operator@example.invalid')
credentials = {}
for actor in (manager, operator):
    key, secret = secrets.token_hex(12), secrets.token_hex(24)
    doc = frappe.get_doc('User', actor); doc.api_key = key; doc.api_secret = secret; doc.save()
    credentials[actor] = {'Authorization': 'token ' + key + ':' + secret}
channel = frappe.get_doc({'doctype': 'Relay Channel', 'channel': 'WhatsApp', 'account': account, 'enabled': 1,
                          'label': 'Picker number', 'waba_id': waba}).insert()
other = frappe.get_doc({'doctype': 'Relay Channel', 'channel': 'WhatsApp', 'account': account, 'enabled': 1,
                        'label': 'Other number', 'waba_id': other_waba}).insert()
rows = [{'id': '1' + run.translate(str.maketrans('abcdef', '123456')) + str(index), 'name': name, 'language': language, 'status': status}
        for index, (name, language, status) in enumerate([('order_ready_notice', 'en', 'PENDING'),
            ('order_ready_notice', 'ta', 'APPROVED'), ('payment_reminder', 'en', 'APPROVED'), ('order_old', 'en', 'DELETED')])]
whatsapp_templates.store(account, rows, waba=waba)
whatsapp_templates.store(account, [{'id': '7' + rows[0]['id'], 'name': 'order_other_waba', 'language': 'en', 'status': 'APPROVED'}], waba=other_waba)
frappe.db.commit()
real_value = settings.value
patch.object(settings, 'value', side_effect=lambda key: account if key == 'relay_hub_account' else real_value(key)).start()


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


def application(environ, start_response):
    environ['HTTP_X_FRAPPE_SITE_NAME'] = 'yrp.site'
    environ['HTTP_HOST'] = '127.0.0.1:8001'
    return frappe.app.application(environ, start_response)


def call(actor, values=None, write=False):
    headers = credentials.get(actor, {})
    response = requests.request('POST' if write else 'GET', base + 'business_events.template_options', headers=headers,
                                **({'json': values or {}} if write else {'params': values or {}}), timeout=30)
    return response.status_code, response.json()


server = None
try:
    server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}/api/method/relay_core.'

    status, body = call(manager, {'query': 'order ready', 'channel': channel.name})
    items = body['message']['items']
    assert status == 200 and [row['label'] for row in items] == ['order_ready_notice · ta', 'order_ready_notice · en'], body
    assert set(items[0]) == {'value', 'label', 'description', 'status'}, items
    assert items[0]['description'] == 'APPROVED · Picker number' and items[1]['status'] == 'PENDING', items
    assert frappe.db.get_value('Relay WhatsApp Template', items[0]['value'], 'template_name') == 'order_ready_notice', items

    status, body = call(manager, {'query': 'order'})
    labels = [row['label'] for row in body['message']['items']]
    assert status == 200 and 'order_other_waba · en' in labels and 'order_old · en' not in labels, labels
    assert labels.index('order_other_waba · en') < labels.index('order_ready_notice · en'), labels
    status, body = call(manager, {'query': 'payment', 'channel': other.name})
    assert status == 200 and body['message']['items'] == [], body

    assert call(operator, {'query': 'order'})[0] == 403
    assert call(None, {'query': 'order'})[0] == 403
    assert call(manager, {'query': 'x' * 81})[0] == 417
    assert call(manager, {'query': 'order'}, write=True)[0] in (403, 405)
    print('template picker HTTP contracts passed')
finally:
    if server: server.shutdown()
    patch.stopall()
    frappe.db.rollback()  # The server thread updated these users after this snapshot.
    frappe.db.delete('Relay WhatsApp Template', {'account': account})
    for name in (channel.name, other.name):
        frappe.delete_doc('Relay Channel', name, force=True, ignore_permissions=True)
    for actor in (manager, operator):
        frappe.delete_doc('User', actor, force=True, ignore_permissions=True)
    frappe.db.commit()
