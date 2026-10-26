"""Step 13: isolated RQ load, process death and Redis failure on yrp.site.

Use bench Python -B with this worktree first on PYTHONPATH. Only test channels
are drained. Providers are blocked and all inserted fixtures are deleted.
"""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler
from unittest.mock import patch

from integration_ai_permissions_site import confine_writes, local_fixtures, SITES
from site_labels import run_label

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = str(Path(__file__).resolve())
os.environ.update(FRAPPE_STREAM_LOGGING='1', PYTHONDONTWRITEBYTECODE='1', SITES_PATH=SITES)


# Retain the loopback provider used by the separate core_defects_site driver.
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


def connect():
    import frappe
    import relay_core
    assert Path(relay_core.__file__).resolve().parents[1] == ROOT
    os.chdir(SITES)
    frappe.init(site='yrp.site', sites_path=SITES); frappe.connect()
    assert frappe.local.site == 'yrp.site' and frappe.conf.developer_mode
    frappe.set_user('Administrator')
    frappe.flags.mute_emails = True
    frappe.conf.relay_automation_enabled = 1


def trace_path(tag):
    return Path('/tmp/relay-event-load-' + tag + '.jsonl')


@contextmanager
def isolated(tag, *, child=False):
    """Real SQL, Redis and RQ; restrict work and cleanup to this run's records."""
    import frappe
    from frappe.model.base_document import BaseDocument
    from frappe.utils.background_jobs import get_redis_conn
    from rq import Queue
    from relay_core.automation import queue
    rq = Queue('sim-event-load-' + tag, connection=get_redis_conn())
    original_all, original_exists = frappe.get_all, type(frappe.local.db).exists
    original_insert, original_init = BaseDocument.db_insert, frappe.init
    def scope(filters):
        if filters == {'automation_status': 'Pending'}:
            channels = original_all('Relay Channel', filters={'account': 'Sim Load ' + tag}, pluck='name')
            return dict(filters, channel=['in', channels])
        return filters
    def get_all(doctype, *args, **kwargs):
        if doctype == 'Relay Message' and 'filters' in kwargs:
            kwargs['filters'] = scope(kwargs['filters'])
        return original_all(doctype, *args, **kwargs)
    def exists(db, doctype, filters=None, *args, **kwargs):
        return original_exists(db, doctype, scope(filters) if doctype == 'Relay Message' else filters, *args, **kwargs)
    def tracked(doc, *args, **kwargs):
        result = original_insert(doc, *args, **kwargs)
        with trace_path(tag).open('a') as stream:
            stream.write(json.dumps([doc.doctype, doc.name]) + '\n')
        return result
    def init(*args, **kwargs):
        result = original_init(*args, **kwargs)
        assert frappe.local.site == 'yrp.site'
        frappe.conf.relay_automation_enabled = 1
        frappe.flags.mute_emails = True
        return result
    with ExitStack() as stack:
        stack.enter_context(patch.object(queue, 'get_queue', return_value=rq))
        stack.enter_context(patch.object(queue.AUTOMATION, 'signal', 'sim-event-wake-' + tag))
        stack.enter_context(patch.object(queue.AUTOMATION, 'lock', 'sim-lock-' + tag[-12:]))
        stack.enter_context(patch.object(frappe, 'get_all', side_effect=get_all))
        stack.enter_context(patch.object(type(frappe.local.db), 'exists', exists))
        stack.enter_context(patch.object(frappe, 'init', side_effect=init))
        stack.enter_context(patch('frappe.utils.background_jobs.get_queue', return_value=rq))
        stack.enter_context(patch.object(frappe, 'publish_realtime'))
        stack.enter_context(patch.object(frappe, 'sendmail'))
        stack.enter_context(patch('relay_core.email_preferences.recover'))
        stack.enter_context(patch('relay_core.messaging.connection_value', return_value='Sim Load ' + tag))
        stack.enter_context(patch('relay_core.whatsapp.client', side_effect=AssertionError('External delivery forbidden')))
        stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('External HTTP forbidden')))
        if child:
            stack.enter_context(patch.object(BaseDocument, 'db_insert', tracked))
        yield rq


def run_child(mode, tag, message=None):
    command = [sys.executable, '-B', SCRIPT, mode, tag] + ([message] if message else [])
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    expected = 17 if mode == '--crash' else 0
    if result.returncode != expected:
        Path('/tmp/relay-event-load-child.log').write_text(result.stdout + result.stderr)
        raise AssertionError('Isolated worker failed; see /tmp/relay-event-load-child.log')


