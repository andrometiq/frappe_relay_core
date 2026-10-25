"""Real loopback HTTP into Frappe for bulk campaign callbacks and campaign API denial.
Synthetic credentials only; the fixture user is disabled and the stored event removed afterwards.
Run from the bench sites folder: PYTHONPATH=<worktree>:<worktree>/tests CI=1 ../env/bin/python -B <this file>
"""
import hashlib, hmac, json, secrets, threading, time
from pathlib import Path
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler
import requests
import frappe
import frappe.app
from relay_core import bulk_campaigns, inbound
from relay_core.automation import projection
from relay_core.automation.service import internal_save

SITE = 'yrp.site'
frappe.init(site=SITE)
frappe.connect()
frappe.set_user('Administrator')
assert Path(inbound.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1]), 'Run with this checkout first on PYTHONPATH'
account = 'bulk-http-fixture'
secret, api_key, api_secret = secrets.token_hex(32), secrets.token_hex(12), secrets.token_hex(24)
email = 'relay-bulk-callback-fixture@example.invalid'
if frappe.db.exists('User', email):
    user = frappe.get_doc('User', email)
    user.update({'enabled': 1, 'api_key': api_key, 'api_secret': api_secret})
    user.save()
else:
    user = frappe.get_doc({'doctype': 'User', 'email': email, 'first_name': 'Bulk callback fixture', 'send_welcome_email': 0,
                           'roles': [{'role': 'Relay Hub Service'}], 'api_key': api_key, 'api_secret': api_secret}).insert()
manager_email = 'relay-bulk-manager-fixture@example.invalid'
manager_key, manager_secret = secrets.token_hex(12), secrets.token_hex(24)
if frappe.db.exists('User', manager_email):
    manager = frappe.get_doc('User', manager_email)
    manager.update({'enabled': 1, 'api_key': manager_key, 'api_secret': manager_secret})
    manager.save()
else:
    frappe.get_doc({'doctype': 'User', 'email': manager_email, 'first_name': 'Bulk manager fixture', 'send_welcome_email': 0,
                    'roles': [{'role': 'Relay Communication Manager'}], 'api_key': manager_key, 'api_secret': manager_secret}).insert()
channel = frappe.get_doc({'doctype': 'Relay Channel', 'channel': 'WhatsApp', 'account': account, 'enabled': 1}).insert()
title = 'Failed import check ' + secrets.choice(('cedar', 'maple', 'birch', 'willow'))
campaign = internal_save(frappe.get_doc({'doctype': 'Relay Campaign', 'title': title, 'channel': channel.name,
    'operation': 'templates.send', 'template_name': 'notice', 'language': 'en', 'status': 'Draft', 'account': account,
    'arguments': json.dumps({'template': {'name': 'notice'}, 'fields': []}), 'reply_window_hours': 72,
    'last_error': 'The first row must hold unique column names', 'request_key': 'bulk-http-' + secrets.token_hex(8)}), new=True)
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
base = f'http://127.0.0.1:{server.server_port}/api/method/'
rows = [{'id': i + 1, 'key': f'bulk-fixture-{i}', 'state': 'submitted', 'message_id': f'wamid.fixture.{i}',
         'status': 'read' if i % 2 else 'failed', 'updated_at': '2026-10-25T10:00:00Z',
         **({} if i % 2 else {'error': {'code': 131026, 'title': 'Message undeliverable', 'message': 'Not delivered'}})}
        for i in range(500)]


