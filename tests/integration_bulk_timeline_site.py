"""Campaign sends in contact timelines on a real site: one batched insert, Hub status updates and reply quotes.
Run from the bench sites folder: PYTHONPATH=<worktree>:<worktree>/tests CI=1 ../env/bin/python -B <this file>
"""
import json
import secrets
import time
from pathlib import Path
from unittest.mock import patch
import frappe
from frappe import _dict
from site_labels import phone

SITE = 'yrp.site'
frappe.init(site=SITE)
frappe.connect()
frappe.set_user('Administrator')
from relay_core import api, bulk_timeline  # noqa: E402
from relay_core.message_updates import provider_key  # noqa: E402
assert Path(bulk_timeline.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1]), 'Run with this checkout first on PYTHONPATH'

words = '-'.join(secrets.choice(('cedar', 'maple', 'birch', 'willow', 'olive', 'alder')) for _ in range(3))
label = 'Timeline check ' + words
TEMPLATE = {'name': 'winter_offer', 'language': 'en', 'components': [
    {'type': 'HEADER', 'format': 'TEXT', 'text': 'Hello {{1}}'},
    {'type': 'BODY', 'text': 'Your {{1}} discount is ready'},
    {'type': 'FOOTER', 'text': 'Reply STOP to opt out'},
    {'type': 'BUTTONS', 'buttons': [{'type': 'QUICK_REPLY', 'text': 'Show offers'}]}]}
created = []


def insert(values):
    doc = frappe.get_doc(values).insert(ignore_permissions=True)
    created.append(doc)
    return doc


try:
    channel = insert({'doctype': 'Relay Channel', 'channel': 'WhatsApp', 'account': 'timeline-' + words, 'enabled': 1})
    people = [insert({'doctype': 'Relay Contact', 'display_name': f'{label} person {side}',
                      'contact': insert({'doctype': 'Contact', 'first_name': f'{label} person {side}'}).name})
              for side in ('one', 'two')]
    numbers = [phone(f'{label} {index}') for index in range(50)]
    frappe.flags.relay_contact_sync = True
    for index, number in enumerate(numbers[:40]):  # The last ten numbers have no Relay Contact.
        insert({'doctype': 'Relay Contact Endpoint', 'channel': channel.name, 'relay_contact': people[index % 2].name,
                'endpoint': number, 'verified': 1})
    frappe.db.commit()
    doc = _dict(name=label, channel=channel.name, template_name='winter_offer', language='en')
    rows = [_dict(request_key=f'bulk-timeline-{words}-{index}', destination=number, message={'components': [
                  {'type': 'header', 'parameters': [{'type': 'text', 'text': f'Customer {index}'}]},
                  {'type': 'body', 'parameters': [{'type': 'text', 'text': 'winter'}]}]})
            for index, number in enumerate(numbers)]
    with patch.object(frappe, 'publish_realtime') as realtime:
        started = time.perf_counter()
        bulk_timeline.record(doc, {'template': TEMPLATE}, rows, bulk_timeline.reserve(len(rows)))
        frappe.db.commit()
        elapsed = time.perf_counter() - started
        bulk_timeline.record(doc, {'template': TEMPLATE}, rows, bulk_timeline.reserve(len(rows)))  # A repeat inserts nothing.
        frappe.db.commit()
    assert realtime.call_count == 1, realtime.call_args_list
    keys = [row.request_key for row in rows]
    stored = frappe.get_all('Relay Message', filters={'source_key': ['in', keys]},
                            fields=['name', 'source_key', 'relay_contact', 'status', 'content', 'message_data', 'direction'],
                            order_by='name asc', limit_page_length=0)
    assert len(stored) == 40, len(stored)
    first = stored[0]
    data = json.loads(first.message_data)
    assert (first.direction, first.status, first.content) == ('Outgoing', 'Pending', 'Your winter discount is ready'), first
    assert (data['campaign'], data['template']['header'], data['template']['footer'], data['template']['buttons']) == \
        (label, 'Hello Customer 0', 'Reply STOP to opt out', ['Show offers']), data
    latest = {person.name: frappe.db.get_value('Relay Contact', person.name, 'last_message') for person in people}
    assert latest == {people[0].name: stored[-2].name, people[1].name: stored[-1].name}, latest

    with patch.object(frappe, 'publish_realtime'):
        bulk_timeline.apply([{'key': keys[0], 'status': 'Read', 'message_id': 'wamid.timeline.' + words, 'reason': ''},
                             {'key': keys[1], 'status': 'Failed', 'message_id': '', 'reason': 'Meta error 131026: Message undeliverable'},
                             {'key': keys[2], 'status': 'Cancelled', 'message_id': '', 'reason': ''}])
        bulk_timeline.apply([{'key': keys[0], 'status': 'Failed', 'message_id': '', 'reason': 'Late failure'}])
        frappe.db.commit()
    states = {row.source_key: row for row in frappe.get_all('Relay Message', filters={'source_key': ['in', keys[:3]]},
              fields=['source_key', 'status', 'provider_id', 'provider_message_key', 'delivery_error'])}
    assert (states[keys[0]].status, states[keys[0]].provider_id, states[keys[0]].delivery_error) == \
        ('Read', 'wamid.timeline.' + words, ''), states[keys[0]]
    assert states[keys[0]].provider_message_key == provider_key(channel.name, numbers[0], 'wamid.timeline.' + words)
    assert (states[keys[1]].status, states[keys[1]].delivery_error) == ('Failed', 'Meta error 131026: Message undeliverable')
    assert (states[keys[2]].status, states[keys[2]].delivery_error) == ('Failed', 'Cancelled before sending')

    reply = insert({'doctype': 'Relay Message', 'relay_contact': people[0].name, 'channel': channel.name,
                    'direction': 'Incoming', 'status': 'Sent', 'content': 'Yes please', 'sender_endpoint': numbers[0],
                    'provider_id': 'wamid.reply.' + words, 'message_type': 'text',
                    'provider_context': json.dumps({'provider': 'WhatsApp', 'reply_to_message_id': 'wamid.timeline.' + words})})
    frappe.db.commit()
    quoted = api.quoted_message(reply.name)['message']
    assert quoted == stored[0].name, quoted
    print(f'PASS campaign timeline: 50-row batch wrote 40 rendered messages for Relay Contacts in {elapsed * 1000:.0f} ms '
          'with one realtime event, a repeat inserted nothing, updates moved status forward only, '
          'and a reply quotes the rendered template')
finally:
    frappe.db.rollback()
    frappe.flags.relay_contact_sync = True
    for name in frappe.get_all('Relay Message', filters={'source_key': ['like', f'bulk-timeline-{words}-%']}, pluck='name'):
        frappe.delete_doc('Relay Message', name, ignore_permissions=True, force=True)
    for doc in reversed(created):
        frappe.delete_doc(doc.doctype, doc.name, ignore_permissions=True, force=True)
    frappe.db.commit()
    frappe.destroy()
