"""Two transactions on one conversation, with innodb_snapshot_isolation on and off: the automation drain locks the
Relay Message and its Relay Contact, then episode admission locks the Relay Business Routing row; projection of the
next inbound message resolves business routing and then records contact activity. Both lock the contact before the
routing row, so projection waits for the drain instead of failing one of them with 1213 "Deadlock found".
Run from the bench sites folder: PYTHONPATH=<worktree>:<worktree>/tests CI=1 ../env/bin/python -B <this file>
"""
import threading
import time
from pathlib import Path
from unittest.mock import patch
import frappe
from frappe import _dict
from site_labels import phone, run_label

SITE = 'yrp.site'
SITES = str(Path.cwd())
WAIT = 1.5  # Long enough for projection to reach its locks; short against innodb_lock_wait_timeout.
frappe.init(site=SITE)
frappe.connect()
frappe.set_user('Administrator')
from relay_core import business_routing, inbox, tickets  # noqa: E402
from relay_core.automation import queue  # noqa: E402
from relay_core.automation.provenance import conversation_key  # noqa: E402
from relay_core.automation.service import internal_save  # noqa: E402
assert Path(queue.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1]), 'Run with this checkout first on PYTHONPATH'

label = 'Sim Routing Locks ' + run_label()
created, state = [], {}


def insert(values):
    doc = frappe.get_doc(values).insert(ignore_permissions=True)
    created.append(doc)
    return doc


def project_next_message(setting):
    """Projection's lock steps for a new inbound message of the same contact, on a second connection."""
    frappe.init(site=SITE, sites_path=SITES)
    frappe.connect()
    try:
        frappe.set_user('Administrator')
        frappe.db.sql('SET SESSION innodb_snapshot_isolation=%s', setting)
        row = {'id': f'{label}-{setting}', 'from': state['number'], 'type': 'text', 'text': {'body': 'Next'}}
        business_routing.resolve(state['contact'], state['channel'], state['number'], dict(state['context']), row,
                                 _dict(name=None, creation=frappe.utils.now_datetime()))
        inbox.message_created(_dict(relay_contact=state['contact'], name=state['message'],
                                    sent_at=frappe.utils.now_datetime()))
        frappe.db.commit()
        state['committed_at'] = time.monotonic()
    except Exception as error:
        state['worker_error'] = repr(error)
        frappe.db.rollback()
    finally:
        frappe.destroy()


def admit(doc):
    """The drain hook after _process locked the message and contact: admission locks the routing row."""
    worker = threading.Thread(target=project_next_message, args=(state['setting'],))
    worker.start()
    worker.join(WAIT)
    state['blocked'] = worker.is_alive()
    state['worker'] = worker
    tickets._lock_episode_routing(doc, state['conversation'])


def drain_case(setting):
    state.update(setting=setting, worker_error=None, committed_at=None)
    frappe.db.sql('SET SESSION innodb_snapshot_isolation=%s', setting)  # This connection only.
    frappe.db.set_value('Relay Message', state['message'], 'automation_status', 'Pending', update_modified=False)
    frappe.db.commit()
    hook = 'relay_core.automation.service.on_message'
    error = None
    try:
        with patch.object(queue, 'HANDLERS', (hook,)), patch(hook, admit):
            queue._process(state['message'])
        frappe.db.commit()
    except frappe.QueryDeadlockError as exc:
        error = repr(exc)
        frappe.db.rollback()
    committed = time.monotonic()
    state.pop('worker').join(60)
    assert not error and not state['worker_error'], (setting, error, state['worker_error'])
    assert state['blocked'] and state['committed_at'] >= committed, 'Projection did not wait for the drain'
    assert frappe.db.get_value('Relay Message', state['message'], 'automation_status') == 'Complete'
    return True


try:
    frappe.db.sql('SET SESSION innodb_snapshot_isolation=0')  # Fixture names must not fail on concurrent series use.
    with patch('relay_core.automation.queue.wake'):
        channel = insert({'doctype': 'Relay Channel', 'channel': 'WhatsApp', 'account': label, 'enabled': 1})
        contact = insert({'doctype': 'Relay Contact', 'display_name': label,
                          'contact': insert({'doctype': 'Contact', 'first_name': label}).name})
        number = phone(label)
        frappe.flags.relay_contact_sync = True
        insert({'doctype': 'Relay Contact Endpoint', 'channel': channel.name, 'relay_contact': contact.name,
                'endpoint': number, 'verified': 1})
        message = insert({'doctype': 'Relay Message', 'relay_contact': contact.name, 'channel': channel.name,
                          'direction': 'Incoming', 'status': 'Sent', 'content': 'Hello', 'sender_endpoint': number,
                          'message_type': 'text'})
        frappe.db.set_value('Relay Message', message.name, 'automation_status', 'Complete', update_modified=False)
        context = {'provider': 'WhatsApp', 'participant_id': number, 'message_id': label}
        conversation = conversation_key(channel.name, number, context)
        routing = frappe.get_doc({'doctype': 'Relay Business Routing', 'conversation_key': conversation,
                                  'relay_contact': contact.name, 'channel': channel.name, 'endpoint': number})
        internal_save(routing, new=True)
        created.append(routing)
        frappe.db.commit()
    state.update(channel=channel.name, contact=contact.name, number=number, message=message.name, context=context,
                 conversation=conversation)
    results = {setting: drain_case(setting) for setting in (1, 0)}
    assert results == {1: True, 0: True}, results
    print('PASS routing locks: with innodb_snapshot_isolation on and off, projection of the next message waited for '
          'the drain that held the contact and admitted the episode routing row; no 1213 deadlock')
finally:
    frappe.db.rollback()
    frappe.flags.relay_contact_sync = True
    for doc in reversed(created):
        frappe.delete_doc(doc.doctype, doc.name, ignore_permissions=True, force=True)
    frappe.db.commit()
    frappe.destroy()
