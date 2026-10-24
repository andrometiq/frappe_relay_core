"""Synthetic Telegram/Email callbacks through real Frappe/PostgreSQL and HTTP MCP.

Run using the isolated Frappe environment, never a shared or production site::

    PYTHONPATH=$PWD RELAY_AUTOMATION_TEST_SITES=$PWD/.runtime/automation-bench/sites \
      /path/to/frappe/env/bin/python tests/integration_channels_site.py

Requires Redis on the isolated site's configured port. Provider decisions are
deterministic fixtures; HubClient performs its real HTTP handshake and send
against a loopback MCP simulator. No provider credentials or external delivery.
Synthetic records are retained in the isolated database for inspection.
"""
from site_labels import run_label

from contextlib import contextmanager
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from unittest.mock import patch


SITES = os.environ.get('RELAY_AUTOMATION_TEST_SITES')
if not SITES:
    raise SystemExit('Set RELAY_AUTOMATION_TEST_SITES to the isolated automation test sites directory')
EXPECTED_SITES = Path(__file__).resolve().parents[1] / '.runtime/automation-bench/sites'
if Path(SITES).resolve() != EXPECTED_SITES.resolve():
    raise SystemExit('Refusing a sites directory outside this repository\'s isolated test fixture')
os.chdir(SITES)

import frappe
from relay_core import settings as connection_settings
# Fixture transports and signatures use process-local synthetic configuration.
# Never replace the installed review site's encrypted connection credentials.
fixture_connection = patch.object(connection_settings, 'value', side_effect=lambda key: frappe.conf.get(key))
fixture_connection.start()
from frappe.permissions import add_permission
from werkzeug.wrappers import Request
from relay_core import api, inbound, tickets, whatsapp
from relay_core.automation import projection, service
from relay_core.automation.contracts import action_key
from relay_core.hub import HubClient


SITE = 'relay-ai-test.local'
frappe.init(site=SITE)
assert frappe.conf.db_name == 'relay_ai_test_20260922', 'Refusing a non-test database'
assert frappe.conf.db_host in ('127.0.0.1', 'localhost'), 'Refusing a remote database'
frappe.connect()
frappe.set_user('Administrator')
frappe.flags.mute_emails = True
frappe.conf.relay_automation_enabled = 1
# The fixture predates the installed framework's User-role audit metadata.
# Reload only missing metadata here, after both site-path and database guards.
for _name, _module in [('Permission Log', 'permission_log'), ('User Role Profile', 'user_role_profile')]:
    if not frappe.db.exists('DocType', _name):
        frappe.reload_doc('core', 'doctype', _module, force=True)
if not frappe.get_meta('User').has_field('role_profiles'):
    frappe.reload_doc('core', 'doctype', 'user', force=True)
if not frappe.get_meta('Relay Message').has_field('message_data') or not frappe.get_meta('Relay Message').has_field('provider_message_key'):
    frappe.reload_doc('relay_core', 'doctype', 'relay_message', force=True)
    frappe.db.add_index('Relay Message', ['conversation_key', 'name'], 'relay_conversation_history')
if not frappe.get_meta('Relay Automation Run').has_field('message_hash'):
    frappe.reload_doc('relay_core', 'doctype', 'relay_automation_run', force=True)
frappe.db.commit()

RUN = run_label()
ACCOUNT = 'channels-sim-' + RUN
SECRET = 'synthetic-callback-secret-' + RUN
TOKEN = 'synthetic-hub-token-' + RUN + '-not-valid-externally'
frappe.conf.relay_hub_account = ACCOUNT
frappe.conf.relay_callback_secret = SECRET
EXECUTOR = 'channels-executor@example.invalid'
CALLBACK_USER = 'channels-callback@example.invalid'
DENIED_USER = 'channels-denied@example.invalid'
BUSINESS_DOCTYPE = 'Relay Channel Simulation Business'
PASSED = []


def passed(label):
    PASSED.append(label)
    print('PASS ' + label, flush=True)


