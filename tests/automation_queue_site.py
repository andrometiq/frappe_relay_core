"""Explicit yrp.site integration benchmark; retains identifiable local records.

Run with the bench Python and -B. Uses the installed default worker, a loopback
AI stub and a Shadow skill. No outbound messaging, service restart or migration.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

os.environ['FRAPPE_STREAM_LOGGING'] = '1'
import frappe
from relay_core.automation import queue

SITES = '/home/sakthi/development/pilot/benches/version_16/sites'


def connect():
    frappe.init(site='yrp.site', sites_path=SITES)
    frappe.connect()
    assert frappe.local.site == 'yrp.site' and frappe.conf.developer_mode
    frappe.set_user('Administrator')
    frappe.flags.mute_emails = True


def insert(doctype, **values):
    return frappe.get_doc(dict(doctype=doctype, **values)).insert(ignore_permissions=True)


def wait(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frappe.db.rollback()
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError('Local automation benchmark timed out')


class LocalAI(BaseHTTPRequestHandler):
    calls = 0

    def log_message(self, *args):
        pass

    def do_POST(self):
        assert self.path == '/chat/completions'
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert request['model'] == 'local-queue-benchmark'
        type(self).calls += 1
        value = dict(reply='Local fixture: quantity 12, amount 1250.', handoff=False, reason='')
        response = json.dumps(dict(choices=[dict(message=dict(role='assistant', content=json.dumps(value)),
            finish_reason='stop')], usage=dict(prompt_tokens=20, completion_tokens=15))).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def main():
    connect()
    assert frappe.conf.get('relay_automation_enabled')
    from frappe.utils.background_jobs import get_queue, get_workers
    workers = get_workers(get_queue('default'))
    assert len(workers) == 1, 'Benchmark requires exactly one default worker'
    assert all(not set(w.queue_names()) & {get_queue('short').name, get_queue('long').name} for w in workers)
    assert not frappe.db.exists('Relay Message', {'automation_status': 'Pending'}), 'Finish existing pending hooks first'
    assert not frappe.db.exists('Notification', {'enabled': 1, 'document_type': ['in',
        ['User', 'Contact', 'Relay Contact', 'Relay Message', 'Relay AI Skill']]}), 'Fixture notifications must be off'
    tag = 'Local queue benchmark ' + str(time.time_ns())
    base = frappe.get_doc('Relay Contact', {'display_name': ['like', 'Local simulation%'], 'automation_paused': 1})
    links = [dict(link_doctype=r.link_doctype, link_name=r.link_name)
             for r in frappe.get_doc('Contact', base.contact).links]
    assert len(links) == 1
    channel = insert('Relay Channel', channel='WhatsApp', account=tag, enabled=1)
    contacts = []
    for label, paused in (('paused', 1), ('no skill', 0), ('AI', 0)):
        person = insert('Contact', first_name=tag + ' ' + label, links=links)
        contacts.append(insert('Relay Contact', contact=person.name, display_name=tag + ' ' + label,
                               automation_paused=paused))
    user = insert('User', email='relay-queue-' + str(time.time_ns()) + '@example.invalid',
        first_name=tag, enabled=1, send_welcome_email=0, user_type='System User',
        roles=[dict(role=r) for r in ('System Manager', 'Relay Communication Manager', 'Accounts Manager')])
    server = ThreadingHTTPServer(('127.0.0.1', 0), LocalAI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    provider = insert('AI Provider Account', account_name=tag, provider='OpenRouter', auth_type='API Key',
        enabled=1, api_key='local-fixture-only', base_url=f'http://127.0.0.1:{server.server_port}')
    model = insert('AI Model', model_label=tag, enabled=1, account=provider.name,
                   model_id='local-queue-benchmark', temperature=0, max_tokens=300)
    ai_channel = insert('Relay Channel', channel='WhatsApp', account=tag + ' AI', enabled=1)
    endpoint = '919999990001'
    insert('Relay Contact Endpoint', channel=ai_channel.name, endpoint=endpoint,
           relay_contact=contacts[2].name, verified=1)
    skill = insert('Relay AI Skill', title=tag, enabled=1, mode='Shadow', channel=ai_channel.name,
        business_doctype=links[0]['link_doctype'], ai_model=model.name, run_as_user=user.name,
        handoff_owner=user.name, instructions='Return the local fixture quantities.', daily_limit=100, allowed_tools='[]')
    frappe.db.commit()

    def message(contact, ch=channel, **values):
        return insert('Relay Message', relay_contact=contact.name, channel=ch.name,
            direction=values.pop('direction', 'Incoming'), content=tag + ': quantity 12, amount 1250',
            message_type='text', provider_context='{"provider":"WhatsApp"}', **values)

    results = {}
    try:
        # Actual insert hooks, committed backlog, then one real default-queue job.
        with patch.object(queue, 'wake'):
            batch = [message(contacts[i % 2]).name for i in range(300)]
            ignored = [message(contacts[0], direction='Outgoing'), message(contacts[0], legacy_source=tag)]
            frappe.db.commit()
        assert all(not d.automation_status for d in ignored)
        assert frappe.db.count('Relay Message', {'name': ['in', batch], 'automation_status': 'Pending'}) == 300
        started = time.monotonic()
        job = queue.wake()
        assert job is not None
        wait(lambda: frappe.db.count('Relay Message', {'name': ['in', batch], 'automation_status': 'Complete'}) == 300)
        results['batch_300_seconds'] = round(time.monotonic() - started, 3)
        wait(lambda: str(job.get_status(refresh=True)).endswith('FINISHED'))
        assert job.return_value() == 300, 'All 300 should fit in one worker turn'
        assert results['batch_300_seconds'] < 15
        results['batch_jobs'] = 1

        # AI arrives after the backlog is committed, before the worker is woken.
        with patch.object(queue, 'wake'):
            backlog = [message(contacts[0]).name for _ in range(300)]
            frappe.db.commit()
            ai = message(contacts[2], ai_channel, sender_endpoint=endpoint,
                conversation_key=hashlib.sha256((tag + ':AI').encode()).hexdigest())
            frappe.db.commit()
        started = time.monotonic()
        queue.wake()
        wait(lambda: frappe.db.exists('Relay Automation Run', {'message': ai.name}))
        results['late_ai_intent_seconds'] = round(time.monotonic() - started, 3)
        wait(lambda: frappe.db.exists('Relay Automation Run', {'message': ai.name, 'status': 'Shadow'}))
        results['late_ai_shadow_seconds'] = round(time.monotonic() - started, 3)
        assert LocalAI.calls == 1
        assert results['late_ai_shadow_seconds'] < 15
        assert frappe.db.count('Relay Message', {'name': ['in', backlog], 'automation_status': 'Complete'}) == 300
        assert frappe.db.count('Relay Automation Run', {'message': ai.name}) == 1
        assert not frappe.db.exists('Relay Message Action', {'source_message': ai.name})
        queue.run_message_hooks(queue.HANDLERS, ai.name)
        assert frappe.db.count('Relay Automation Run', {'message': ai.name}) == 1

        # Kill a separate process after hooks/ack writes but before commit.
        with patch.object(queue, 'wake'):
            crash = message(contacts[2], ai_channel, sender_endpoint=endpoint,
                conversation_key=ai.conversation_key)
            frappe.db.commit()
        command = [sys.executable, '-B', str(Path(__file__).resolve())]
        assert frappe.db.sql('select get_lock(%s, 0)', (queue._lock_name(),))[0][0]
        try:
            result = subprocess.run(command + ['--contend'], capture_output=True, text=True)
            assert result.returncode == 0, 'Concurrent drain did not respect the database lock'
        finally:
            frappe.db.sql('select release_lock(%s)', (queue._lock_name(),))
        result = subprocess.run(command + ['--crash', crash.name], capture_output=True, text=True)
        assert result.returncode == 17, 'Crash injector did not reach the uncommitted acknowledgement'
        frappe.db.rollback()
        assert frappe.db.get_value('Relay Message', crash.name, 'automation_status') == 'Pending'
        assert not frappe.db.exists('Relay Automation Run', {'message': crash.name})
        queue.recover()
        wait(lambda: frappe.db.get_value('Relay Message', crash.name, 'automation_status') == 'Complete')
        wait(lambda: frappe.db.exists('Relay Automation Run', {'message': crash.name, 'status': 'Shadow'}))
        assert frappe.db.count('Relay Automation Run', {'message': crash.name}) == 1
        assert LocalAI.calls == 2
        results.update(crash_recovered=True, concurrent_drain_excluded=True, ai_calls=LocalAI.calls,
                       site='yrp.site', old_300_seconds=138, retained_fixture_prefix=tag)
        print(json.dumps(results, sort_keys=True))
    finally:
        frappe.db.rollback()
        skill.reload()
        skill.enabled = 0
        skill.save(ignore_permissions=True)
        frappe.db.commit()
        server.shutdown()
        server.server_close()
        frappe.destroy()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        connect()
        if sys.argv[1] == '--contend':
            assert queue.drain() == 0
            frappe.destroy()
        elif sys.argv[1] == '--crash':
            assert frappe.db.sql('select get_lock(%s, 0)', (queue._lock_name(),))[0][0]
            queue._process(sys.argv[2])
            os._exit(17)
        else:
            raise ValueError('Unknown benchmark mode')
    else:
        main()
