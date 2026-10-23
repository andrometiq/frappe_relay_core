"""Real isolated Core group simulations; all provider HTTP stays on loopback.

Use RELAY_AUTOMATION_TEST_SITES and the installed Frappe Python exactly as for
integration_channels_site.py. Creates only synthetic records in the guarded DB.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
import os
from pathlib import Path
import threading
import time
from unittest.mock import patch

sites = os.environ.get('RELAY_AUTOMATION_TEST_SITES')
expected = Path(__file__).resolve().parents[1] / '.runtime/automation-bench/sites'
assert sites and Path(sites).resolve() == expected.resolve(), 'Refusing a non-test sites directory'
os.chdir(sites)
import frappe
from relay_core import settings as connection_settings
# Fixture transports and signatures use process-local synthetic configuration.
# Never replace the installed review site's encrypted connection credentials.
fixture_connection = patch.object(connection_settings, 'value', side_effect=lambda key: frappe.conf.get(key))
fixture_connection.start()
from werkzeug.wrappers import Request
from relay_core import inbound, mcp, telegram, whatsapp
from relay_core.automation import projection, service
from relay_core.automation.provenance import context_of
from relay_core.hub import HubClient, HubError

frappe.init(site='relay-ai-test.local')
assert frappe.conf.db_name == 'relay_ai_test_20260922', 'Refusing a non-test database'
assert frappe.conf.db_host in ('127.0.0.1', 'localhost'), 'Refusing a remote database'
frappe.connect(); frappe.set_user('Administrator'); frappe.flags.mute_emails = True
frappe.conf.relay_automation_enabled = 1
frappe.reload_doc('relay_core', 'doctype', 'relay_message', force=True)
frappe.db.add_index('Relay Message', ['conversation_key', 'name'], 'relay_conversation_history')
frappe.db.commit()
run_id = str(time.time_ns()); account = 'groups-sim-' + run_id
frappe.conf.relay_hub_account = account
secret = 'synthetic-group-callback-' + run_id
frappe.conf.relay_callback_secret = secret
token = 'synthetic-group-hub-token-' + run_id
actor = 'channels-executor@example.invalid'; callback_actor = 'channels-callback@example.invalid'
assert frappe.db.exists('User', actor) and frappe.db.exists('User', callback_actor), 'Run integration_channels_site.py once to provision isolated framework/user fixtures'
doctype = 'Relay Channel Simulation Business'
business = frappe.get_doc(dict(doctype=doctype, title='Group business ' + run_id)).insert()
person = frappe.get_doc(dict(doctype='Contact', first_name='Group person ' + run_id,
    phone_nos=[dict(phone='919000000009', is_primary_mobile_no=1)],
    links=[dict(link_doctype=doctype, link_name=business.name)])).insert()
contact = frappe.get_doc(dict(doctype='Relay Contact', contact=person.name,
    display_name='Group simulation ' + run_id, automation_generation=1)).insert()
provider = frappe.get_doc(dict(doctype='Relay AI Provider', provider='OpenRouter', model='synthetic-model',
    api_key='synthetic-unused-key', enabled=1)).insert()
channels, replies, endpoints = {}, {}, {}
for medium in ('Telegram', 'WhatsApp'):
    channel = frappe.get_doc(dict(doctype='Relay Channel', channel=medium, account=account, enabled=1)).insert()
    channels[medium] = channel
    reply = frappe.get_doc(dict(doctype='Relay Canned Reply', title='Group acknowledgement ' + run_id,
        channel=medium, language='Tamil', body='வணக்கம் குழு. உதவி செய்கிறோம்.', ai_enabled=1, published=1)).insert()
    replies[medium] = reply
    frappe.get_doc(dict(doctype='Relay Automation Policy', channel=channel.name, provider=provider.name,
        execution_user=actor, enabled=1, mode='Automatic', allow_ticket=1, allow_reply=1,
        business_doctype=doctype, daily_limit=100, reply_ids=reply.name, fallback_reply=reply.name)).insert()
    addresses = ('-100100', '-100200', '900100') if medium == 'Telegram' else ('group-one', 'group-two', '919000000009')
    for address in addresses:
        endpoints[(medium, address)] = frappe.get_doc(dict(doctype='Relay Contact Endpoint', channel=channel.name,
            endpoint=address, relay_contact=contact.name, verified=1)).insert()
frappe.db.commit()
site_url = frappe.utils.get_url().rstrip('/')
checks = []; serial = 0

def passed(label):
    checks.append(label); print('PASS ' + label, flush=True)

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *_): pass
    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', '0')); assert 0 < size < 65536
            value = json.loads(self.rfile.read(size)); assert self.path == '/mcp'
            assert self.headers.get('Authorization') == 'Bearer ' + token
            method = value['method']
            if method == 'initialize':
                result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'simulated-hub', 'version': 'test'}}
            elif method == 'notifications/initialized':
                self.send_response(202); self.send_header('Content-Length', '0'); self.end_headers(); return
            else:
                assert method == 'tools/call' and self.headers.get('MCP-Protocol-Version') == '2025-06-18'
                params = value['params']; name = params['name']; arguments = params['arguments']
                assert name in ('telegram.send', 'telegram.message', 'telegram.groups', 'whatsapp.enqueue', 'whatsapp.execute')
                if name == 'whatsapp.execute' and arguments['operation'] == 'capabilities':
                    result = {'structuredContent': {'site': site_url, 'groups': True}}
                else:
                    self.server.calls.append(params)
                    result = ({'isError': True, 'structuredContent': self.server.provider_error}
                              if self.server.provider_error else {'structuredContent': {'accepted': 1, 'success': True}})
            raw = json.dumps({'jsonrpc': '2.0', 'id': value['id'], 'result': result}).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
        except Exception as exc:
            self.server.errors.append(str(exc)); self.send_response(500); self.send_header('Content-Length', '0'); self.end_headers()

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.daemon_threads = True
server.calls, server.errors, server.provider_error = [], [], None
thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
client = HubClient(f'http://127.0.0.1:{server.server_port}/mcp', token)

def telegram_payload(chat=-100100, topic=None, participant=900100, kind='message', **changes):
    global serial
    serial += 1
    message = {'message_id': serial, 'chat': {'id': chat, 'type': 'supergroup' if chat < 0 else 'private'},
        'from': {'id': participant, 'is_bot': False}, 'text': 'குழு உதவி ' + str(serial)}
    if topic is not None: message['message_thread_id'] = topic
    message.update(changes)
    raw = {'update_id': serial, kind: message}
    return {'channel': 'Telegram', 'direction': 'inbound', 'provider_id': str(serial), 'sender': str(chat),
        'body': message.get('text', ''), 'payload': raw}

def whatsapp_payload(group='group-one', participant='919000000009'):
    global serial
    serial += 1
    message = {'id': 'wamid.synthetic.' + str(serial), 'from': participant, 'group_id': group,
        'type': 'text', 'text': {'body': 'WhatsApp குழு உதவி ' + str(serial)}}
    return {'entry': [{'changes': [{'field': 'messages', 'value': {'messages': [message]}}]}]}

def receive(value):
    global serial
    serial += 1
    medium = value.get('channel', 'WhatsApp'); event_id = serial
    envelope = {'account': account, 'events': [{'id': event_id, 'payload': value}]}
    raw = json.dumps(envelope).encode(); timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    old_user, old_request = frappe.session.user, getattr(frappe.local, 'request', None)
    frappe.set_user(callback_actor)
    frappe.local.request = Request.from_values(method='POST', data=raw, content_type='application/json',
        headers={'X-Relay-Timestamp': timestamp, 'X-Relay-Signature': signature})
    try:
        with patch.object(frappe, 'enqueue'), patch.object(frappe, 'publish_realtime'):
            assert inbound.receive() == {'accepted': 1}
        frappe.db.commit()
    finally:
        frappe.local.request = old_request; frappe.set_user(old_user)
    key = f'{account}:{event_id}' if medium == 'WhatsApp' else f'{account}:{medium}:{event_id}'
    name = frappe.db.get_value('Relay Hub Event', {'event_key': key}, 'name')
    with patch.object(frappe, 'enqueue'): projection.project(name)
    frappe.db.commit()
    try: rows = projection.extract_messages(value)
    except (ValueError, TypeError): rows = []
    message = frappe.db.get_value('Relay Message', {'provider_id': rows[0]['id'], 'channel': channels[medium].name}, 'name') if rows else None
    return name, message

def automate(message, medium):
    run_name = frappe.db.get_value('Relay Automation Run', {'message': message}, 'name'); assert run_name
    decision = {'category': 'Support', 'brief': 'Group help', 'create_ticket': True, 'reply': replies[medium].name, 'handoff': False}
    with patch.object(service, 'complete', return_value=decision), patch.object(frappe, 'enqueue'): service.process(run_name)
    run = frappe.get_doc('Relay Automation Run', run_name)
    return run, frappe.db.get_value('Relay Automation Outbox', {'run': run_name}, 'name')

def dispatch(outbox):
    with patch.object(whatsapp, 'client', return_value=client): service.dispatch(outbox)
    assert not server.errors, server.errors
    return frappe.db.get_value('Relay Automation Outbox', outbox, 'status')

try:
    # Insert all four conversations before processing to expose any channel-wide
    # supersession bug. One Contact deliberately owns private/group/topic endpoints.
    messages = []
    for chat, topic in [(-100100, 11), (-100100, 22), (-100200, 11), (900100, None)]:
        value = telegram_payload(chat, topic, reply_to_message={'message_id': 777})
        _, name = receive(value); doc = frappe.get_doc('Relay Message', name)
        context = context_of(doc)
        assert context['chat_id'] == chat and context['participant_id'] == 900100
        assert context['message_id'] == value['payload']['message']['message_id']
        assert context['reply_to_message_id'] == 777
        assert doc.sender_endpoint == str(chat)
        messages.append((doc, topic))
    assert len({doc.conversation_key for doc, _ in messages}) == 4
    for doc, topic in messages:
        run, outbox = automate(doc.name, 'Telegram'); assert run.status == 'Completed', run.reason
        assert dispatch(outbox) == 'Submitted'
        sent = server.calls[-1]['arguments']
        assert sent['chat_id'] == int(doc.sender_endpoint)
        assert sent['reply_to'] == context_of(doc)['message_id']
        assert sent.get('message_thread_id') == topic
    passed('Telegram private chats, distinct groups and distinct topics stay isolated through real HTTP replies')

    value = telegram_payload(topic=33)
    _, original = receive(value); _, repeated = receive(value)
    assert original == repeated
    assert frappe.db.count('Relay Automation Run', {'message': original}) == 1
    passed('Telegram identical provider update replay creates one group message and automation run')

    _, older = receive(telegram_payload(topic=44)); _, newer = receive(telegram_payload(topic=44))
    run, outbox = automate(older, 'Telegram'); assert run.status == 'Handoff' and not outbox
    run, outbox = automate(newer, 'Telegram'); assert run.status == 'Completed' and dispatch(outbox) == 'Submitted'
    passed('newer message supersedes only its own Telegram group topic')

    for kind in ('edited_message', 'message_reaction', 'message_reaction_count', 'my_chat_member', 'chat_member', 'chat_join_request'):
        value = telegram_payload(kind=kind)
        if kind == 'message_reaction': value['payload'][kind].update(user={'id': 900100}, new_reaction=[])
        if kind == 'message_reaction_count': value['payload'][kind]['reactions'] = []
        name, message = receive(value); assert not message
        expected = 'Uncategorized' if kind == 'edited_message' or kind.startswith('message_reaction') else 'Ignored'
        assert frappe.db.get_value('Relay Hub Event', name, 'projection_status') == expected
    value = telegram_payload(); value['payload']['message'].pop('text'); value['body'] = ''
    value['payload']['message']['new_chat_members'] = [{'id': 99}]
    name, message = receive(value); assert not message and frappe.db.get_value('Relay Hub Event', name, 'projection_status') == 'Ignored'
    value = telegram_payload(); value['payload']['message']['from']['is_bot'] = True
    _, message = receive(value); assert not message
    passed('Telegram service, edited, reaction, membership and bot updates cannot trigger new text automation')

    value = telegram_payload(topic=77)
    value['payload']['message'].pop('text')
    value['payload']['message'].update({'photo': [{'file_id': 'synthetic-photo', 'file_unique_id': 'unique-photo'}], 'caption': 'Payment screenshot'})
    value['body'] = 'Payment screenshot'
    _, message = receive(value); doc = frappe.get_doc('Relay Message', message)
    assert doc.message_type == 'photo' and context_of(doc)['media']['file_id'] == 'synthetic-photo'
    name = frappe.db.get_value('Relay Automation Run', {'message': message}, 'name')
    with patch.object(service, 'complete') as model:
        service.process(name); model.assert_not_called()
    assert frappe.db.get_value('Relay Automation Run', name, 'status') == 'Handoff'
    assert not frappe.db.exists('Relay Automation Outbox', {'run': name})
    passed('Telegram group photo provenance is retained; caption does not bypass the text-only AI policy')

    _, message = receive(telegram_payload(chat=-100999)); assert not message
    passed('unverified Telegram group cannot inherit a participant private-chat binding')

    _, message = receive(telegram_payload(topic=55)); run, outbox = automate(message, 'Telegram')
    endpoint = endpoints[('Telegram', '-100100')]; endpoint.verified = 0; endpoint.save(); frappe.db.commit()
    count = len(server.calls); assert dispatch(outbox) == 'Cancelled' and len(server.calls) == count
    endpoint.reload(); endpoint.verified = 1; endpoint.save(); frappe.db.commit()
    passed('revoked Telegram group binding cancels queued reply without HTTP delivery')

    _, message = receive(telegram_payload(topic=66)); run, outbox = automate(message, 'Telegram')
    doc = frappe.get_doc('Relay Message', message); changed = context_of(doc); changed['message_thread_id'] = 999
    frappe.db.set_value('Relay Message', message, 'provider_context', json.dumps(changed)); frappe.db.commit()
    count = len(server.calls); assert dispatch(outbox) == 'Cancelled' and len(server.calls) == count
    passed('changed topic provenance cannot redirect an already authorized reply')

    for chat, kind in [(-100100, 'private'), (900100, 'group')]:
        value = telegram_payload(chat); value['payload']['message']['chat']['type'] = kind
        event, message = receive(value)
        assert not message and frappe.db.get_value('Relay Hub Event', event, 'projection_status') == 'Failed'
    passed('signed but inconsistent private/group identity is rejected before projection')

    frappe.set_user(actor)
    with patch.object(telegram, 'client', return_value=client), patch('relay_core.whatsapp.client', return_value=client):
        telegram.groups('topics.create', {'chat_id': -100100, 'name': 'Support'})
        telegram.execute('pins.pin', {'chat_id': -100100, 'message_id': 123})
        telegram.send(-100100, 'Manual group reply', reply_to=123, message_thread_id=11, request_key='group-facade-'+str(time.time_ns()))
    assert server.calls[-3]['name'] == 'telegram.groups'
    assert server.calls[-2]['arguments'] == {'operation': 'pins.pin', 'chat_id': -100100, 'message_id': 123}
    assert server.calls[-1]['arguments']['message_thread_id'] == 11
    passed('Core manager group/topic/pin and verified-binding send facades reach canonical Hub MCP via real HTTP')
    frappe.set_user('channels-denied@example.invalid'); count = len(server.calls)
    try:
        with patch.object(telegram, 'client', return_value=client): telegram.groups('title', {'chat_id': -100100, 'title': 'forged'})
    except frappe.PermissionError: frappe.db.rollback()
    else: raise AssertionError('Communication user modified group administration')
    assert len(server.calls) == count; frappe.set_user('Administrator')
    passed('non-manager group administration is rejected before HTTP')

    frappe.set_user(actor)
    server.provider_error = {'provider': 'Telegram', 'error': {'http_status': 429, 'code': 429,
        'retry_after': 17, 'migrate_to_chat_id': -100999, 'outcome_unknown': False,
        'description': 'synthetic-secret-must-not-cross-boundary'}}
    count = len(server.calls)
    with patch.object(telegram, 'client', return_value=client):
        try: telegram.groups('info', {'chat_id': -100100})
        except HubError as exc:
            assert exc.metadata == {'provider': 'Telegram', 'error': {'http_status': 429, 'code': 429,
                'retry_after': 17, 'migrate_to_chat_id': -100999, 'outcome_unknown': False}}
            assert 'synthetic-secret' not in str(exc)
        else: raise AssertionError('Provider error was treated as success')
    assert len(server.calls) == count + 1
    old_request = getattr(frappe.local, 'request', None)
    request = {'jsonrpc': '2.0', 'id': 17, 'method': 'tools/call', 'params': {'name': 'relay.telegram.groups',
        'arguments': {'operation': 'info', 'arguments': {'chat_id': -100100}}}}
    frappe.local.request = Request.from_values(method='POST', data=json.dumps(request), content_type='application/json',
        headers={'Authorization': 'token synthetic:synthetic'})
    try:
        with patch.object(telegram, 'client', return_value=client): result = mcp.endpoint()
        wire = json.loads(result.get_data(as_text=True))
        assert wire['error']['data']['error']['retry_after'] == 17
        assert wire['error']['data']['error']['migrate_to_chat_id'] == -100999
        assert 'synthetic-secret' not in result.get_data(as_text=True)
    finally:
        frappe.local.request = old_request; server.provider_error = None; frappe.set_user('Administrator')
    assert len(server.calls) == count + 2
    assert endpoints[('Telegram', '-100100')].endpoint == '-100100'
    passed('Telegram retry/migration metadata survives real HTTP and Core MCP without secret leakage, retries or automatic rebinding')

    wa = []
    for group in ('group-one', 'group-two'):
        _, name = receive(whatsapp_payload(group)); doc = frappe.get_doc('Relay Message', name)
        assert doc.sender_endpoint == group and context_of(doc)['participant_id'] == '919000000009'
        wa.append(doc)
    for doc in wa:
        run, outbox = automate(doc.name, 'WhatsApp'); assert run.status == 'Completed', run.reason
        assert dispatch(outbox) == 'Submitted'
        sent = server.calls[-1]; assert sent['name'] == 'whatsapp.enqueue'
        request = sent['arguments']['messages'][0]['message']
        assert request['operation'] == 'groups.send' and request['to'] == doc.sender_endpoint
        assert request['to'] != context_of(doc)['participant_id']
        assert request['reply_to'] == doc.provider_id
    passed('WhatsApp groups preserve participant provenance and queue replies to original group, never participant DM')
    _, message = receive(whatsapp_payload('unknown-group')); assert not message
    passed('unverified WhatsApp group cannot inherit a verified participant mobile endpoint')
    for field in ('group_lifecycle_update', 'group_participants_update', 'group_settings_update', 'group_status_update'):
        name, message = receive({'entry': [{'changes': [{'field': field, 'value': {'groups': [{'group_id': 'group-one', 'type': 'update'}]}}]}]})
        assert not message and frappe.db.get_value('Relay Hub Event', name, 'projection_status') == 'Ignored'
    passed('WhatsApp lifecycle, membership, settings and status webhooks cannot trigger text AI')
    _, message = receive(whatsapp_payload()); run, outbox = automate(message, 'WhatsApp')
    endpoint = endpoints[('WhatsApp', 'group-one')]; endpoint.verified = 0; endpoint.save(); frappe.db.commit()
    count = len(server.calls); assert dispatch(outbox) == 'Cancelled' and len(server.calls) == count
    endpoint.reload(); endpoint.verified = 1; endpoint.save(); frappe.db.commit()
    passed('revoked WhatsApp group binding cancels queued group delivery')
    for operation, arguments in [('groups.media', {'id': 'group-one', 'media_type': 'document', 'media_id': '123'}),
                                 ('groups.template', {'id': 'group-one', 'name': 'order_update', 'language': 'en'}),
                                 ('groups.pin', {'id': 'group-one', 'reply_to': 'wamid.1', 'action': 'pin', 'expiration_days': 3})]:
        prepared = whatsapp.prepare(operation, arguments)
        assert prepared['operation'] == operation and prepared['to'] == 'group-one' and 'id' not in prepared
    for unsupported in ('groups.participants.add', 'groups.invite.revoke'):
        try: whatsapp.prepare(unsupported, {'id': 'group-one'})
        except frappe.ValidationError: frappe.db.rollback()
        else: raise AssertionError('Unsupported Meta API was exposed')
    uploaded = whatsapp.prepare('groups.media', {'id':'group-one','media_type':'document','content_base64':'Zml4dHVyZQ==','mime_type':'text/plain','filename':'note.txt'})
    assert uploaded['content_base64']=='Zml4dHVyZQ==' and uploaded['to']=='group-one'
    for operation,args in [('groups.send', {'id':'group-one','content_base64':'Zg=='}),('groups.media',{'id':'group-one','content_base64':'Zg==','media_url':'https://example.invalid/x'})]:
        try:whatsapp.prepare(operation,args)
        except frappe.ValidationError:frappe.db.rollback()
        else:raise AssertionError('Invalid byte-upload operation accepted')
    frappe.set_user('relay-agent-a@example.invalid')
    for operation in ('groups.list','groups.info','groups.send','groups.media','groups.template','groups.pin'):
        try:whatsapp.prepare(operation,{'id':'group-one'})
        except frappe.PermissionError:frappe.db.rollback()
        else:raise AssertionError('Account-wide group operation accepted for an ordinary agent')
    frappe.set_user('Administrator')
    passed('WhatsApp group media/template/pin contracts and rejection of nonexistent Meta operations')
    frappe.set_user('Administrator')
    directory = telegram.group_chats(limit=1)
    assert len(directory['items']) == 1 and directory['next']
    assert directory['items'][0]['chat_id'] < 0
    following = telegram.group_chats(after=directory['next'], limit=1)
    assert len(following['items']) == 1 and following['items'][0]['chat_id'] != directory['items'][0]['chat_id']
    assert following['next'] is None
    found=telegram.group_chats(query='-100100')
    assert len(found['items'])==1 and found['items'][0]['chat_id']==-100100
    assert not telegram.group_chats(query='%')['items']
    assert telegram.group_chats(query=contact.display_name[:40])['items']
    for bad in ('x'*81, 'bad\nquery', 123):
        try:telegram.group_chats(query=bad)
        except frappe.ValidationError:frappe.db.rollback()
        else:raise AssertionError('Invalid group search accepted')
    passed('Telegram group directory is account-scoped, searched and paged; private chats excluded')
    endpoint = endpoints[('Telegram', '-100100')]; endpoint.verified = 0; endpoint.save(); frappe.db.commit()
    assert len(telegram.group_chats()['items']) == 1
    endpoint.verified = 1; endpoint.save(); frappe.db.commit()
    passed('Unverified group endpoints are excluded from the directory')
    from relay_core.api import messages as group_history
    history_page = group_history(contact.name, channel=channels['Telegram'].name, sender_endpoint='-100100')
    assert history_page['items'] and all(row.sender_endpoint == '-100100' for row in history_page['items'])
    passed('Group history excludes other groups and private chats on the same contact')
    from relay_core.api import business_types, business_records
    assert doctype in business_types()
    assert business.name in [row.name for row in business_records(doctype, business.name)]
    try:business_records('User', '')
    except frappe.PermissionError:pass
    else:raise AssertionError('unconfigured business search accepted')
    passed('Business record picker uses configured types and permission-checked database search')
    frappe.set_user('Guest')
    try:telegram.group_chats()
    except frappe.PermissionError:pass
    else:raise AssertionError('guest could list account groups')
    passed('Group directory denies guest access')
    print(json.dumps({'result': 'passed', 'scenarios': len(checks), 'account': account,
        'http_submissions': len(server.calls), 'database': frappe.conf.db_name}), flush=True)
finally:
    server.shutdown(); server.server_close(); thread.join(timeout=3); frappe.destroy()