def user(email, role):
    if not frappe.db.exists('User', email):
        frappe.get_doc(dict(doctype='User', email=email, first_name='Synthetic channels',
                            send_welcome_email=0, role_profiles=[], roles=[dict(role=role)])).insert()


for email, role in [(EXECUTOR, 'Relay Communication Manager'),
                    (CALLBACK_USER, 'Relay Hub Service'),
                    (DENIED_USER, 'Relay Communication User')]:
    user(email, role)
add_permission('Contact', 'Relay Communication Manager', 0)
if not frappe.db.exists('DocType', BUSINESS_DOCTYPE):
    frappe.get_doc(dict(doctype='DocType', name=BUSINESS_DOCTYPE, module='Relay Core', custom=1,
        autoname='field:title', fields=[dict(fieldname='title', label='Title', fieldtype='Data', reqd=1)],
        permissions=[dict(role='Relay Communication Manager', read=1),
                     dict(role='System Manager', read=1, write=1, create=1)])).insert()
if not frappe.db.exists('Relay Contact Type', {'business_doctype': BUSINESS_DOCTYPE}):
    frappe.get_doc(dict(doctype='Relay Contact Type', business_doctype=BUSINESS_DOCTYPE, enabled=1)).insert()
business = frappe.get_doc(dict(doctype=BUSINESS_DOCTYPE, title='Channels Synthetic ' + RUN)).insert()
other_business = frappe.get_doc(dict(doctype=BUSINESS_DOCTYPE, title='Channels Other ' + RUN)).insert()
contact = frappe.get_doc(dict(doctype='Contact', first_name='Channels synthetic ' + RUN,
    email_ids=[dict(email_id='channels-' + RUN + '@example.invalid', is_primary=1)],
    links=[dict(link_doctype=BUSINESS_DOCTYPE, link_name=business.name)])).insert()
relay_contact = frappe.get_doc(dict(doctype='Relay Contact', contact=contact.name,
    display_name='Channels simulation ' + RUN, automation_generation=1)).insert()
provider = frappe.get_doc(dict(doctype='Relay AI Provider', provider='OpenRouter',
    model='synthetic-model', api_key='synthetic-key-never-used', enabled=1)).insert()
fixtures = {}
for medium, endpoint in [('Telegram', '-100123456'), ('Email', contact.email_id)]:
    channel = frappe.get_doc(dict(doctype='Relay Channel', channel=medium, account=ACCOUNT, enabled=1)).insert()
    endpoint_doc = frappe.get_doc(dict(doctype='Relay Contact Endpoint', channel=channel.name,
        endpoint=endpoint, relay_contact=relay_contact.name, verified=1)).insert()
    reply = frappe.get_doc(dict(doctype='Relay Canned Reply', title='Synthetic acknowledgement ' + RUN,
        channel=medium, language='Tamil', body='வணக்கம். எங்கள் குழு உதவும்.',
        ai_enabled=1, published=1)).insert()
    policy = frappe.get_doc(dict(doctype='Relay Automation Policy', channel=channel.name,
        provider=provider.name, execution_user=EXECUTOR, enabled=1, mode='Automatic',
        allow_ticket=1, allow_reply=1, business_doctype=BUSINESS_DOCTYPE, daily_limit=100,
        reply_ids=reply.name, fallback_reply=reply.name)).insert()
    fixtures[medium] = dict(channel=channel, endpoint=endpoint, endpoint_doc=endpoint_doc,
                            reply=reply, policy=policy)
frappe.db.commit()


class MCPHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        pass

    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            assert 0 < size < 65536, 'Unexpected MCP request size'
            payload = json.loads(self.rfile.read(size))
            assert self.path == '/mcp', self.path
            assert self.headers.get('Authorization') == 'Bearer ' + TOKEN, 'Missing token'
            assert payload['jsonrpc'] == '2.0', 'Invalid JSON-RPC envelope'
            method = payload['method']
            if method == 'initialize':
                assert payload['params']['protocolVersion'] == '2025-06-18'
                result = dict(protocolVersion='2025-06-18', capabilities={'tools': {}},
                              serverInfo={'name': 'synthetic-relay-hub', 'version': 'test'})
            elif method == 'notifications/initialized':
                self.send_response(202)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            else:
                assert method == 'tools/call', method
                assert self.headers.get('MCP-Protocol-Version') == '2025-06-18'
                name = payload['params']['name']
                assert name in ('telegram.message', 'email.send'), name
                self.server.submissions.append(payload['params'])
                if self.server.reject:
                    result = {'isError': True, 'content': [{'type': 'text', 'text': 'Synthetic rejection'}]}
                else:
                    result = {'structuredContent': {'accepted': 1, 'provider_id': 'simulated-reply'}}
            raw = json.dumps({'jsonrpc': '2.0', 'id': payload['id'], 'result': result}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except Exception as exc:
            self.server.failures.append(str(exc))
            self.send_response(500)
            self.send_header('Content-Length', '0')
            self.end_headers()


server = ThreadingHTTPServer(('127.0.0.1', 0), MCPHandler)
server.submissions, server.failures, server.reject = [], [], False
server.daemon_threads = True
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
client = HubClient(f'http://127.0.0.1:{server.server_port}/mcp', TOKEN)
event_number = 0


def payload(medium, provider_id=None, sender=None, **changes):
    fixture = fixtures[medium]
    value = dict(channel=medium, direction='inbound', provider_id=provider_id or 'synthetic-' + str(time.time_ns()),
                 sender=sender or fixture['endpoint'], recipient='synthetic-account',
                 body='என் கட்டணத்தை சரிபார்க்க உதவுங்கள்.', occurred_at='2026-09-23T00:00:00Z')
    value.update(changes)
    if medium == 'Telegram':
        update_id = int(time.time_ns() % 1_000_000_000)
        value['provider_id'] = str(update_id)
        value['payload'] = {'update_id': update_id, 'message': {'message_id': update_id,
            'chat': {'id': int(value['sender']), 'type': 'supergroup' if int(value['sender']) < 0 else 'private'},
            'from': {'id': 123456, 'is_bot': False}, 'text': value['body']}}
    return value


@contextmanager
def request_context(events, *, account=ACCOUNT, actor=CALLBACK_USER, valid_signature=True, age=0):
    raw = json.dumps({'account': account, 'events': events}, ensure_ascii=False).encode()
    timestamp = str(int(time.time()) - age)
    signature = hmac.new(SECRET.encode(), timestamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    old_request, old_user = getattr(frappe.local, 'request', None), frappe.session.user
    frappe.local.request = Request.from_values(method='POST', data=raw, content_type='application/json',
        headers={'X-Relay-Timestamp': timestamp, 'X-Relay-Signature': signature if valid_signature else '0' * 64})
    frappe.set_user(actor)
    try:
        yield
    finally:
        frappe.local.request = old_request
        frappe.set_user(old_user)


def receive(events, **options):
    with request_context(events, **options), patch.object(frappe, 'enqueue'), patch.object(frappe, 'publish_realtime'):
        result = inbound.receive()
    frappe.db.commit()
    return result


def store(value, event_id=None):
    global event_number
    event_number += 1
    event = {'id': event_id or event_number, 'payload': value}
    assert receive([event]) == {'accepted': 1}
    key = f"{ACCOUNT}:{value['channel']}:{event['id']}"
    return event, frappe.db.get_value('Relay Hub Event', {'event_key': key}, 'name')


def project(name):
    with patch.object(frappe, 'enqueue'):
        projection.project(name)
    frappe.db.commit()
    return frappe.db.get_value('Relay Hub Event', name, 'projection_status')


def get_message(value):
    fixture = fixtures[value['channel']]
    return frappe.db.get_value('Relay Message', {'provider_id': value['provider_id'],
                                                'channel': fixture['channel'].name}, 'name')


def automate(message, medium):
    run_name = frappe.db.get_value('Relay Automation Run', {'message': message}, 'name')
    assert run_name, 'Projection did not create an automation run'
    decision = dict(category='Payment evidence', brief='Synthetic payment query', create_ticket=True,
                    reply=fixtures[medium]['reply'].name, handoff=False)
    with patch.object(service, 'complete', return_value=decision) as model, patch.object(frappe, 'enqueue'):
        service.process(run_name)
    return frappe.get_doc('Relay Automation Run', run_name), model.call_count


def prepare(medium):
    value = payload(medium)
    event, name = store(value)
    assert project(name) == 'Projected'
    message = get_message(value)
    run, calls = automate(message, medium)
    assert (run.status, calls) == ('Completed', 1), (run.status, run.reason, calls)
    outbox = frappe.db.get_value('Relay Automation Outbox', {'run': run.name}, 'name')
    assert outbox
    return value, event, name, message, run, outbox


def dispatch(outbox):
    with patch.object(whatsapp, 'client', return_value=client):
        service.dispatch(outbox)
    assert not server.failures, server.failures
    return frappe.db.get_value('Relay Automation Outbox', outbox, 'status')


def denied_callback(events, label, **options):
    before = frappe.db.count('Relay Hub Event', {'account': ACCOUNT})
    try:
        receive(events, **options)
    except (frappe.PermissionError, frappe.ValidationError):
        frappe.db.rollback()
    else:
        raise AssertionError(label + ' was accepted')
    assert frappe.db.count('Relay Hub Event', {'account': ACCOUNT}) == before
    passed(label)


try:
    # Each channel traverses the real callback verifier, journal, projection,
    # permissions, ticket/outbox transactions and HubClient HTTP implementation.
    for medium in fixtures:
        value, event, event_name, message, run, outbox = prepare(medium)
        ticket = frappe.get_doc('Relay Ticket', run.ticket)
        assert [row.message for row in ticket.messages] == [message]
        doc = frappe.get_doc('Relay Message', message)
        assert doc.relay_contact == relay_contact.name and doc.content == value['body']
        before = len(server.submissions)
        assert dispatch(outbox) == 'Submitted'
        assert dispatch(outbox) == 'Submitted'
        assert len(server.submissions) == before + 1
        sent = server.submissions[-1]
        assert sent['name'] == ('telegram.message' if medium=='Telegram' else 'email.send')
        if medium == 'Telegram':
            assert sent['arguments'] == {'operation':'text', 'chat_id': int(fixtures[medium]['endpoint']),
                                         'text': fixtures[medium]['reply'].body,
                                         'reply_to': value['payload']['message']['message_id'], 'request_key':frappe.db.get_value('Relay Automation Outbox',outbox,'action_key')}
        else:
            assert sent['arguments'] == {'to': [fixtures[medium]['endpoint']], 'subject': 'Reply',
                                         'body': fixtures[medium]['reply'].body, 'cc': [], 'bcc': [], 'request_key':frappe.db.get_value('Relay Automation Outbox',outbox,'action_key')}
        assert receive([event]) == {'accepted': 1}
        assert project(event_name) == 'Projected'
        duplicate_event, duplicate_name = store(value)
        assert project(duplicate_name) == 'Projected'
        assert frappe.db.count('Relay Message', {'provider_id': value['provider_id'], 'channel': fixtures[medium]['channel'].name}) == 1
        assert frappe.db.count('Relay Automation Run', {'message': message}) == 1
        assert frappe.db.count('Relay Ticket', {'source_action_key': action_key(message, 'ticket')}) == 1
        assert frappe.db.count('Relay Automation Outbox', {'run': run.name}) == 1
        passed(medium + ': signed callback → projection → ticket → HTTP MCP reply; replay is idempotent')
        denied_callback([dict(event, payload=dict(value, body='Conflicting payload'))], medium + ': conflicting event payload rejected')

    same_id = 999999
    identities = []
    for medium in fixtures:
        _, name = store(payload(medium), same_id)
        identities.append(name)
    assert len(set(identities)) == 2
    passed('Telegram and Email event IDs are isolated within one account')

    sample = [{'id': 999998, 'payload': payload('Telegram')}]
    denied_callback(sample, 'invalid callback signature rejected', valid_signature=False)
    denied_callback(sample, 'expired callback rejected', age=301)
    denied_callback(sample, 'foreign account callback rejected', account='foreign-synthetic-account')
    denied_callback(sample, 'communication user cannot impersonate Hub callback', actor=DENIED_USER)
    denied_callback([{'id': 100000 + i, 'payload': payload('Telegram')} for i in range(51)],
                    'callback batches above 50 rejected without partial persistence')
    batch = [{'id': 110000 + i, 'payload': payload('Telegram', sender='777777777')} for i in range(50)]
    count = frappe.db.count('Relay Hub Event', {'account': ACCOUNT})
    assert receive(batch) == {'accepted': 50}
    assert receive(batch) == {'accepted': 50}
    assert frappe.db.count('Relay Hub Event', {'account': ACCOUNT}) == count + 50
    passed('50-event callback boundary persists once across retry')
    conflict = dict(batch[0], payload=dict(batch[0]['payload'], body='Conflicting second item'))
    denied_callback([{'id': 120000, 'payload': payload('Telegram')}, conflict],
                    'a conflict rolls back the entire callback batch')

    for medium in fixtures:
        value = payload(medium, direction='outbound')
        _, name = store(value)
        assert project(name) == 'Ignored'
        assert not get_message(value)
        passed(medium + ': outbound callback does not echo into incoming automation')

        value = payload(medium, body={'unexpected': 'object'})
        _, name = store(value)
        assert project(name) == 'Failed'
        assert not get_message(value)
        passed(medium + ': malformed normalized body is retained as failed without a message')

        # Unknown endpoints are retained for reconciliation, never automatically
        # granted the rights of a matching-looking business record.
        unknown = '123456789' if medium == 'Telegram' else 'unknown-' + RUN + '@example.invalid'
        value = payload(medium, sender=unknown)
        _, name = store(value)
        assert project(name) == 'Uncategorized'
        assert not get_message(value)
        frappe.get_doc(dict(doctype='Relay Contact Endpoint', channel=fixtures[medium]['channel'].name,
            endpoint=unknown, relay_contact=relay_contact.name, verified=1)).insert()
        frappe.db.commit()
        assert project(name) == 'Projected'
        assert get_message(value)
        assert project(name) == 'Projected'
        assert frappe.db.count('Relay Message', {'provider_id': value['provider_id'], 'channel': fixtures[medium]['channel'].name}) == 1
        passed(medium + ': unknown endpoint quarantined and explicit verified mapping recovers once')

        value = payload(medium)
        _, name = store(value)
        assert project(name) == 'Projected'
        endpoint = fixtures[medium]['endpoint_doc']
        endpoint.reload(); endpoint.verified = 0; endpoint.save(); frappe.db.commit()
        run, calls = automate(get_message(value), medium)
        assert (run.status, calls) == ('Handoff', 0), (run.status, calls)
        assert not run.ticket and not frappe.db.exists('Relay Automation Outbox', {'run': run.name})
        endpoint.reload(); endpoint.verified = 1; endpoint.save(); frappe.db.commit()
        passed(medium + ': revoked endpoint blocks inference, ticket creation and delivery')

        _, _, _, _, run, outbox = prepare(medium)
        endpoint.reload(); endpoint.verified = 0; endpoint.save(); frappe.db.commit()
        count = len(server.submissions)
        assert dispatch(outbox) == 'Cancelled'
        assert len(server.submissions) == count
        endpoint.reload(); endpoint.verified = 1; endpoint.save(); frappe.db.commit()
        passed(medium + ': endpoint revoked after decision cancels delivery')

        _, _, _, _, run, outbox = prepare(medium)
        server.reject = True
        count = len(server.submissions)
        assert dispatch(outbox) == 'Uncertain'
        assert dispatch(outbox) == 'Uncertain'
        assert len(server.submissions) == count + 1
        server.reject = False
        passed(medium + ': failed MCP reply is retained and not blindly resent')

        _, _, _, _, run, outbox = prepare(medium)
        service.takeover(relay_contact.name); frappe.db.commit()
        count = len(server.submissions)
        assert dispatch(outbox) == 'Cancelled'
        assert len(server.submissions) == count
        service.takeover(relay_contact.name, 0); frappe.db.commit()
        passed(medium + ': human takeover cancels queued reply')

        _, _, _, _, run, outbox = prepare(medium)
        reply = fixtures[medium]['reply']
        reply.reload(); reply.published = 0; reply.save(); frappe.db.commit()
        count = len(server.submissions)
        assert dispatch(outbox) == 'Cancelled'
        assert len(server.submissions) == count
        reply.reload(); reply.published = 1; reply.save(); frappe.db.commit()
        passed(medium + ': unpublished canned reply cannot be delivered')

        # These are actual configuration changes after inference, not mocked
        # authorization methods. The dispatcher must recheck at send time.
        _, _, _, _, run, outbox = prepare(medium)
        channel = fixtures[medium]['channel']
        channel.reload(); channel.enabled = 0; channel.save(); frappe.db.commit()
        count = len(server.submissions)
        status = dispatch(outbox)
        channel.reload(); channel.enabled = 1; channel.save(); frappe.db.commit()
        assert status == 'Cancelled' and len(server.submissions) == count, (medium, 'disabled channel was sent', status)
        passed(medium + ': channel disabled after decision cancels delivery')

        _, _, _, _, run, outbox = prepare(medium)
        contact.reload(); contact.links = []; contact.save(); frappe.db.commit()
        count = len(server.submissions)
        status = dispatch(outbox)
        contact.reload(); contact.append('links', dict(link_doctype=BUSINESS_DOCTYPE, link_name=business.name)); contact.save(); frappe.db.commit()
        assert status == 'Cancelled' and len(server.submissions) == count, (medium, 'revoked business link was sent', status)
        passed(medium + ': business link revoked after decision cancels delivery')

        _, _, _, _, run, outbox = prepare(medium)
        contact.reload(); contact.links[0].link_name = other_business.name; contact.save(); frappe.db.commit()
        count = len(server.submissions)
        status = dispatch(outbox)
        contact.reload(); contact.links[0].link_name = business.name; contact.save(); frappe.db.commit()
        assert status == 'Cancelled' and len(server.submissions) == count, (medium, 'changed business link was sent', status)
        passed(medium + ': replacing business A with B cannot send an acknowledgement authorized for A')

        _, _, _, _, run, outbox = prepare(medium)
        permission = frappe.db.get_value('DocPerm', {'parent': BUSINESS_DOCTYPE,
            'role': 'Relay Communication Manager'}, 'name')
        assert permission
        frappe.db.set_value('DocPerm', permission, 'read', 0)
        frappe.clear_cache(doctype=BUSINESS_DOCTYPE); frappe.db.commit()
        try:
            assert not frappe.has_permission(BUSINESS_DOCTYPE, 'read', doc=business, user=EXECUTOR)
            count = len(server.submissions)
            status = dispatch(outbox)
            assert status == 'Cancelled' and len(server.submissions) == count, (medium, 'business permission revocation was ignored', status)
        finally:
            frappe.set_user('Administrator')
            frappe.db.set_value('DocPerm', permission, 'read', 1)
            frappe.clear_cache(doctype=BUSINESS_DOCTYPE); frappe.db.commit()
        passed(medium + ': revoked business read permission cancels an already decided reply')

    frappe.set_user(EXECUTOR)
    expected = frappe.get_list('Relay Message', filters={'relay_contact': relay_contact.name},
        fields=['name', 'channel'], order_by='name asc', page_length=1000)
    assert len(expected) > 6 and {row.channel for row in expected} == {f['channel'].name for f in fixtures.values()}
    expected_ids = [row.name for row in expected]
    older, cursor = [], None
    while True:
        page = api.messages(relay_contact.name, before=cursor, limit=3)
        assert 0 < len(page['items']) <= 3
        ids = [row.name for row in page['items']]
        assert ids == sorted(ids)
        older = ids + older
        if not page['has_more']:
            break
        cursor = page['first']
    assert older == expected_ids
    passed('real reverse conversation pagination is bounded, ordered and contains no missing or duplicate messages')

    newer, cursor = [], 'RELAY-MSG-0000000000'
    while True:
        page = api.messages(relay_contact.name, after=cursor, limit=3)
        assert 0 < len(page['items']) <= 3
        ids = [row.name for row in page['items']]
        assert ids == sorted(ids)
        newer.extend(ids)
        if not page['has_more']:
            break
        cursor = page['last']
    assert newer == expected_ids
    passed('real forward conversation pagination matches reverse history exactly')

    for medium, fixture in fixtures.items():
        page = api.messages(relay_contact.name, channel=fixture['channel'].name, limit=100)
        assert [row.name for row in page['items']] == [row.name for row in expected if row.channel == fixture['channel'].name]
        assert {row.channel for row in page['items']} == {fixture['channel'].name}
        settings = api.channel_settings(fixture['channel'].name)
        assert set(settings) == {'name', 'channel', 'account', 'enabled'}
        try:
            api.update_channel(fixture['channel'].name, 'forged-account', 0)
        except frappe.PermissionError:
            frappe.db.rollback()
        else:
            raise AssertionError('Communication manager changed System Manager channel configuration')
        assert frappe.db.get_value('Relay Channel', fixture['channel'].name, 'account') == ACCOUNT
        passed(medium + ': real channel filter preserves contact identity; manager can view but cannot change configuration')

    linked = [next(row.name for row in expected if row.channel == fixture['channel'].name) for fixture in fixtures.values()]
    created = tickets.create('Synthetic multi-channel ticket ' + RUN, linked,
        brief='Combine related Telegram and email evidence', category='Payment evidence')
    frappe.db.commit()
    ticket = tickets.read(created['name'])
    assert [row['message'] for row in ticket['messages']] == linked
    assert {row['contact'] for row in ticket['messages']} == {relay_contact.name}
    assert {row['channel'] for row in ticket['messages']} == {fixture['channel'].name for fixture in fixtures.values()}
    assert tickets.update_status(created['name'], 'Resolved')['status'] == 'Resolved'
    frappe.db.commit()
    assert tickets.read(created['name'])['status'] == 'Resolved'
    passed('real multi-channel ticket create/read/resolve retains each exact message and chat reference')

    count = frappe.db.count('Relay Ticket', {'subject': 'Synthetic duplicate ticket ' + RUN})
    try:
        tickets.create('Synthetic duplicate ticket ' + RUN, [linked[0], linked[0]])
    except frappe.ValidationError:
        frappe.db.rollback()
    else:
        raise AssertionError('Duplicate ticket message was accepted')
    assert frappe.db.count('Relay Ticket', {'subject': 'Synthetic duplicate ticket ' + RUN}) == count
    passed('duplicate ticket message links are rejected without partial ticket persistence')

    frappe.set_user(DENIED_USER)
    try:
        tickets.read(created['name'])
    except frappe.PermissionError:
        frappe.db.rollback()
    else:
        raise AssertionError('Communication user read another user\'s ticket')
    finally:
        frappe.set_user('Administrator')
    passed('real ticket owner permission denies an unrelated communication user')
    passed('both channels share one business contact without changing delivery channel')
    print(json.dumps({'result': 'passed', 'scenarios': len(PASSED), 'account': ACCOUNT,
                      'http_submissions': len(server.submissions), 'database': frappe.conf.db_name}), flush=True)
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
    frappe.destroy()
