"""Projection drain on yrp.site: a callback burst wakes one drain, order holds, a mid-drain wake is kept.

Run from the bench sites folder with CI=1 PYTHONPATH=<worktree>:<worktree>/tests
../env/bin/python -B tests/projection_drain_site.py [--events 200] [--rate 10 --seconds 30].
Real signed ingress, SQL, Redis and RQ on an isolated queue; shared workers see nothing.
--rate also runs a forking RQ worker, as a bench worker does. Fixtures are deleted.
"""
import argparse
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from integration_ai_permissions_site import SITES, confine_writes, local_fixtures
from site_labels import run_label

os.environ.update(FRAPPE_STREAM_LOGGING='1', PYTHONDONTWRITEBYTECODE='1')

SECRET = 'local-projection-drain-fixture-secret'
PHONE = '919999955561'


def connect():
    import frappe
    frappe.init(site='yrp.site', sites_path=SITES); frappe.connect()
    assert frappe.local.site == 'yrp.site' and frappe.conf.developer_mode
    frappe.set_user('Administrator')
    frappe.flags.mute_emails = True


def callback(account, event_id, provider):
    """One signed Hub callback with one location message, which never projects inline."""
    import frappe
    from relay_core import inbound
    message = {'from': PHONE, 'id': provider, 'timestamp': str(int(time.time())), 'type': 'location',
               'location': {'latitude': 13.08, 'longitude': 80.27, 'name': 'Sim', 'address': 'Sim'}}
    value = {'messaging_product': 'whatsapp', 'metadata': {'phone_number_id': 'fixture'}, 'messages': [message]}
    payload = {'account': account, 'events': [{'id': event_id, 'payload': {'object': 'whatsapp_business_account',
               'entry': [{'id': 'fixture', 'changes': [{'field': 'messages', 'value': value}]}]}}]}
    raw = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(SECRET.encode(), timestamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    frappe.local.request = SimpleNamespace(get_data=lambda: raw, headers={
        'X-Relay-Timestamp': timestamp, 'X-Relay-Signature': signature})
    assert inbound.receive()['accepted'] == 1
    frappe.db.commit()


def isolate(stack, tag, account):
    """Scope drains to this run: an own RQ queue, signals, locks and Pending rows."""
    import frappe
    from frappe.utils.background_jobs import get_redis_conn
    from rq import Queue
    from relay_core import inbound
    from relay_core.automation import projection, queue
    rq = Queue('sim-projection-drain-' + tag, connection=get_redis_conn())
    get_all = frappe.get_all
    def scoped(doctype, *args, **kwargs):
        if doctype == 'Relay Hub Event' and isinstance(kwargs.get('filters'), list):
            kwargs['filters'] = kwargs['filters'] + [['account', '=', account]]
        return get_all(doctype, *args, **kwargs)
    stack.enter_context(patch.object(queue, 'get_queue', return_value=rq))
    for kind, signal in projection.DRAINS.items():
        stack.enter_context(patch.object(signal, 'signal', f'sim-projection-wake-{kind}-{tag}'))
        stack.enter_context(patch.object(signal, 'lock', f'sim-{kind}-{tag[-12:]}'))
    stack.enter_context(patch.object(frappe, 'get_all', side_effect=scoped))
    stack.enter_context(patch.object(queue, 'wake'))  # Fixture messages stay out of automation.
    stack.enter_context(patch.object(frappe, 'enqueue'))
    stack.enter_context(patch.object(frappe, 'publish_realtime'))
    stack.enter_context(patch.object(inbound, 'connection_value', side_effect=lambda key: {
        'relay_hub_account': account, 'relay_callback_secret': SECRET}.get(key)))
    return rq


def take_job(rq):
    """Simulate a worker picking up the only queued drain job."""
    jobs = rq.get_jobs()
    assert len(jobs) == 1, [job.id for job in jobs]
    kwargs = jobs[0].kwargs['kwargs']
    jobs[0].delete()
    return kwargs


def burst(account, events, start):
    for index in range(events):
        callback(account, start + index, f'wamid.sim-drain.{account}.{start + index}')


def check_burst_and_mid_drain_wake(rq, account, events):
    import frappe
    from relay_core.automation import projection
    burst(account, events, 1)
    assert rq.count == 1, f'{events} callbacks woke {rq.count} drain jobs'
    kwargs = take_job(rq)
    late = []
    project = projection.project_committed
    def project_and_receive(name):
        if not late:
            late.append(True)
            def arrive():
                connect()
                try:
                    callback(account, events + 1, f'wamid.sim-drain.{account}.{events + 1}')
                finally:
                    frappe.destroy()
            worker = threading.Thread(target=arrive); worker.start(); worker.join(timeout=30)
        return project(name)
    with patch.object(projection, 'project_committed', side_effect=project_and_receive):
        assert projection.drain(**kwargs) == events + 1
    assert rq.count == 1, 'A wake during the drain did not reserve a successor'
    assert projection.drain(**take_job(rq)) == 0
    providers = frappe.get_all('Relay Message', filters={'sender_endpoint': PHONE, 'provider_id': ['like', f'%.{account}.%']},
                               pluck='provider_id', order_by='creation asc, name asc')
    assert providers == [f'wamid.sim-drain.{account}.{index}' for index in range(1, events + 2)], providers
    assert not frappe.db.exists('Relay Hub Event', {'account': account, 'projection_status': 'Pending'})


def measure(rq, account, events, start):
    from relay_core.automation import projection
    burst(account, events, start)
    kwargs = take_job(rq)
    started = time.perf_counter()
    assert projection.drain(**kwargs) == events
    seconds = time.perf_counter() - started
    return {'events': events, 'drain_seconds': round(seconds, 3), 'events_per_second': round(events / seconds, 1)}


def trace_path(tag):
    return Path('/tmp/relay-projection-drain-' + tag + '.jsonl')


def run_worker(tag, account):
    """Child process: a forking RQ worker on the isolated queue that records its inserts."""
    from frappe.model.base_document import BaseDocument
    from rq import Worker
    connect()
    original = BaseDocument.db_insert
    def tracked(doc, *args, **kwargs):
        result = original(doc, *args, **kwargs)
        with trace_path(tag).open('a') as stream:
            stream.write(json.dumps([doc.doctype, doc.name]) + '\n')
        return result
    with ExitStack() as stack:
        rq = isolate(stack, tag, account)
        stack.enter_context(patch.object(BaseDocument, 'db_insert', tracked))
        Worker([rq], connection=rq.connection).work(max_idle_time=5, logging_level='ERROR')


def paced(rq, account, tag, rate, seconds):
    """Callbacks at a fixed rate against a real worker; lag is message insert minus callback start."""
    import frappe
    worker = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--worker', tag, account])
    time.sleep(3)
    sent = {}
    started = time.monotonic()
    for index in range(rate * seconds):
        time.sleep(max(0, started + index / rate - time.monotonic()))
        provider = f'wamid.sim-drain.{account}.{5000 + index}'
        sent[provider] = frappe.utils.now_datetime()
        callback(account, 5000 + index, provider)
    deadline = time.monotonic() + 60
    while frappe.db.exists('Relay Hub Event', {'account': account, 'projection_status': 'Pending'}):
        assert time.monotonic() < deadline, 'Projection did not catch up'
        time.sleep(.2); frappe.db.rollback()
    assert worker.wait(timeout=60) == 0
    rows = frappe.get_all('Relay Message', filters={'provider_id': ['in', list(sent)]}, fields=['provider_id', 'creation'])
    assert len(rows) == len(sent)
    lag = sorted((row.creation - sent[row.provider_id]).total_seconds() for row in rows)
    jobs = rq.finished_job_registry.count
    assert not rq.failed_job_registry.count
    return {'rate': rate, 'events': len(sent), 'drain_jobs': jobs, 'p50_seconds': round(lag[len(lag) // 2], 3),
            'p95_seconds': round(lag[math.ceil(len(lag) * .95) - 1], 3), 'max_seconds': round(lag[-1], 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', type=int, default=200)
    parser.add_argument('--rate', type=int, default=0, help='Callbacks per second for the worker run')
    parser.add_argument('--seconds', type=int, default=30)
    args = parser.parse_args()
    os.chdir(SITES)
    connect()
    import frappe
    from relay_core.automation import projection
    tag = run_label()
    label, account = 'Sim Drain ' + tag, 'sim-drain-' + tag
    with local_fixtures() as created, ExitStack() as stack:
        rq = isolate(stack, tag, account)
        try:
            base = frappe.get_doc('Relay Contact', {'display_name': ['like', 'Local simulation%'], 'automation_paused': 1})
            links = [dict(link_doctype=row.link_doctype, link_name=row.link_name) for row in frappe.get_doc('Contact', base.contact).links]
            assert len(links) == 1
            person = frappe.get_doc(dict(doctype='Contact', first_name=label, links=links)).insert()
            contact = frappe.get_doc(dict(doctype='Relay Contact', contact=person.name, display_name=label, automation_paused=1)).insert()
            channel = frappe.get_doc(dict(doctype='Relay Channel', channel='WhatsApp', account=account, enabled=1)).insert()
            frappe.get_doc(dict(doctype='Relay Contact Endpoint', channel=channel.name, endpoint=PHONE,
                                relay_contact=contact.name, verified=1)).insert()
            frappe.db.commit()
            check_burst_and_mid_drain_wake(rq, account, 20)
            print('PASS projection drain: 20 callbacks woke one drain job, all projected in order, '
                  'a callback during the drain reserved one successor that found nothing left')
            print(json.dumps(dict(measurement=measure(rq, account, args.events, 1000), site='yrp.site'), sort_keys=True))
            if args.rate:
                print(json.dumps(dict(worker=paced(rq, account, tag, args.rate, args.seconds), site='yrp.site'), sort_keys=True))
        finally:
            if trace_path(tag).exists():
                created.extend(tuple(json.loads(line)) for line in trace_path(tag).read_text().splitlines())
            from rq.job import Job
            from rq.results import Result
            for registry in (rq.finished_job_registry, rq.failed_job_registry):
                for job_id in registry.get_job_ids():
                    Result.delete_all(Job.fetch(job_id, connection=rq.connection))
                    registry.remove(job_id, delete_job=True)
            for job in rq.get_jobs():
                job.delete()
            for signal in projection.DRAINS.values():
                rq.connection.delete(signal.signal_key)
            rq.delete()


if __name__ == '__main__':
    sys.addaudithook(confine_writes)
    if sys.argv[1:2] == ['--worker']:
        os.chdir(SITES)
        run_worker(*sys.argv[2:4])
    else:
        main()