def send(data, auth=True, signature=True):
    raw = json.dumps(data, separators=(',', ':')).encode()
    stamp = str(int(time.time()))
    digest = hmac.new(secret.encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    headers = {'Content-Type': 'application/json', 'X-Relay-Timestamp': stamp, 'X-Relay-Signature': digest if signature else '0' * 64}
    if auth:
        headers['Authorization'] = f'token {api_key}:{api_secret}'
    return requests.post(base + 'relay_core.inbound.receive_bulk_updates', data=raw, headers=headers, timeout=20)


def stored():
    return frappe.db.count('Relay Hub Event', {'account': account})


try:
    settings = {'relay_hub_account': account, 'relay_callback_secret': secret}
    with patch.object(inbound, 'connection_value', side_effect=settings.get), patch.object(projection, 'on_event'):
        payload = {'account': account, 'updates': rows}
        started = time.perf_counter()
        for _ in range(2):
            response = send(payload)
            assert response.status_code == 200, (response.status_code, response.text[:300])
            assert response.json()['message'] == {'accepted': 500}, response.text[:300]
        elapsed = (time.perf_counter() - started) / 2
        frappe.db.rollback()
        assert stored() == 1, 'Replay must not store a second batch'
        event = frappe.get_all('Relay Hub Event', filters={'account': account}, fields=['payload'], limit_page_length=1)[0]
        assert json.loads(event.payload)['bulk_updates'][0]['error']['code'] == 131026
        for bad, auth, signature in [(payload, False, True), (payload, True, False), ({'account': 'other', 'updates': rows}, True, True),
                                     ({'account': account, 'updates': rows + [dict(rows[-1], id=501)]}, True, True),
                                     ({'account': account, 'updates': [dict(rows[0], state='sent')]}, True, True)]:
            response = send(bad, auth=auth, signature=signature)
            assert response.status_code in (401, 403), response.status_code
        frappe.db.rollback()
        assert stored() == 1
        headers = {'Authorization': f'token {api_key}:{api_secret}'}
        for method, data in (('relay_core.bulk_campaigns.create', {'title': 'Winter launch Oct 2026', 'template_name': 'notice', 'language': 'en'}),
                             ('relay_core.bulk_campaigns.control', {'name': 'Winter launch Oct 2026', 'action': 'start'})):
            for auth in (None, headers):
                response = requests.post(base + method, json=data, headers=auth or {}, timeout=20)
                assert response.status_code == 403, (method, response.status_code)
        response = requests.get(base + 'relay_core.bulk_campaigns.read', params={'name': 'Winter launch Oct 2026'}, headers=headers, timeout=20)
        assert response.status_code == 403, response.status_code
        manager_headers = {'Authorization': f'token {manager_key}:{manager_secret}'}
        with patch.object(bulk_campaigns, 'connection_value', side_effect=settings.get), \
                patch.object(bulk_campaigns.whatsapp, 'checked_client', side_effect=AssertionError('Hub must not be called')):
            response = requests.get(base + 'relay_core.bulk_campaigns.read', params={'name': title}, headers=manager_headers, timeout=20)
            assert response.status_code == 200, (response.status_code, response.text[:300])
            body = response.json()['message']
            assert {'status', 'last_error', 'issues', 'recipients', 'counts', 'next'} <= set(body), sorted(body)
            assert (body['status'], body['last_error']) == ('Draft', 'The first row must hold unique column names'), body
            response = requests.post(base + 'relay_core.bulk_campaigns.control', json={'name': title, 'action': 'start'},
                                     headers=manager_headers, timeout=20)
            assert response.status_code == 417 and 'last import failed' in response.text, (response.status_code, response.text[:300])
        frappe.db.rollback()
        assert frappe.db.get_value('Relay Campaign', title, 'status') == 'Draft'
    print(f'PASS bulk update HTTP: 500-row signed batch accepted in {elapsed * 1000:.0f} ms per call, replay stored once, '
          'unsigned/unauthenticated/foreign/oversized/invalid-state batches rejected without writes; campaign APIs deny guests and non-managers; '
          'a manager reads the campaign shape and cannot start it after a failed import')
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    frappe.db.rollback()
    for name in frappe.get_all('Relay Hub Event', filters={'account': account}, pluck='name'):
        frappe.delete_doc('Relay Hub Event', name, ignore_permissions=True, force=True)
    frappe.db.set_value('User', email, {'enabled': 0, 'api_key': None})
    frappe.db.set_value('User', manager_email, {'enabled': 0, 'api_key': None})
    frappe.delete_doc('Relay Campaign', title, ignore_permissions=True, force=True)
    frappe.delete_doc('Relay Channel', channel.name, ignore_permissions=True, force=True)
    frappe.db.commit()
    frappe.destroy()
