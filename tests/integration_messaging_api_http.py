"""Real loopback HTTP into Frappe for number-based WhatsApp sends and JSON-row campaigns, and the grouped bulk
projection on MariaDB. Hub is patched in this process; synthetic fixtures only, and nothing reaches WhatsApp.
Run from the bench sites folder: PYTHONPATH=<core>:<core>/tests CI=1 ../env/bin/python -B <this file>
"""
import json
import secrets
import threading
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch
from wsgiref.simple_server import WSGIRequestHandler, make_server
import requests
import frappe
import frappe.app
from site_labels import phone, run_label

SITE = 'yrp.site'
frappe.init(site=SITE)
frappe.connect()
frappe.set_user('Administrator')
from relay_core import (bulk_campaigns, bulk_timeline, bulk_updates, conversation_start, enrollment, messaging,
                        messaging_api, whatsapp)
from relay_core.permissions import sequential_name
assert Path(messaging_api.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1]), 'Run with this checkout first on PYTHONPATH'
assert frappe.db.exists('Relay Contact Type', {'business_doctype': 'Customer', 'enabled': 1}), 'Enable the Customer business type'

stamp = run_label()
account = 'api-' + stamp
known, unknown, other = phone(stamp + 'known'), phone(stamp + 'unknown'), phone(stamp + 'other')
TEMPLATE = {'name': 'order_ready', 'language': 'en', 'components': [{'type': 'BODY', 'text': 'Order {{1}} is ready'}]}


def user(label, roles):
    email = f'relay-api-{label}-{stamp.lower()}@example.invalid'
    key, secret = secrets.token_hex(12), secrets.token_hex(24)
    with patch('frappe.core.doctype.user.user.throttle_user_creation'):
        frappe.get_doc({'doctype': 'User', 'email': email, 'first_name': 'Relay API ' + label, 'send_welcome_email': 0,
                        'roles': [{'role': role} for role in roles], 'api_key': key, 'api_secret': secret}).insert()
    return email, {'Authorization': f'token {key}:{secret}'}


channel = frappe.get_doc({'doctype': 'Relay Channel', 'channel': 'WhatsApp', 'account': account, 'enabled': 1}).insert(
    set_name=sequential_name('channel'))
customer = frappe.get_doc({'doctype': 'Customer', 'customer_name': 'Sim API ' + stamp, 'customer_type': 'Company',
                           'customer_group': frappe.db.get_value('Customer Group', {'is_group': 0}, 'name'),
                           'territory': frappe.db.get_value('Territory', {'is_group': 0}, 'name')}).insert()
person = frappe.get_doc({'doctype': 'Contact', 'first_name': 'Sim API ' + stamp, 'phone_nos': [
    {'phone': '+' + known, 'is_primary_mobile_no': 1}], 'links': [{'link_doctype': 'Customer', 'link_name': customer.name}]}).insert()
relay = frappe.get_doc({'doctype': 'Relay Contact', 'contact': person.name, 'display_name': person.first_name}).insert()
frappe.get_doc({'doctype': 'Relay Contact Endpoint', 'channel': channel.name, 'relay_contact': relay.name,
                'endpoint': known, 'verified': 1}).insert()
frappe.get_doc({'doctype': 'Relay Message', 'relay_contact': relay.name, 'channel': channel.name, 'sender_endpoint': known,
                'direction': 'Incoming', 'content': 'Is order 25 ready?', 'status': 'Sent', 'business_doctype': 'Customer',
                'business_name': customer.name, 'provider_context': json.dumps({'provider': 'WhatsApp'})}).insert()
emails, headers = {}, {}
for label, roles in (('manager', ['Relay Communication Manager', 'Sales User']),
                     ('agent', ['Relay Communication User', 'Sales User']), ('outsider', ['Sales User'])):
    emails[label], headers[label] = user(label, roles)
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
hub = Mock()
hub.call_tool.side_effect = lambda tool, arguments: {'messages': [{'id': 'wamid.' + arguments['request_key'][:24]}]}


