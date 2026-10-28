"""HTTP contract of template header media on yrp.site: refused links and uploads return 417 with a plain message; no Hub call."""
import base64
import json
import os
import secrets
import threading
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler

import requests
import frappe
import frappe.app
from channel_site_fixtures import init, user
from relay_core import settings
from relay_core.contact_lifecycle import enroll
from relay_core.contacts import ensure_relay

init()
os.environ['SITES_PATH'] = os.environ['RELAY_AUTOMATION_TEST_SITES']
run = secrets.token_hex(4)
account, number = 'header-media-' + run, '9198' + str(secrets.randbelow(10 ** 8)).zfill(8)
manager = user('relay-header-media-manager@example.invalid', manager=True)
key, secret = secrets.token_hex(12), secrets.token_hex(24)
doc = frappe.get_doc('User', manager); doc.api_key = key; doc.api_secret = secret; doc.save()
headers = {'Authorization': 'token ' + key + ':' + secret}
channel = frappe.get_doc({'doctype': 'Relay Channel', 'channel': 'WhatsApp', 'account': account, 'enabled': 1,
                          'label': 'Header media number'}).insert()
other = frappe.get_doc({'doctype': 'Relay Channel', 'channel': 'WhatsApp', 'account': 'other-' + run, 'enabled': 1,
                        'label': 'Other account number'}).insert()
person = frappe.get_doc({'doctype': 'Contact', 'first_name': 'Header Media ' + run, 'mobile_no': '+' + number}).insert()
relay = ensure_relay(person)
endpoint = enroll(relay, channel.name, 'WhatsApp', number).name
frappe.db.commit()
real_value = settings.value
patch.object(settings, 'value', side_effect=lambda name: account if name == 'relay_hub_account' else real_value(name)).start()


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


def application(environ, start_response):
    environ['HTTP_X_FRAPPE_SITE_NAME'] = 'yrp.site'
    environ['HTTP_HOST'] = '127.0.0.1:8001'
    return frappe.app.application(environ, start_response)


def call(method, values):
    response = requests.post(base + method, headers=headers, json=values, timeout=30)
    body = response.json()
    messages = [json.loads(row).get('message') for row in json.loads(body.get('_server_messages') or '[]')]
    return response.status_code, messages


def send(link, request_key):
    components = [{'type': 'header', 'parameters': [{'type': 'image', 'image': {'link': link}}]},
                  {'type': 'body', 'parameters': [{'type': 'text', 'text': 'Ravi'}]}]
    return call('conversation_start.send', {'contact': relay, 'endpoint': endpoint, 'kind': 'template', 'request_key': request_key,
                                            'data': {'name': 'offer', 'language': 'en_US', 'components': components}})


server = None
keys = ['header-media-' + run + '-' + str(index) for index in range(3)]
try:
    server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}/api/method/relay_core.'

    assert send('https://192.168.1.10/offer.png', keys[0]) == (417, ['Media link must point to a public host'])
    assert send('http://cdn.example.com/offer.png', keys[1]) == (417, ['Media needs an HTTPS link without credentials'])
    assert send('https://localhost/offer.png', keys[2]) == (417, ['Media link must point to a public host'])

    gif = base64.b64encode(b'GIF89a').decode()
    status, messages = call('template_media.upload', {'channel': channel.name, 'media_type': 'image', 'filename': 'offer.gif', 'content_base64': gif})
    assert (status, messages) == (417, ['This file type is not accepted for this image header']), (status, messages)
    status, messages = call('template_media.upload', {'channel': channel.name, 'media_type': 'sticker', 'filename': 'a.webp', 'content_base64': gif})
    assert (status, messages) == (417, ['Choose an image, video or document header']), (status, messages)
    status, _ = call('template_media.upload', {'channel': other.name, 'media_type': 'image', 'filename': 'offer.png', 'content_base64': gif})
    assert status == 403, status
    print('template header media HTTP contracts passed')
finally:
    if server: server.shutdown()
    patch.stopall()
    frappe.db.rollback()
    assert not frappe.db.exists('Relay Message Action', {'start_contact': relay}), 'a refused send created an action'
    frappe.delete_doc('Relay Contact Endpoint', endpoint, force=True, ignore_permissions=True)
    frappe.delete_doc('Relay Contact', relay, force=True, ignore_permissions=True)
    frappe.delete_doc('Contact', person.name, force=True, ignore_permissions=True)
    for name in (channel.name, other.name):
        frappe.delete_doc('Relay Channel', name, force=True, ignore_permissions=True)
    frappe.delete_doc('User', manager, force=True, ignore_permissions=True)
    frappe.db.commit()
