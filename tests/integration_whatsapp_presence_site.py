"""WhatsApp read receipts and typing on yrp.site: real reads, permissions, Redis leases and HTTP; the Hub is faked."""
import json
import secrets
import threading
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler

import requests
import frappe
import frappe.app
from channel_site_fixtures import init, user
from channel_identity_fixtures import scenario, configured, endpoint
from relay_core import business_inbox, inbox, message_reads, whatsapp, whatsapp_presence

site = init()


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


def application(environ, start_response):
    environ['HTTP_X_FRAPPE_SITE_NAME'] = site
    environ['HTTP_HOST'] = '127.0.0.1:8001'
    return frappe.app.application(environ, start_response)


def credential(actor):
    doc = frappe.get_doc('User', actor); doc.api_key = secrets.token_hex(12); secret = secrets.token_hex(24)
    doc.api_secret = secret; doc.save(ignore_permissions=True)
    return {'Authorization': 'token ' + doc.api_key + ':' + secret}


def queued():
    return [call.kwargs for call in frappe.enqueue.call_args_list if call.args and call.args[0] == 'relay_core.whatsapp_presence.send']


def incoming(fixture, binding, identifier, context=None):
    return frappe.get_doc({'doctype': 'Relay Message', 'relay_contact': fixture.contact.name, 'channel': binding.channel,
        'sender_endpoint': binding.endpoint, 'direction': 'Incoming', 'content': 'Quantity 25', 'message_type': 'text',
        'status': 'Sent', 'provider_id': identifier, 'business_doctype': fixture.customer.doctype, 'business_name': fixture.customer.name,
        'provider_context': json.dumps(context or {'provider': 'WhatsApp', 'message_id': identifier})}).insert().name


server = None
try:
    fixture = scenario()
    outsider = user('relay-presence-outsider-' + fixture.stamp + '@example.invalid')
    with configured(fixture), patch.object(whatsapp_presence, 'connection_value', return_value=fixture.account), \
         patch.object(whatsapp, 'client') as client:
        binding = endpoint(fixture, 'WhatsApp', '919555000777')
        older, newest = 'wamid.presence-old-' + fixture.stamp, 'wamid.presence-new-' + fixture.stamp
        names = [incoming(fixture, binding, older), incoming(fixture, binding, newest)]
        group = incoming(fixture, binding, 'wamid.presence-group-' + fixture.stamp, {'provider': 'WhatsApp', 'group_id': 'G' + fixture.stamp})
        expired = incoming(fixture, binding, 'wamid.presence-expired-' + fixture.stamp)
        frappe.db.set_value('Relay Message', expired, 'creation', frappe.utils.add_days(frappe.utils.now_datetime(), -31), update_modified=False)
        frappe.db.commit()
        frappe.set_user(fixture.actor)

        frappe.enqueue.reset_mock()
        message_reads.mark(fixture.contact.name, [group, expired])
        assert not queued(), 'Group or expired message got a read receipt'
        assert message_reads.mark(fixture.contact.name, names)['marked'] == names
        message_reads.mark(fixture.contact.name, names)
        assert queued() == [{'queue': 'short', 'job_id': 'relay-whatsapp-read:' + names[1], 'deduplicate': True,
                             'message_id': newest, 'typing': False}], queued()

        frappe.enqueue.reset_mock()
        with patch.object(whatsapp_presence, 'mark_read', side_effect=ConnectionError('Redis unavailable')), patch.object(frappe, 'log_error') as logged:
            assert message_reads.mark(fixture.contact.name, names[:1])['marked'] == names[:1]
        logged.assert_called_once()

        frappe.set_user('Administrator')
        frappe.db.set_single_value('Relay Settings', 'send_whatsapp_read_receipts', 0); frappe.db.commit()
        frappe.set_user(fixture.actor)
        try:
            frappe.cache.delete_value('relay-whatsapp-read:' + fixture.contact.name + ':' + names[1])
            message_reads.mark(fixture.contact.name, names)
            assert not queued(), 'Read receipt sent while switched off'
        finally:
            frappe.set_user('Administrator')
            frappe.db.set_single_value('Relay Settings', 'send_whatsapp_read_receipts', 1); frappe.db.commit()
            frappe.set_user(fixture.actor)

        frappe.enqueue.reset_mock()
        inbox.typing(fixture.contact.name, message=names[0]); inbox.typing(fixture.contact.name, message=names[0])
        assert queued() == [{'queue': 'short', 'job_id': 'relay-whatsapp-read:' + names[1] + ':typing', 'deduplicate': True,
                             'message_id': newest, 'typing': True}], queued()
        frappe.enqueue.reset_mock()
        inbox.typing(fixture.contact.name, active=0, message=names[0])
        assert not queued()

        frappe.cache.delete_value('relay-whatsapp-typing:' + fixture.contact.name)
        business_inbox.typing(fixture.customer.doctype, fixture.customer.name, fixture.contact.name, message=names[0])
        assert [row['typing'] for row in queued()] == [True], queued()

        whatsapp_presence.send(newest, typing=True)
        client.return_value.execute.assert_called_once_with({'operation': 'messages.read', 'message_id': newest, 'typing': True})

        frappe.enqueue.reset_mock(); frappe.set_user(outsider)
        for denied in (lambda: message_reads.mark(fixture.contact.name, names), lambda: inbox.typing(fixture.contact.name, message=names[0])):
            try: denied()
            except frappe.PermissionError: pass
            else: raise AssertionError('Outsider reached a WhatsApp read signal')
        assert not queued()
        frappe.set_user('Administrator')

        headers = {fixture.actor: credential(fixture.actor), outsider: credential(outsider)}; frappe.db.commit()
        server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}/api/method/relay_core.'
        mark = lambda actor: requests.post(base + 'message_reads.mark', headers=headers[actor],
            json={'contact': fixture.contact.name, 'messages': names}, timeout=30)
        response = mark(fixture.actor)
        assert response.status_code == 200 and response.json()['message'] == {'marked': names}, response.text
        assert mark(outsider).status_code == 403
        response = requests.post(base + 'inbox.typing', headers=headers[outsider], json={'contact': fixture.contact.name, 'message': names[0]}, timeout=30)
        assert response.status_code == 403, response.text
    print('PASS WhatsApp read receipt and typing: newest message, leases, setting off, Hub-safe mark, deny and HTTP')
finally:
    if server: server.shutdown()
    frappe.destroy()