def post(method, who, **data):
    return requests.post(base + method, json=data, headers=headers.get(who, {}), timeout=30)


def get(method, who, **params):
    return requests.get(base + method, params=params, headers=headers.get(who, {}), timeout=30)


def ok(response):
    assert response.status_code == 200, (response.status_code, response.text[:400])
    return response.json()['message']


def refused(response, status, text=''):
    assert response.status_code == status and text in response.text, (response.status_code, response.text[:400])


def check_sends():
    text = 'relay_core.messaging_api.send_text'
    for who in ('guest', 'outsider', 'agent'):  # The agent is not assigned to this contact.
        refused(post(text, who, number=known, body='Order 25 is ready'), 403)
    sent = ok(post(text, 'manager', number=known, body='Order 25 is ready'))
    assert {'action', 'status', 'message', 'number', 'contact', 'key'} <= set(sent) and sent['status'] == 'Submitted', sent
    calls = hub.call_tool.call_count
    assert ok(post(text, 'manager', number='+' + known, body='Order 25 is ready'))['action'] == sent['action']
    assert hub.call_tool.call_count == calls, 'A repeat must not send again'
    keyed = ok(post(text, 'manager', number=known, body='Order 26 is ready', key='order-26-' + stamp[-6:]))
    refused(post(text, 'manager', number=known, body='Changed text', key='order-26-' + stamp[-6:]), 417, 'different content')
    frappe.db.rollback()
    message = frappe.get_doc('Relay Message', sent['message'])
    assert (message.business_doctype, message.business_name, message.direction) == ('Customer', customer.name, 'Outgoing')
    refused(post(text, 'manager', number=unknown, body='Hello'), 417, '24-hour reply window')
    media = ok(post('relay_core.messaging_api.send_media', 'manager', number=known, media_url='https://cdn.example/bill.pdf',
                    media_type='document', filename='bill.pdf'))
    refused(post('relay_core.messaging_api.send_media', 'manager', number=known, media_url='http://cdn.example/a.jpg',
                 media_type='image'), 417, 'HTTPS')
    return sent, keyed, media


def check_templates_and_lists():
    template = 'relay_core.messaging_api.send_template'
    refused(post(template, 'manager', number=unknown, template='order_ready', language='en', params=['25']), 417, 'business_doctype')
    refused(post(template, 'agent', number=unknown, template='order_ready', language='en', params=['25'],
                 business_doctype='Customer', business_name=customer.name), 403)
    created = ok(post(template, 'manager', number=unknown, template='order_ready', language='en', params=['25'],
                      business_doctype='Customer', business_name=customer.name))
    assert created['status'] == 'Submitted' and created['number'] == unknown, created
    assert ok(post(template, 'manager', number=unknown, template='order_ready', language='en', params=['25']))['action'] == created['action']
    refused(post(template, 'manager', number=known, template='order_ready', language='en', params=[]), 417, 'Missing')
    items = [{'type': 'text', 'number': known, 'body': 'List text'}, {'type': 'template', 'number': unknown,
             'template': 'order_ready', 'language': 'en', 'params': ['27']},
             {'type': 'text', 'number': other, 'body': 'Closed window'}, {'type': 'call', 'number': known}]
    calls = hub.call_tool.call_count
    queued = ok(post('relay_core.messaging_api.send_messages', 'manager', items=items))
    results = queued['results']
    assert [(row['ok'], row.get('status')) for row in results] == [(True, 'Pending'), (True, 'Pending'), (False, None), (False, None)], results
    assert '24-hour reply window' in results[2]['error'], results
    assert hub.call_tool.call_count == calls, 'A list send must not reach the Hub inside the request'
    job = next(call for call in frappe.enqueue.call_args_list if call.args[:1] == ('relay_core.messaging_api.deliver_batch',))
    assert (job.kwargs['queue'], job.kwargs['job_id'], job.kwargs['batch']) == ('long', 'relay-send-' + queued['batch'], queued['batch'])
    assert ok(post('relay_core.messaging_api.send_messages', 'manager', items=items))['batch'] == queued['batch']
    status = 'relay_core.messaging_api.send_status'
    assert {row['status'] for row in ok(get(status, 'manager', batch=queued['batch']))['results']} == {'Pending'}
    frappe.db.rollback()  # A worker starts with a fresh transaction.
    frappe.set_user(emails['manager'])
    messaging_api.deliver_batch(job.kwargs['batch'], job.kwargs['messages'])
    frappe.set_user('Administrator')
    assert hub.call_tool.call_count == calls + 2, hub.call_tool.call_count - calls
    assert [row['status'] for row in ok(get(status, 'manager', batch=queued['batch']))['results']] == ['Submitted', 'Submitted']
    refused(get(status, 'agent', batch=queued['batch']), 404)
    refused(post('relay_core.messaging_api.send_messages', 'manager', items=[items[0]] * 101), 417, '1-100')
    refused(post('relay_core.messaging_api.send_messages', 'outsider', items=items), 403)
    return created


