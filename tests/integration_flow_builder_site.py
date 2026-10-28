"""Imported WhatsApp Core /help flow end to end on a site without a Hub; every send is captured, none leaves.

Jobs run inline: the drain wake is patched, so the bench workers never pick up these messages.

Usage (from the bench sites folder):
  RELAY_FLOW_TEST_SITE=relay-flows-test.localhost RELAY_FLOW_SOURCE_DB=relay_src_ops_flows \\
  RELAY_SOURCE_DB_PASSWORD=... ../env/bin/python ../apps/relay_core/tests/integration_flow_builder_site.py
"""
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import frappe
from frappe.permissions import add_permission
from site_labels import phone, run_label
import flow_fake_actions

SITE = os.environ.get('RELAY_FLOW_TEST_SITE', 'relay-flows-test.localhost')
frappe.init(site=SITE, sites_path='.')
frappe.connect()
assert not frappe.db.get_single_value('Relay Settings', 'hub_url'), 'Run only on a site without a Relay Hub'
frappe.set_user('Administrator')
frappe.flags.mute_emails = True

from relay_core import legacy_database, messaging
from relay_core.automation import queue
from relay_core.flows import actions, service as flows
from relay_core.flows.legacy_import import FlowImporter

RUN = run_label()
MANAGER = 'Relay Communication Manager'


def fixtures():
    runner = 'flow-runner@example.invalid'
    if not frappe.db.exists('User', runner):
        frappe.get_doc({'doctype': 'User', 'email': runner, 'first_name': 'Flow runner', 'send_welcome_email': 0,
                        'roles': [{'role': MANAGER}]}).insert()
    add_permission('Note', MANAGER, 0)
    add_permission('Company', MANAGER, 0)
    company = frappe.get_all('Company', pluck='name', limit=1)
    assert company, 'Run on a site with ERPNext and a Company: automated chats open a ticket in the channel company'
    if not frappe.db.exists('Relay Contact Type', {'business_doctype': 'Note'}):
        frappe.get_doc({'doctype': 'Relay Contact Type', 'business_doctype': 'Note', 'enabled': 1, 'label': 'Note'}).insert()
    note = frappe.get_doc({'doctype': 'Note', 'title': 'Flow business ' + RUN, 'public': 1}).insert()
    # Automated conversations open an episode ticket; the channel's triage owner receives it.
    channel = frappe.get_doc({'doctype': 'Relay Channel', 'channel': 'WhatsApp', 'account': 'flow-' + RUN, 'enabled': 1,
                              'triage_owner': runner, 'company': company[0]}).insert()
    frappe.db.commit()
    return runner, note, channel


def person(note, channel, label):
    contact = frappe.get_doc({'doctype': 'Contact', 'first_name': label, 'links': [{'link_doctype': 'Note', 'link_name': note.name}]}).insert()
    relay = frappe.get_doc({'doctype': 'Relay Contact', 'contact': contact.name, 'display_name': label}).insert()
    number = phone(RUN + label)
    frappe.get_doc({'doctype': 'Relay Contact Endpoint', 'channel': channel.name, 'relay_contact': relay.name,
                    'endpoint': number, 'verified': 1}).insert()
    return relay.name, number


class Conversation:
    """Inbound messages through the real admission drain; flow jobs run inline and in order."""

    def __init__(self, channel, contact, number):
        self.channel, self.contact, self.number = channel, contact, number

    def say(self, text, kind='text'):
        context = {'provider': 'WhatsApp', 'message_id': 'wamid.' + str(time.time_ns())}
        data = {'kind': 'text', 'text': text} if kind == 'text' else {'kind': kind, 'media': {'id': 'media-' + RUN}}
        message = frappe.get_doc({'doctype': 'Relay Message', 'relay_contact': self.contact, 'channel': self.channel.name,
            'direction': 'Incoming', 'content': text, 'message_type': kind, 'status': 'Sent', 'sender_endpoint': self.number,
            'provider_context': json.dumps(context), 'message_data': json.dumps(data)}).insert(ignore_permissions=True)
        frappe.db.commit()
        run_jobs()
        return message


JOBS = []


def capture(method, **kwargs):
    if method == 'relay_core.flows.service.process':
        JOBS.append(kwargs['name'])


def run_jobs():
    queue.drain()
    while JOBS:
        flows.process(JOBS.pop(0))


SENT = []


def fake_send(run, event, source, channel, text, key):
    SENT.append((source.relay_contact, text, key))


REAL_GET_ATTR = frappe.get_attr


def get_attr(method):
    # frappe.get_attr only loads installed apps; the fake actions live in this test folder.
    if method.startswith('flow_fake_actions.'):
        return getattr(flow_fake_actions, method.split('.', 1)[1])
    return REAL_GET_ATTR(method)


def texts(contact):
    return [text for owner, text, _ in SENT if owner == contact]


