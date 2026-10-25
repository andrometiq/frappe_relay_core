"""Local yrp.site HTTP acceptance for where a thread opens and for received media failures.

Only worktree code runs; the Hub is a local fake, so no provider is contacted.
Run from the bench sites folder: PYTHONPATH=<worktree>:<worktree>/tests CI=1 ../env/bin/python -B <this file>
"""
import base64
import json
import secrets
import threading
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler
import requests
import frappe
import frappe.app
from relay_core import inbox, messaging, whatsapp
from relay_core.hub import HubError

SITE = 'yrp.site'
assert Path(inbox.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1]), 'Run with this checkout first on PYTHONPATH'


def connect():
    frappe.init(site=SITE)
    frappe.connect()
    frappe.set_user('Administrator')
    frappe.flags.mute_emails = True
    frappe.conf.relay_automation_enabled = 0


def fixture(doctype, filters, values):
    name = frappe.db.get_value(doctype, filters, 'name')
    return frappe.get_doc(doctype, name) if name else frappe.get_doc(dict(doctype=doctype, **values)).insert()


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


class FakeHub:
    """Answers whatsapp.attachment by media ID: expired, busy or a small photo."""
    def call_tool(self, name, arguments):
        assert name == 'whatsapp.attachment'
        if arguments['media_id'] == '7001':
            raise HubError('rejected', {'provider': 'Hub', 'error': {'check': 'provider_metadata'}})
        if arguments['media_id'] == '7002':
            raise HubError('rejected', {'provider': 'Hub', 'error': {'check': 'capacity'}})
        return {'content_base64': base64.b64encode(b'local photo bytes').decode(), 'content_type': 'image/jpeg'}