def check_campaigns():
    create, title = 'relay_core.bulk_campaigns.create_with_rows', 'API rows ' + stamp[-12:]
    message = {'kind': 'photo', 'caption': 'Hi {{name}}'}
    rows = [{'phone': '+' + known, 'name': 'Asha', 'media_url': 'https://cdn.example/a.jpg'},
            {'phone': other, 'name': 'Ravi', 'media_url': 'http://cdn.example/b.jpg'},
            {'phone': known, 'name': 'Asha again', 'media_url': 'https://cdn.example/c.jpg'}]
    for who in ('guest', 'outsider', 'agent'):
        refused(post(create, who, title=title, message=message, rows=rows), 403)
    refused(post(create, 'manager', title=title, message=message, rows=rows * 1667), 417, '1-5000')
    frappe.db.rollback()
    assert not frappe.db.exists('Relay Campaign', title)
    body = ok(post(create, 'manager', title=title, message=message, rows=rows))
    assert {'status', 'counts', 'issues', 'recipients', 'mapping'} <= set(body) and body['status'] == 'Draft', body
    assert [(row['status'], row['reason']) for row in body['recipients']] == [
        ('Pending', ''), ('Skipped', 'Photo link must be an HTTPS link'), ('Skipped', 'Duplicate number')], body['recipients']
    more = ok(post('relay_core.bulk_campaigns.append_rows', 'manager', name=title,
                   rows=[{'phone': unknown, 'name': 'New', 'media_url': 'https://cdn.example/d.jpg'}, rows[0]]))
    assert [(row['sheet_row'], row['status']) for row in more['recipients']][3:] == [(4, 'Pending'), (5, 'Skipped')], more
    refused(post('relay_core.bulk_campaigns.append_rows', 'agent', name=title, rows=rows), 403)
    return title


