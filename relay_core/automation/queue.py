"""Durable inbound hooks, coalesced on default, away from projection queues."""
import hashlib
import time
from functools import wraps
from uuid import uuid4

import frappe
from frappe import ValidationError
from frappe.utils.background_jobs import (
    RQ_JOB_FAILURE_TTL, RQ_RESULTS_TTL, create_job_id, get_queue, truncate_failed_registry,
)
from redis.exceptions import WatchError
from rq import Callback


QUEUE = 'default'
BATCH_SIZE = 100
TURN_SECONDS = 5
WAKE_TTL = 120
HANDLERS = (
    'relay_core.translations.on_message',
    'relay_core.flows.service.on_message',
    'relay_core.automation.service.on_message',
    'relay_core.email_preferences.on_message',
)


def after_message_commit(handler):
    """Only signal after commit; no policy reads, locks or Redis during insertion."""
    @wraps(handler)
    def on_message(doc, method=None):
        if method != 'after_insert':
            return handler(doc, method)
        if doc.direction != 'Incoming' or doc.get('legacy_source'):
            return
        if not doc.flags.get('relay_deferred_message_hooks'):
            doc.flags.relay_deferred_message_hooks = True
            frappe.db.after_commit.add(wake)
    return on_message


def _signal_key():
    # Versioned because old producers put non-atomic reservations in cache Redis.
    return frappe.cache.make_key('relay-message-automation-wake:v2')


def _release_signal(token):
    # An expired enqueue reservation must not remove its successor's signal.
    get_queue(QUEUE).connection.eval("""
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        end
        return 0
    """, 1, _signal_key(), token)


def wake():
    """Publish the reservation and RQ job in one Redis transaction."""
    try:
        queue = get_queue(QUEUE)
        key = _signal_key()
        with queue.connection.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(key)
                    if pipe.get(key):
                        return
                    token = uuid4().hex
                    pipe.multi()
                    pipe.set(key, token, ex=WAKE_TTL)
                    # frappe.enqueue has no pipeline argument. Keep its worker
                    # entry point/user context, but atomically publish via RQ.
                    job = queue.enqueue_call('frappe.utils.background_jobs.execute_job',
                        kwargs=dict(site=frappe.local.site, user=frappe.session.user,
                            method='relay_core.automation.queue.drain', event=None,
                            job_name='relay_core.automation.queue.drain', is_async=True,
                            kwargs={'token': token}),
                        timeout=120, job_id=create_job_id(f'relay-message-automation-drain:{token}'),
                        failure_ttl=frappe.conf.get('rq_job_failure_ttl') or RQ_JOB_FAILURE_TTL,
                        result_ttl=frappe.conf.get('rq_results_ttl') or RQ_RESULTS_TTL,
                        on_failure=Callback(truncate_failed_registry), pipeline=pipe)
                    pipe.execute()
                    return job
                except WatchError:
                    continue
    except Exception:
        # Message projection has already committed. The scheduler retries the
        # durable marker; a Redis outage must not fail the inbound HTTP request.
        frappe.log_error(title='Relay automation wake failed',
            message='Pending message hooks will be retried by automation recovery.')


def recover():
    from relay_core.email_preferences import recover as recover_email
    recover_email()
    if frappe.db.exists('Relay Message', {'automation_status': 'Pending'}):
        wake()


def _lock_name():
    return 'relay-hooks:' + hashlib.sha256(frappe.local.site.encode()).hexdigest()[:40]


def _process(message):
    # The acknowledgement and all hook intents share this transaction. Death
    # before commit rolls both back; death afterwards cannot replay the hooks.
    status = frappe.db.get_value('Relay Message', message, 'automation_status', for_update=True)
    if status != 'Pending':
        return
    doc = frappe.get_doc('Relay Message', message)
    if doc.direction == 'Incoming' and not doc.get('legacy_source'):
        for handler in HANDLERS:
            # Pause only suppresses AI. Translation, flow and email keep their
            # independent guards (in particular translation still works paused).
            if handler == 'relay_core.automation.service.on_message' and (
                not frappe.conf.get('relay_automation_enabled') or
                frappe.db.get_value('Relay Contact', doc.relay_contact, 'automation_paused')
            ):
                continue
            frappe.get_attr(handler)(doc)
    frappe.db.set_value('Relay Message', message, 'automation_status', 'Complete', update_modified=False)


def drain(token=None):
    if frappe.db.db_type not in ('mariadb', 'postgres'):
        raise RuntimeError('Relay automation drain supports MariaDB and PostgreSQL only')
    if token:
        # Clear at START, not completion: an arrival during the final empty
        # read can always reserve a successor. Its job ID differs from ours.
        _release_signal(token)
    lock = _lock_name()
    if frappe.db.db_type == 'postgres':
        lock = int.from_bytes(hashlib.sha256(lock.encode()).digest()[:8], 'big', signed=True)
        acquire, release = 'select pg_try_advisory_lock(%s)', 'select pg_advisory_unlock(%s)'
    else:
        acquire, release = 'select get_lock(%s, 1)', 'select release_lock(%s)'
    if not frappe.db.sql(acquire, (lock,))[0][0]:
        # This job consumed its signal. The owner may already have done its
        # final empty read, so it cannot be relied on to notice this arrival.
        wake()
        return 0
    count = 0
    deadline = time.monotonic() + TURN_SECONDS
    try:
        while time.monotonic() < deadline:
            messages = frappe.get_all('Relay Message', filters={'automation_status': 'Pending'},
                pluck='name', order_by='creation asc, name asc', limit_page_length=BATCH_SIZE)
            if not messages:
                break
            for message in messages:
                try:
                    _process(message)
                except (ValueError, ValidationError) as error:
                    # Configuration failures belong to this message, not the site.
                    # Roll back partial hook intents before recording triage.
                    frappe.db.rollback()
                    from relay_core.automation.service import configuration_failure
                    configuration_failure(message, error)
                    frappe.db.set_value('Relay Message', message, 'automation_status', 'Complete', update_modified=False)
                frappe.db.commit()
                count += 1
                if time.monotonic() >= deadline:
                    break
        # End the read snapshot before releasing the site-wide ordering lock.
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        # Preserve the oldest failing message and contact order. The scheduler
        # retries; do not spin a poison message through the default queue.
        raise
    finally:
        frappe.db.sql(release, (lock,))
    recover()
    return count


def run_message_hooks(handlers, message):
    """Compatibility for jobs already queued by the per-message implementation."""
    doc = frappe.get_doc('Relay Message', message)
    if doc.direction != 'Incoming' or doc.get('legacy_source') or doc.get('automation_status') == 'Complete':
        return
    frappe.db.sql("""update `tabRelay Message` set automation_status='Pending'
        where name=%s and coalesce(automation_status, '')=''""", (message,))
    frappe.db.commit()
    return drain()
