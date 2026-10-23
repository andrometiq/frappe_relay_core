"""Automation uses the default queue, served separately from short/long projection."""
from functools import wraps

import frappe


QUEUE = 'default'


def message_job_id(message):
    return f'relay-message-automation:{message}'


def after_message_commit(handler):
    """Keep policy reads, locks and intent creation out of message insertion."""
    path = f'{handler.__module__}.{handler.__name__}'

    @wraps(handler)
    def on_message(doc, method=None):
        if method != 'after_insert':
            return handler(doc, method)
        if doc.direction != 'Incoming' or doc.get('legacy_source'):
            return
        handlers = doc.flags.get('relay_deferred_message_hooks')
        if handlers is None:
            handlers = doc.flags.relay_deferred_message_hooks = []
            # One job preserves hook order without a worker startup per hook.
            # Defer even Redis access until the message transaction is committed.
            frappe.db.after_commit.add(lambda: frappe.enqueue(
                'relay_core.automation.queue.run_message_hooks', handlers=handlers, message=doc.name,
                queue=QUEUE, timeout=120, job_id=message_job_id(doc.name), deduplicate=True))
        handlers.append(path)

    return on_message


def run_message_hooks(handlers, message):
    doc = frappe.get_doc('Relay Message', message)
    for handler in handlers:
        frappe.get_attr(handler)(doc)
