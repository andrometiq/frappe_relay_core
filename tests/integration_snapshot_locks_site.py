"""Two transactions on one Relay Contact and the Relay Message series, with innodb_snapshot_isolation on and off:
the automation drain and a campaign timeline batch take their locks before their first plain read, so another
worker's commit makes them wait instead of failing with 1020 "Record has changed since last read".
Run from the bench sites folder: PYTHONPATH=<worktree>:<worktree>/tests CI=1 ../env/bin/python -B <this file>
"""
import threading
import time
from pathlib import Path
from unittest.mock import patch
import frappe
from frappe import _dict
from frappe.model.naming import getseries
from site_labels import phone, run_label

SITE = 'yrp.site'
SITES = str(Path.cwd())
WAIT = 1.5  # Long enough for another worker's commit; short against innodb_lock_wait_timeout.
frappe.init(site=SITE)
frappe.connect()
frappe.set_user('Administrator')
from relay_core import bulk_timeline  # noqa: E402
from relay_core.automation import queue  # noqa: E402
from relay_core.automation.service import lock_contact  # noqa: E402
assert Path(queue.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1]), 'Run with this checkout first on PYTHONPATH'

label = 'Sim Snapshot ' + run_label()
TEMPLATE = {'name': 'sim_offer', 'language': 'en', 'components': [{'type': 'BODY', 'text': 'Offer {{1}}'}]}
created, state = [], {}


def insert(values):
    doc = frappe.get_doc(values).insert(ignore_permissions=True)
    created.append(doc)
    return doc


def other_worker(*steps):
    """Run each step in its own committed transaction on a second connection; returns its finish event."""
    done = threading.Event()

    def run():
        frappe.init(site=SITE, sites_path=SITES)
        frappe.connect()
        try:
            for step in steps:
                step()
                frappe.db.commit()
            state['committed_at'] = time.monotonic()
        finally:
            frappe.destroy()
            done.set()
    state['worker'] = threading.Thread(target=run)
    state['worker'].start()
    return done


def touch_contact():
    frappe.db.set_value('Relay Contact', state['contact'], 'last_message_at', frappe.utils.now_datetime(),
                        update_modified=False)


def contend(doc):
    """A hook after the drain's plain reads: a new message changes the contact, then automation locks it."""
    state['blocked'] = not other_worker(touch_contact).wait(WAIT)
    lock_contact(doc.relay_contact)


def drain_case():
    message = state['message']
    frappe.db.set_value('Relay Message', message, 'automation_status', 'Pending', update_modified=False)
    hook = 'relay_core.automation.service.on_message'
    with patch.object(queue, 'HANDLERS', (hook,)), patch(hook, contend):
        queue._process(message)
    frappe.db.commit()
    return finish()


def timeline_case():
    frappe.get_all('Relay Contact', filters={'name': state['contact']}, limit_page_length=1)  # Opens a snapshot.
    other_worker(lambda: getseries(bulk_timeline.SERIES, 10)).wait(WAIT)  # Another Relay Message takes a name.
    state.pop('worker').join(30)
    state.pop('committed_at')
    rows = [_dict(request_key=f'{label}-{state["run"]}-{index}', destination=state['number'],
                  components=[{'type': 'body', 'parameters': [{'type': 'text', 'text': str(index)}]}]) for index in range(3)]
    first = bulk_timeline.reserve(len(rows))
    get_all = frappe.get_all

    def read_then_contend(doctype, *args, **kwargs):
        result = get_all(doctype, *args, **kwargs)
        if doctype == 'Relay Message':
            state['blocked'] = not other_worker(touch_contact).wait(WAIT)
        return result
    with patch.object(frappe, 'get_all', read_then_contend), patch.object(frappe, 'publish_realtime'):
        bulk_timeline.record(_dict(name=label, channel=state['channel'], template_name='sim_offer', language='en'),
                             {'template': TEMPLATE}, rows, first)
    frappe.db.commit()
    stored = frappe.get_all('Relay Message', filters={'source_key': ['like', f'{label}-{state["run"]}-%']}, pluck='name')
    assert len(stored) == 3, stored
    return finish()


def finish():
    committed = time.monotonic()
    state.pop('worker').join(30)
    assert state['blocked'] and state.pop('committed_at') >= committed, 'The other worker did not wait for the lock'
    return True


try:
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
        frappe.db.commit()
    state.update(channel=channel.name, contact=contact.name, number=number, message=message.name)
    results = {}
    for setting in (1, 0):
        frappe.db.commit()
        frappe.db.sql('SET SESSION innodb_snapshot_isolation=%s', setting)  # This connection only.
        state['run'] = setting
        results[setting] = (drain_case(), timeline_case())
    assert results == {1: (True, True), 0: (True, True)}, results
    print('PASS snapshot locks: with innodb_snapshot_isolation on and off, the drain and a timeline batch held the '
          'contact lock while another worker changed the contact and took a Relay Message name; no 1020, the other '
          'worker committed after them')
finally:
    frappe.db.rollback()
    frappe.flags.relay_contact_sync = True
    for name in frappe.get_all('Relay Message', filters={'source_key': ['like', f'{label}-%']}, pluck='name'):
        frappe.delete_doc('Relay Message', name, ignore_permissions=True, force=True)
    for doc in reversed(created):
        frappe.delete_doc(doc.doctype, doc.name, ignore_permissions=True, force=True)
    frappe.db.commit()
    frappe.destroy()