def main():
    runner, note, channel = fixtures()
    password = os.environ.get('RELAY_SOURCE_DB_PASSWORD')
    source = legacy_database.Source(os.environ.get('RELAY_FLOW_SOURCE_DB', 'relay_src_ops_flows'), password=password)
    try:
        importer = lambda dry=False: FlowImporter(source, 'flowtest-' + RUN, channel.name, runner, 'Note', dry).run()
        preview = importer(True)
        assert not preview['failures'] and len(preview['flows']) == 1 and frappe.db.count('Relay Flow', {'legacy_key': ['like', 'flowtest-' + RUN + '%']}) == 0, preview
        first = importer()
        flow = first['flows'][0]
        assert not first['failures'] and flow['versions_added'] == 4 and flow['command'] == '/help', first
        assert flow['missing_actions'] == sorted('custom_andrometiq.support.' + key for key in
            ('append_ticket_content', 'create_ticket', 'finalize_ticket', 'lookup_ticket', 'resolve_customer')), flow
        again = importer()
        assert again['flows'][0]['status'] == 'exists' and again['flows'][0]['versions_added'] == 0, again
        print('PASS import: dry run writes nothing; 1 flow with 4 versions; re-run adds nothing; unregistered actions listed')
    finally:
        source.close()

    name = flow['relay_flow']
    doc = frappe.get_doc('Relay Flow', name)
    assert not doc.enabled and doc.published_version and frappe.db.count('Relay Flow Version', {'flow': name}) == 4
    frappe.db.set_single_value('Relay Settings', 'enable_flows', 0)
    frappe.db.commit()
    with patch.object(actions, 'definitions', flow_fake_actions.definitions), patch.object(frappe, 'enqueue', side_effect=capture), \
         patch.object(flows, 'send', side_effect=fake_send), patch.object(frappe, 'get_attr', side_effect=get_attr), \
         patch.object(queue.AUTOMATION, 'wake', return_value=None), patch.object(messaging, 'connection_value', return_value=channel.account):
        try:
            flows.set_enabled(name, 1)
            raise AssertionError('Flows must be switched on first')
        except frappe.PermissionError:
            pass
        frappe.db.set_single_value('Relay Settings', 'enable_flows', 1)
        flows.set_enabled(name, 1)
        frappe.db.commit()

        contact, number = person(note, channel, 'Asha ' + RUN)
        frappe.db.commit()
        chat = Conversation(channel, contact, number)
        chat.say('/help')
        assert texts(contact)[-1] == 'Hi Asha! How can we help you today?\n1. Create Ticket\n2. View Ticket\n3. Edit Ticket', texts(contact)
        chat.say('1')
        assert texts(contact)[-1].startswith('Type a short title'), texts(contact)
        chat.say('x')
        assert texts(contact)[-1].startswith('Please send the ticket title as a text message only'), texts(contact)
        chat.say('', kind='image')
        assert texts(contact)[-1].startswith('Please send the ticket title as a text message only'), texts(contact)
        chat.say('Printer is offline')
        assert texts(contact)[-2:] == ['Ticket #0043 created.', 'Send one update: text, voice note, image, video, document, sticker, location, or contact. You can add more after this.'], texts(contact)
        chat.say('', kind='image')
        assert texts(contact)[-1].startswith('Your update is saved.'), texts(contact)
        chat.say('Add Attachment')
        chat.say('It shows error 41')
        chat.say('Finalise Ticket')
        assert texts(contact)[-1] == 'Ticket #0043 is saved.\n\nType /help to start again.', texts(contact)
        run = frappe.get_all('Relay Flow Run', filters={'relay_contact': contact}, fields=['name', 'status', 'values'])[0]
        values = json.loads(run['values'])
        assert run['status'] == 'Completed' and values['_visits']['content_choice'] == 2 and values['title'] == 'Printer is offline', run
        kinds = [call[1]['content']['type'] for call in flow_fake_actions.CALLS if call[0] == 'append_ticket_content']
        assert kinds == ['image', 'text'], flow_fake_actions.CALLS
        keys = [call[2] for call in flow_fake_actions.CALLS if call[0] == 'append_ticket_content']
        assert len(set(keys)) == 2, 'each loop visit gets its own action key'
        print('PASS /help: numbered choice, text-only title with its own error, media and text updates in a loop, final message')

        chat.say('/help')
        chat.say('cancel')
        assert texts(contact)[-1] == 'The current flow has been closed.'
        assert frappe.db.get_value('Relay Flow Run', {'relay_contact': contact, 'status': 'Cancelled'}, 'reason') == 'Closed by the customer'
        print('PASS exit word closes the open run')

        doc = frappe.get_doc('Relay Flow', name)
        flows.save({'keywords': 'Need help\nsupport'}, name)
        frappe.db.commit()
        other, other_number = person(note, channel, 'Ravi ' + RUN)
        frappe.db.commit()
        Conversation(channel, other, other_number).say('  need   HELP ')
        assert texts(other)[-1].startswith('Hi Asha!'), texts(other)
        print('PASS keyword trigger starts the flow (case and spacing ignored)')

        frappe.db.set_single_value('Relay Settings', 'enable_flows', 0)
        frappe.db.commit()
        count = len(SENT)
        Conversation(channel, other, other_number).say('2')
        assert len(SENT) == count, 'switched off flows send nothing'
        frappe.db.set_single_value('Relay Settings', 'enable_flows', 1)
        frappe.db.commit()
        print('PASS Enable flows off stops claiming messages')
        flows.set_enabled(name, 0)
        frappe.db.commit()
    print('ALL PASS', RUN)


if __name__ == '__main__':
    main()