with ExitStack() as stack:
    for target in ('enqueue', 'publish_realtime', 'sendmail'):
        stack.enter_context(patch.object(frappe, target))
    stack.enter_context(patch.object(whatsapp, 'client', return_value=FakeHub()))
    stack.enter_context(patch.object(messaging, 'connection_value', side_effect=lambda key: 'local-media-view' if key == 'relay_hub_account' else None))
    connect()
    assert frappe.db.exists('Relay Contact Type', {'business_doctype': 'Customer', 'enabled': 1})
    user = fixture('User', {'email': 'relay-media-view@example.invalid'}, {'email': 'relay-media-view@example.invalid',
        'first_name': 'Local media view verifier', 'send_welcome_email': 0, 'roles': [{'role': 'System Manager'}]})
    api_key, api_secret = secrets.token_hex(12), secrets.token_hex(24)
    user.api_key = api_key; user.api_secret = api_secret; user.enabled = 1; user.save()
    business = fixture('Customer', {'customer_name': 'Local media view verification'}, {
        'customer_name': 'Local media view verification', 'customer_type': 'Company',
        'customer_group': frappe.db.get_value('Customer Group', {'is_group': 0}, 'name'),
        'territory': frappe.db.get_value('Territory', {'is_group': 0}, 'name')})
    person = fixture('Contact', {'first_name': 'Local Media Ravi'}, {'first_name': 'Local Media Ravi',
        'links': [{'link_doctype': 'Customer', 'link_name': business.name}]})
    contact = fixture('Relay Contact', {'contact': person.name}, {'contact': person.name, 'display_name': 'Local Media Ravi'})
    channel = fixture('Relay Channel', {'title': 'Local media view'}, {'title': 'Local media view', 'channel': 'WhatsApp',
        'account': 'local-media-view', 'enabled': 0})
    fixture('Relay Contact Endpoint', {'channel': channel.name, 'endpoint': 'local-media-ravi'}, {'channel': channel.name,
        'relay_contact': contact.name, 'endpoint': 'local-media-ravi', 'verified': 1})

    def message(content, kind, media_id=None):
        data = {'kind': kind, 'text': content} if kind == 'text' else {'kind': kind, 'media': {'id': media_id, 'mime_type': 'image/jpeg'}}
        return fixture('Relay Message', {'channel': channel.name, 'content': content}, {
            'relay_contact': contact.name, 'channel': channel.name, 'direction': 'Incoming', 'status': 'Sent',
            'content': content, 'message_type': kind, 'message_data': json.dumps(data), 'sender_endpoint': 'local-media-ravi'})
    expired, busy, recent = message('Local media expired photo', 'image', '7001'), message('Local media busy photo', 'image', '7002'), message('Local media recent photo', 'image', '7003')
    # Created last but sent first: the conversation opens at it because thread order is by sent time.
    earliest = message('Local media earliest question', 'text')
    now = frappe.utils.now_datetime()
    for row, sent in ((expired, now - timedelta(days=40)), (busy, now - timedelta(hours=1)), (recent, now - timedelta(minutes=5)), (earliest, now - timedelta(days=41))):
        frappe.db.set_value('Relay Message', row.name, 'sent_at', sent, update_modified=False)
    state = frappe.db.get_value('Relay Conversation State', {'state_key': inbox.state_key(contact.name, user.name)}, 'name')
    if state: frappe.delete_doc('Relay Conversation State', state, ignore_permissions=True, force=True)
    frappe.db.delete('Relay Message Read', {'user': user.name, 'message': ['in', [expired.name, busy.name, recent.name, earliest.name]]})
    frappe.db.set_value('Relay Channel', channel.name, 'enabled', 1)
    frappe.db.commit()
    names = {'expired': expired.name, 'busy': busy.name, 'recent': recent.name, 'earliest': earliest.name, 'newest': max(expired.name, busy.name, recent.name, earliest.name)}
    contact_name, user_name, channel_name = contact.name, user.name, channel.name
    frappe.destroy()

    original_init = frappe.app.init_request
    def init_request(request):
        original_init(request)
        frappe.flags.mute_emails = True
        frappe.conf.relay_automation_enabled = 0
    stack.enter_context(patch.object(frappe.app, 'init_request', init_request))
    def application(environ, start_response):
        environ['HTTP_X_FRAPPE_SITE_NAME'] = SITE
        return frappe.app.application(environ, start_response)
    server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f'http://127.0.0.1:{server.server_port}/api/method/relay_core.'
    headers = {'Authorization': 'token ' + api_key + ':' + api_secret}
    get = lambda method, params, auth=True: requests.get(url + method, params=params, headers=headers if auth else {}, timeout=20)
    try:
        response = get('inbox.view_state', {'contact': contact_name})
        assert response.status_code == 200, response.text[:300]
        state = response.json()['message']
        assert state['first_unread'] == names['earliest'] and state['channel'] == '', state
        assert get('inbox.view_state', {'contact': contact_name, 'channel': channel.name}).json()['message']['first_unread'] == names['earliest']
        assert get('inbox.view_state', {'contact': contact_name}, auth=False).status_code in (401, 403)
        update = requests.post(url + 'inbox.update', json={'contact': contact_name, 'last_read': names['newest']}, headers=headers, timeout=20)
        assert update.status_code == 200, update.text[:300]
        assert get('inbox.view_state', {'contact': contact_name}).json()['message']['first_unread'] is None
        print('PASS HTTP view_state names the first unread message in thread order, none once read, and denies guests')

        expired_response = get('attachments.read', {'message': names['expired']})
        assert expired_response.status_code == 410, expired_response.status_code
        assert 'Media no longer available from WhatsApp' in expired_response.json()['_server_messages']
        busy_response = get('attachments.read', {'message': names['busy']})
        assert busy_response.status_code == 503 and 'Try again' in busy_response.json()['_server_messages']
        photo = get('attachments.read', {'message': names['recent']})
        assert photo.status_code == 200 and photo.headers['Content-Type'] == 'image/jpeg' and photo.content == b'local photo bytes'
        assert get('attachments.read', {'message': names['recent']}, auth=False).status_code in (401, 403)
        print('PASS HTTP media read: 410 with a readable reason for expired media, 503 retry for a busy Hub, bytes, guest denial')
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        connect()
        user = frappe.get_doc('User', user_name)
        user.api_key = None; user.api_secret = None; user.enabled = 0; user.save()
        frappe.db.set_value('Relay Channel', channel_name, 'enabled', 0)
        frappe.db.commit(); frappe.destroy()
