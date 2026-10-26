"""Explicit yrp.site regressions; retained local fixtures, isolated RQ queue.

Run with bench Python -B. Reloads ONLY Relay Message. No migrate, exports,
service restart, site configuration changes, deletion, or external delivery.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

os.environ['FRAPPE_STREAM_LOGGING'] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
import frappe
import requests
from rq import Queue, SimpleWorker
from frappe.utils.background_jobs import get_redis_conn
from relay_core import inbound
from relay_core.automation import queue, projection
from relay_core.message_updates import provider_key

SITES = '/home/sakthi/development/pilot/benches/version_16/sites'
SCRIPT = str(Path(__file__).resolve())


def connect():
    frappe.init(site='yrp.site', sites_path=SITES)
    frappe.connect()
    assert frappe.local.site == 'yrp.site' and frappe.conf.developer_mode
    frappe.set_user('Administrator')
    frappe.flags.mute_emails = True


def insert(doctype, **values):
    return frappe.get_doc(dict(doctype=doctype, **values)).insert(ignore_permissions=True)


@contextmanager
def isolated(tag):
    """Use real SQL/hooks/RQ, scoped to our new channels and test worker."""
    rq = Queue('relay-core-local-defects-' + tag, connection=get_redis_conn())
    original_get_all = frappe.get_all
    original_request = requests.sessions.Session.request

    def local_request(session, method, url, *args, **kwargs):
        assert urlsplit(url).hostname == '127.0.0.1', 'External HTTP disabled'
        return original_request(session, method, url, *args, **kwargs)

    def get_all(doctype, *args, **kwargs):
        if doctype == 'Relay Message' and kwargs.get('filters') == {'automation_status': 'Pending'}:
            channels = original_get_all('Relay Channel', filters={'account': 'local-defects-' + tag}, pluck='name')
            kwargs['filters'] = dict(kwargs['filters'], channel=['in', channels])
        return original_get_all(doctype, *args, **kwargs)

    def recover():
        if get_all('Relay Message', filters={'automation_status': 'Pending'}, pluck='name', limit_page_length=1):
            queue.wake()

    with ExitStack() as stack:
        stack.enter_context(patch.object(queue, 'get_queue', return_value=rq))
        stack.enter_context(patch.object(queue.AUTOMATION, 'signal', 'relay-core-local-wake-' + tag))
        stack.enter_context(patch.object(queue.AUTOMATION, 'lock', 'core-lock-' + tag[-12:]))
        stack.enter_context(patch.object(queue, 'recover', side_effect=recover))
        stack.enter_context(patch.object(frappe, 'get_all', side_effect=get_all))
        stack.enter_context(patch('frappe.utils.background_jobs.get_queue', return_value=rq))
        stack.enter_context(patch('relay_core.channel_statuses.connection_value', return_value='local-defects-' + tag))
        # These tests configure no delivery policies; accidental sends must fail.
        stack.enter_context(patch('requests.sessions.Session.request', local_request))
        yield rq


@contextmanager
def ai_fixture(tag, links):
    from automation_queue_site import LocalAI
    title = 'Local Core defects AI ' + tag
    person = insert('Contact', first_name=title, links=links)
    contact = insert('Relay Contact', contact=person.name, display_name=title, automation_paused=0)
    channel = insert('Relay Channel', channel='WhatsApp', account='local-defects-' + tag, enabled=1)
    endpoint = '919999990001'
    insert('Relay Contact Endpoint', channel=channel.name, endpoint=endpoint, relay_contact=contact.name, verified=1)
    server = ThreadingHTTPServer(('127.0.0.1', 0), LocalAI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    skill = None
    try:
        previous_import = frappe.flags.in_import
        frappe.flags.in_import = True
        try:
            user = insert('User', email='relay-core-defects-' + tag + '@example.invalid', first_name=title,
                enabled=1, send_welcome_email=0, user_type='System User',
                roles=[dict(role=role) for role in ('System Manager', 'Relay Communication Manager', 'Accounts Manager')])
        finally:
            frappe.flags.in_import = previous_import
        provider = insert('AI Provider Account', account_name=title, provider='OpenRouter', auth_type='API Key',
            enabled=1, api_key='local-fixture-only', base_url=f'http://127.0.0.1:{server.server_port}')
        model = insert('AI Model', model_label=title, enabled=1, account=provider.name,
                       model_id='local-queue-benchmark', temperature=0, max_tokens=300)
        skill = insert('Relay AI Skill', title=title, enabled=1, mode='Shadow', channel=channel.name,
            business_doctype=links[0]['link_doctype'], ai_model=model.name, run_as_user=user.name,
            handoff_owner=user.name, instructions='Return the local fixture quantities.', daily_limit=100,
            allowed_tools='[]')
        frappe.db.commit()
        yield contact, channel, endpoint, LocalAI
    finally:
        frappe.db.rollback()
        if skill:
            skill.reload()
            skill.enabled = 0
            skill.save(ignore_permissions=True)
            frappe.db.commit()
        server.shutdown()
        server.server_close()


def run_child(mode, tag):
    result = subprocess.run([sys.executable, '-B', SCRIPT, mode, tag], capture_output=True, text=True)
    if result.returncode:
        # Our fixtures and worker arguments contain no credentials. Keep logs local.
        Path('/tmp/relay-core-defects-child.log').write_text(result.stdout + result.stderr)
        raise AssertionError('Site child failed; see /tmp/relay-core-defects-child.log')


def callback(account, payload, event_id=0, *, statuses=False):
    # Exercise authentication and the real whitelisted callback in a fresh site
    # process, without changing the running web process's connection settings.
    values = {'statuses': payload} if statuses else {'events': [{'id': event_id, 'payload': payload}]}
    body = json.dumps({'account': account, **values}).encode()
    timestamp = str(int(time.time()))
    secret = 'local-test-signature-only-' * 2
    signature = hmac.new(secret.encode(), timestamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
    request = frappe._dict(get_data=lambda: body,
        headers={'X-Relay-Timestamp': timestamp, 'X-Relay-Signature': signature})
    with patch.object(inbound, 'connection_value', side_effect=lambda key: secret if key == 'relay_callback_secret' else account), \
            patch.object(frappe.local, 'request', request, create=True):
        return inbound.receive_channel_statuses() if statuses else inbound.receive()


def main():
    connect()
    assert not frappe.db.exists('Notification', {'enabled': 1, 'document_type': ['in',
        ['Contact', 'Relay Contact', 'Relay Message', 'Relay Channel', 'User', 'Relay AI Skill']]})
    tag = str(time.time_ns())
    account = 'local-defects-' + tag
    # Read compatibility evidence only. No existing messages are repaired/rekeyed.
    old = frappe.db.sql("""select m.name, m.provider_id, m.source_key, m.provider_message_key, m.provider_context
        from `tabRelay Message` m join `tabRelay Channel` c on c.name=m.channel
        where c.channel='Email' and coalesce(m.provider_id,'')=''""", as_dict=True)
    compatible = [row for row in old if json.loads(row.provider_context or '{}').get('message_id')]
    frappe.reload_doc('relay_core', 'doctype', 'relay_message', force=True)
    frappe.db.commit()
    assert frappe.get_meta('Relay Message').get_field('provider_id').ignore_xss_filter
    for row in compatible:
        actual = frappe.db.get_value('Relay Message', row.name,
            ['provider_id', 'source_key', 'provider_message_key', 'provider_context'], as_dict=True)
        assert all(actual[key] == row[key] for key in actual)
        frappe.get_doc('Relay Message', row.name).validate()

    base = frappe.get_doc('Relay Contact', {'display_name': ['like', 'Local simulation%'], 'automation_paused': 1})
    links = [dict(link_doctype=row.link_doctype, link_name=row.link_name)
             for row in frappe.get_doc('Contact', base.contact).links]
    assert len(links) == 1
    person = insert('Contact', first_name='Local Core defects ' + tag, links=links)
    contact = insert('Relay Contact', contact=person.name, display_name='Local Core defects ' + tag, automation_paused=1)
    channels = {}
    for medium, endpoint in (('Telegram', '123456789'), ('Email', 'local-' + tag + '@example.invalid')):
        channel = insert('Relay Channel', channel=medium, account=account, enabled=1)
        insert('Relay Contact Endpoint', channel=channel.name, endpoint=endpoint, relay_contact=contact.name, verified=1)
        channels[medium] = channel.name, endpoint
    frappe.db.commit()

    from test_projection_latency import channel_text
    messages = []
    timings = {}
    with isolated(tag) as rq, ai_fixture(tag, links) as ai:
        fixture_jobs = rq.count  # Frappe's User -> Contact creation, also local.
        # Simulate loss of a producer after staging the reservation but before
        # RQ enqueue. Nothing is visible, so the next arrival can wake at once.
        with patch.object(rq, 'enqueue_call', side_effect=SystemExit('injected producer death')):
            try:
                queue.wake()
            except SystemExit:
                pass
            else:
                raise AssertionError('Producer fault was not injected')
        assert not rq.connection.get(queue.AUTOMATION.signal_key) and rq.count == fixture_jobs

        for index, medium in enumerate(('Telegram', 'Email'), 1):
            channel, endpoint = channels[medium]
            payload = channel_text(medium)
            payload['sender'] = endpoint
            if medium == 'Telegram':
                payload['payload']['message']['chat']['id'] = int(endpoint)
            else:
                payload['provider_id'] = '<Local+Tag=' + tag + '@example.invalid>'
                payload['payload']['message_id'] = payload['provider_id']
            started = time.monotonic()
            response = callback(account, payload, index)
            assert response['timing']['inline_projection_ms'] > 0
            row = frappe.get_doc('Relay Message', {'channel': channel, 'relay_contact': contact.name})
            assert row.content == 'Quantity 12' and row.automation_status == 'Pending'
            assert row.provider_id == payload['provider_id']
            messages.append(row.name)
            frappe.db.commit()
            timings[medium] = round((time.monotonic() - started) * 1000, 2)
            assert timings[medium] < 500, 'Single-message projection exceeds local bound'
            callback(account, payload, index)
            callback(account, payload, index + 100)  # New event, same provider identity.
            frappe.db.commit()
            assert frappe.db.count('Relay Message', {'channel': channel, 'relay_contact': contact.name}) == 1
            if medium == 'Email':
                assert row.provider_message_key == provider_key(channel, endpoint, payload['provider_id'])
                # Mimic a pre-fix row using a new local fixture only. Dedupe and
                # reply threading must still work from its intact hashes/context.
                original_keys = (row.source_key, row.provider_message_key)
                row.provider_id = ''
                row.save(ignore_permissions=True)
                frappe.db.commit()
                callback(account, payload, index + 200)
                reply = dict(payload, provider_id='<Reply-' + tag + '@example.invalid>',
                    payload=dict(payload['payload'], message_id='<Reply-' + tag + '@example.invalid>',
                        in_reply_to=payload['provider_id'], references=[payload['provider_id']]))
                callback(account, reply, index + 300)
                reply_row = frappe.get_doc('Relay Message', {'channel': channel, 'provider_id': reply['provider_id']})
                assert reply_row.conversation_key == row.conversation_key
                messages.append(reply_row.name)
                row.reload()
                assert (row.source_key, row.provider_message_key) == original_keys
                assert frappe.db.count('Relay Message', {'channel': channel, 'relay_contact': contact.name}) == 2
                # Outbound projection uses the same real DocType sanitizer path.
                outgoing = insert('Relay Message', relay_contact=contact.name, channel=channel,
                    direction='Outgoing', content='Local outgoing quantity 12', provider_id='<Sent-' + tag + '@example.invalid>')
                outgoing.reload()
                assert outgoing.provider_id == '<Sent-' + tag + '@example.invalid>'
                assert not outgoing.automation_status
                frappe.db.commit()

        # A committed backlog must preserve order and leave room for a real AI
        # intent. The existing hooks execute, with all external providers local.
        for index in range(300):
            row = insert('Relay Message', relay_contact=contact.name, channel=channels['Telegram'][0],
                direction='Incoming', content=f'Local Core defects {tag}: quantity {index + 1}, amount 1250',
                message_type='text')
            messages.append(row.name)
        ai_contact, ai_channel, endpoint, local_ai = ai
        ai_message = insert('Relay Message', relay_contact=ai_contact.name, channel=ai_channel.name,
            direction='Incoming', content='Local Core defects: quantity 12, amount 1250',
            message_type='text', sender_endpoint=endpoint, provider_context='{"provider":"WhatsApp"}')
        messages.append(ai_message.name)
        frappe.db.commit()
        assert rq.count == fixture_jobs + 1, 'Arrivals must coalesce'
        # Bounded batches/media/DSNs still use the background projection path.
        # A real signed non-zero DSN for a Hub-owned send without a Core action
        # is acknowledged durably and ignored safely by the projection worker.
        with patch.object(projection, 'project', wraps=projection.project) as project:
            response = callback(account, [dict(id=1, delivery_id=1, request_key='local_dsn_' + tag,
                operation='email.send', state='bounced', occurred_at='2026-10-24T00:00:00Z',
                receipt=dict(message_id='<dsn-' + tag + '@example.invalid>', recipient=channels['Email'][1],
                    delivery_status='bounced', status_code='5.1.1'))], statuses=True)
            assert response['accepted'] == 1
            project.assert_not_called()
        status_event = frappe.db.get_value('Relay Hub Event',
            {'account': account, 'event_key': ['like', 'channel-statuses:%']}, 'name')
        assert frappe.db.get_value('Relay Hub Event', status_event, 'projection_status') == 'Pending'
        response = callback(account, dict(channel_text('Email'), body='x' * 17000), 17900)
        assert response['timing']['inline_projection_ms'] == 0
        frappe.db.commit()
        # Competing process consumes a wake but cannot acquire the ordering lock.
        # It must leave a successor even if the active owner sees no further work.
        assert frappe.db.sql('select get_lock(%s, 0)', (queue.AUTOMATION.lock_name,))[0][0]
        try:
            run_child('--contend', tag)
        finally:
            frappe.db.sql('select release_lock(%s)', (queue.AUTOMATION.lock_name,))
        started = time.monotonic()
        run_child('--work', tag)
        frappe.db.rollback()
        for name in messages:
            assert frappe.db.get_value('Relay Message', name, 'automation_status') == 'Complete'
        assert frappe.db.get_value('Relay Hub Event', status_event, 'projection_status') == 'Projected'
        assert frappe.db.count('Relay Automation Run', {'message': ai_message.name, 'status': 'Shadow'}) == 1
        assert local_ai.calls == 1
        assert rq.count == 0
        elapsed = round(time.monotonic() - started, 3)
        queue.wake()  # Replay must not call hooks again for Complete rows.
        run_child('--work', tag)
        frappe.db.rollback()
        assert frappe.db.count('Relay Automation Run', {'message': ai_message.name}) == 1 and local_ai.calls == 1
        trace = Path('/tmp/relay-core-defects-' + tag + '.jsonl')
        processed = [json.loads(line) for line in trace.read_text().splitlines()]
        assert len(processed) == len(set(processed))
        assert processed[:len(messages)] == messages, 'Processing order changed'
        print(json.dumps(dict(site='yrp.site', fixture_prefix='Local Core defects ' + tag,
            inline_ms=timings, drain_seconds=elapsed, processed=len(processed),
            compatible_existing_email_rows=len(compatible), provider_identity=True, replay_and_threading=True,
            interrupted_enqueue_atomic=True, lock_contention_rewakes=True, at_most_once=True,
            shadow_ai_calls=local_ai.calls)))
    frappe.destroy()


if __name__ == '__main__':
    if len(sys.argv) == 3:
        mode, tag = sys.argv[1:]
        connect()
        with isolated(tag) as rq:
            if mode == '--contend':
                token = rq.connection.get(queue.AUTOMATION.signal_key)
                assert token
                assert queue.drain(token=token.decode()) == 0
                assert rq.connection.get(queue.AUTOMATION.signal_key) != token
                assert rq.count >= 2
            elif mode == '--work':
                original = queue._process
                def process(name):
                    original(name)
                    with open('/tmp/relay-core-defects-' + tag + '.jsonl', 'a') as stream:
                        stream.write(json.dumps(name) + '\n')
                os.chdir(SITES)
                with patch.object(queue, '_process', side_effect=process):
                    SimpleWorker([rq], connection=rq.connection).work(burst=True, logging_level='WARNING')
                assert not rq.failed_job_registry.count, 'Isolated worker job failed'
            else:
                raise ValueError('Unknown mode')
        frappe.destroy()
    else:
        main()