def main():
    import frappe
    from relay_core.automation import queue
    from relay_core.automation.provenance import conversation_key
    from relay_core.permissions import sequential_name
    from redis.exceptions import ConnectionError
    from rq.job import Job
    connect()
    tag = run_label()
    with local_fixtures() as created, isolated(tag) as rq:
        try:
            def raw(doctype, label, **values):
                doc = frappe.get_doc(dict(doctype=doctype, name='Sim ' + label + ' ' + tag, **values))
                doc.db_insert(); return doc
            company = raw('Company', 'Load Company', company_name='Sim Load Company ' + tag,
                abbr='SL', country='India', default_currency='INR')
            from channel_site_fixtures import user
            with patch.object(frappe, 'enqueue'):
                actor = user('sim-load-' + tag.lower() + '@example.invalid', manager=True)
                operator = frappe.get_doc('User', actor)
                operator.append('roles', {'role': 'Purchase Manager'})
                operator.save()
            supplier = raw('Supplier', 'Load Supplier', supplier_name='Sim Load Supplier ' + tag,
                supplier_type='Company', alias='sim-load-' + tag.lower() + '@example.invalid')
            person = frappe.get_doc(dict(doctype='Contact', first_name='Sim Load Person ' + tag,
                links=[dict(link_doctype='Supplier', link_name=supplier.name)])).insert()
            contact = frappe.get_doc(dict(doctype='Relay Contact', contact=person.name,
                display_name='Sim Load Contact ' + tag)).insert()
            channel = frappe.get_doc(dict(doctype='Relay Channel', channel='Email', account='Sim Load ' + tag,
                enabled=1, company=company.name, triage_owner=actor)).insert(set_name=sequential_name('channel'))
            frappe.get_doc(dict(doctype='Relay Contact Endpoint', channel=channel.name, endpoint=supplier.alias,
                relay_contact=contact.name, verified=1)).insert()
            event = raw('Relay AI Skill', 'Load Support', title='Sim Load Support ' + tag,
                enabled=1, channel=channel.name, business_doctype='Supplier', mode='Automatic',
                target='Review payment evidence', instructions='Raise the ticket for staff to review amount 1250.',
                exact_trigger='Payment evidence amount 1250', execution_policy='Ticket only',
                run_as_user=actor, handoff_owner=actor, daily_limit=1000, allowed_tools='[]', allowed_actions='[]')
            def message(label, **extra):
                label = label.replace(' ', '-')
                context = dict(provider='Email', message_id='<sim-' + label + '-' + tag + '@example.invalid>',
                    email_thread_id='<sim-' + label + '-' + tag + '@example.invalid>', authentication={'status':'pass'})
                return frappe.get_doc(dict(doctype='Relay Message', channel=channel.name,
                    relay_contact=contact.name, sender_endpoint=supplier.alias, business_doctype='Supplier',
                    business_name=supplier.name, direction=extra.pop('direction', 'Incoming'),
                    content=event.exact_trigger, message_type='text', provider_context=json.dumps(context),
                    conversation_key=conversation_key(channel.name, supplier.alias, context), **extra)).insert()
            frappe.db.commit()
            # Fault before atomic EXEC: neither a reservation nor a job can escape.
            with patch.object(rq, 'enqueue_call', side_effect=SystemExit('Injected producer death')):
                try: queue.wake()
                except SystemExit: pass
                else: raise AssertionError('Producer did not die')
            assert not rq.connection.get(queue.AUTOMATION.signal_key) and rq.count == 0
            # Redis loss at commit cannot lose the durable message marker.
            with patch.object(queue, 'get_queue', side_effect=ConnectionError('Injected queue outage')):
                first = message('Redis Recovery'); frappe.db.commit()
            assert frappe.db.get_value('Relay Message', first.name, 'automation_status') == 'Pending'
            assert not frappe.db.exists('Relay Automation Run', {'message': first.name})
            assert rq.count == 0 and not rq.connection.get(queue.AUTOMATION.signal_key)
            batch = [first.name]
            with patch.object(queue, 'wake'):
                for index in range(79):
                    batch.append(message('Conversation ' + str(index + 1)).name)
                ignored = [message('Outgoing', direction='Outgoing'), message('Import', legacy_source='Sim Load ' + tag)]
                frappe.db.commit()
            assert all(not row.automation_status for row in ignored)
            started = time.monotonic()
            queue.recover()
            assert rq.count == 1
            # Process contention also proves the database lock releases on exit.
            assert frappe.db.sql('select get_lock(%s, 0)', (queue.AUTOMATION.lock_name,))[0][0]
            try: run_child('--contend', tag)
            finally: frappe.db.sql('select release_lock(%s)', (queue.AUTOMATION.lock_name,))
            run_child('--work', tag)
            frappe.db.rollback()
            runs = frappe.get_all('Relay Automation Run', filters={'message':['in', batch]}, fields=['name','status','ticket','stage','reason'])
            assert len(runs) == len(batch) and all(row.status == 'Completed' and row.ticket for row in runs), (len(runs), {(row.status, row.stage, row.reason) for row in runs})
            assert len({row.ticket for row in runs}) == len(batch)
            assert frappe.db.count('Relay Message', {'name':['in',batch], 'automation_status':'Complete'}) == len(batch)
            assert not frappe.db.exists('Relay Message Action', {'source_message':['in',batch]})
            elapsed = round(time.monotonic() - started, 3)
            assert elapsed < 60, 'Local 80-episode acceptance exceeded 60 seconds'
            # SQL timestamps include backlog wait, admission, and the worker turn.
            # Ticket only does not call a model or produce a first/complete reply.
            timings = frappe.db.sql('''select timestampdiff(microsecond, m.creation, t.creation)/1000 as ticket_ms,
                timestampdiff(microsecond, m.creation, r.modified)/1000 as complete_ms
                from `tabRelay Message` m join `tabRelay Automation Run` r on r.message=m.name
                join `tabRelay Ticket` t on t.name=r.ticket where m.name in %(messages)s''',
                {'messages': batch}, as_dict=True)
            def latency(field):
                values = sorted(float(row[field]) for row in timings)
                return {'p50_ms': round(values[math.ceil(len(values)*.5)-1], 2),
                        'p95_ms': round(values[math.ceil(len(values)*.95)-1], 2), 'max_ms': round(values[-1], 2)}
            from relay_core import tickets
            claim_started = time.monotonic()
            tickets.claim(runs[0].ticket); frappe.db.commit()
            takeover_ms = round((time.monotonic() - claim_started) * 1000, 2)
            assert frappe.db.get_value('Relay Ticket', runs[0].ticket, 'ai_disabled')
            before = {row.name for row in runs}
            queue.wake(); run_child('--work', tag); frappe.db.rollback()
            assert set(frappe.get_all('Relay Automation Run', filters={'message':['in',batch]}, pluck='name')) == before
            # Process death after ticket/run/ack writes, before commit, rolls all back.
            with patch.object(queue, 'wake'):
                crash = message('Worker Recovery'); frappe.db.commit()
            run_child('--crash', tag, crash.name)
            frappe.db.rollback()
            assert frappe.db.get_value('Relay Message', crash.name, 'automation_status') == 'Pending'
            assert not frappe.db.exists('Relay Automation Run', {'message': crash.name})
            assert not frappe.db.get_value('Relay Message', crash.name, 'ticket')
            queue.recover(); run_child('--work', tag); frappe.db.rollback()
            assert frappe.db.count('Relay Automation Run', {'message':crash.name, 'status':'Completed'}) == 1
            ticket = frappe.db.get_value('Relay Message', crash.name, 'ticket')
            assert ticket and frappe.db.count('Relay Ticket', {'conversation_key':crash.conversation_key}) == 1
            assert frappe.db.get_value('Relay Message', crash.name, 'automation_status') == 'Complete'
            print(json.dumps(dict(site='yrp.site', episodes=len(batch), seconds=elapsed, ticket_only=True,
                redis_outage_recovered=True, atomic_enqueue=True, process_death_recovered=True,
                concurrent_drain_excluded=True, replay_idempotent=True, external_sends=0,
                ticket_latency=latency("ticket_ms"), completion_latency=latency("complete_ms"),
                takeover_ms=takeover_ms, model_calls=0), sort_keys=True))
        finally:
            # Child inserts use an append-only local manifest, including rows from
            # crashed transactions. Only these exact test rows enter cleanup.
            if trace_path(tag).exists():
                created.extend(tuple(json.loads(line)) for line in trace_path(tag).read_text().splitlines())
            for job in rq.get_jobs() + [Job.fetch(name, connection=rq.connection)
                    for name in rq.finished_job_registry.get_job_ids() + rq.failed_job_registry.get_job_ids()]:
                job.delete()
            rq.connection.delete(queue.AUTOMATION.signal_key)
            rq.delete()
    frappe.destroy()


if __name__ == '__main__':
    sys.addaudithook(confine_writes)
    if len(sys.argv) > 1:
        import frappe
        from relay_core.automation import queue
        from rq import SimpleWorker
        mode, tag = sys.argv[1:3]
        connect()
        with isolated(tag, child=True) as rq:
            if mode == '--crash':
                with patch.object(frappe, 'enqueue'):
                    queue._process(sys.argv[3])
                    assert frappe.db.get_value('Relay Message', sys.argv[3], 'automation_status') == 'Complete'
                    assert frappe.db.exists('Relay Automation Run', {'message':sys.argv[3]})
                    os._exit(17)
            elif mode == '--contend':
                token = rq.connection.get(queue.AUTOMATION.signal_key)
                assert token and queue.drain(token=token.decode()) == 0
                assert rq.connection.get(queue.AUTOMATION.signal_key) != token and rq.count == 2
            elif mode == '--work':
                SimpleWorker([rq], connection=rq.connection).work(burst=True, logging_level='ERROR')
                assert not rq.failed_job_registry.count
            else:
                raise ValueError('Unknown test mode')
        frappe.destroy()
    else:
        main()