def check_projection(title):
    """500 rows in three statuses: three recipient UPDATEs, and a replay changes nothing."""
    keys = [f'api-projection-{stamp}-{i}' for i in range(500)]
    now = frappe.utils.now()
    frappe.db.bulk_insert('Relay Campaign Recipient', ('name', 'creation', 'modified', 'owner', 'modified_by', 'campaign',
                          'recipient_key', 'request_key', 'status', 'destination', 'sheet_row', 'reason'),
                          [(key, now, now, 'Administrator', 'Administrator', title, key, key, 'Queued', '91' + str(9000000000 + i),
                            1000 + i, '') for i, key in enumerate(keys)])
    frappe.db.commit()
    statuses = ('read', 'delivered', 'failed')
    rows = [{'id': i + 1, 'key': key, 'state': 'submitted', 'message_id': f'wamid.projection.{i}', 'status': statuses[i % 3],
             **({'error': {'code': 131026, 'title': 'Message undeliverable'}} if i % 3 == 2 else {})} for i, key in enumerate(keys)]
    event = frappe._dict(name='projection-' + stamp, account=account)
    statements = []
    real = frappe.db.sql

    def counted(query, *args, **kwargs):
        statements.append(str(query))
        return real(query, *args, **kwargs)

    def snapshot():
        return frappe.db.sql('''SELECT name, status, modified, provider_id, delivery_id, error_code, reason
            FROM `tabRelay Campaign Recipient` WHERE request_key IN %s ORDER BY name''', (tuple(keys),))

    with patch.object(frappe.db, 'sql', side_effect=counted), patch.object(frappe.db, 'set_value'):
        bulk_updates.project_batch(event, rows)
    frappe.db.commit()
    updates = [query for query in statements if 'UPDATE `tabRelay Campaign Recipient`' in query]
    assert len(updates) == 3 and len(statements) <= 6, (len(updates), len(statements))
    first = snapshot()
    counts = frappe.db.sql('''SELECT status, COUNT(*), SUM(error_code=131026), SUM(provider_id LIKE 'wamid.projection.%%')
        FROM `tabRelay Campaign Recipient` WHERE request_key IN %s GROUP BY status ORDER BY status''', (tuple(keys),))
    assert [(status, *map(int, numbers)) for status, *numbers in counts] == [
        ('Delivered', 167, 0, 167), ('Failed', 166, 166, 166), ('Read', 167, 0, 167)], counts
    with patch.object(frappe.db, 'set_value'):
        bulk_updates.project_batch(event, rows)
        bulk_updates.project_batch(event, [dict(row, status='sent') for row in rows])  # Older news cannot move a row back.
    frappe.db.commit()
    assert snapshot() == first, 'A replay or older status must not change any row'
    return len(statements)


def check_timeline(sent):
    """The grouped timeline UPDATE moves a sent message forward and never back."""
    key = frappe.db.get_value('Relay Message', sent['message'], 'source_key')
    bulk_timeline.apply([{'key': key, 'status': 'Read', 'message_id': 'wamid.timeline.' + stamp[-6:], 'reason': ''}])
    bulk_timeline.apply([{'key': key, 'status': 'Failed', 'message_id': '', 'reason': 'Late failure'}])
    frappe.db.commit()
    row = frappe.db.get_value('Relay Message', sent['message'], ['status', 'provider_id', 'delivery_error'], as_dict=True)
    assert (row.status, row.provider_id, row.delivery_error or '') == ('Read', 'wamid.timeline.' + stamp[-6:], ''), row


campaign = None
try:
    with ExitStack() as stack:
        for module in (whatsapp, conversation_start, messaging, enrollment, bulk_campaigns, bulk_updates):
            stack.enter_context(patch.object(module, 'connection_value', return_value=account))
        stack.enter_context(patch.object(whatsapp, 'client', return_value=hub))
        stack.enter_context(patch('relay_core.whatsapp_templates.definition', return_value=TEMPLATE))
        stack.enter_context(patch.object(frappe, 'enqueue'))
        stack.enter_context(patch.object(frappe, 'publish_realtime'))
        stack.enter_context(patch('relay_core.automation.queue.wake'))
        sent, keyed, media = check_sends()
        check_templates_and_lists()
        campaign = check_campaigns()
        statements = check_projection(campaign)
        check_timeline(sent)
    print(f'PASS messaging API HTTP: text/media/template sends return action shape, list sends queue one job and report per-item status, repeat and keyed sends are one message, '
          f'guests, outsiders and unassigned agents get 403, closed windows and bad links 417; an unknown number gets a Contact '
          f'only from a manager with a business; JSON campaigns skip bad links and duplicates, refuse 5001 rows and non-managers, '
          f'and append numbers on; 500 bulk updates took {statements} statements (3 UPDATEs) and replays changed nothing')
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    frappe.db.rollback()
    if campaign:
        frappe.db.delete('Relay Campaign Recipient', {'campaign': campaign})
        frappe.delete_doc('Relay Campaign', campaign, ignore_permissions=True, force=True)
    for email in emails.values():
        frappe.db.set_value('User', email, {'enabled': 0, 'api_key': None})
    frappe.db.set_value('Relay Channel', channel.name, 'enabled', 0)
    frappe.db.commit()
    frappe.destroy()
