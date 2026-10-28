"""Local yrp.site HTTP acceptance of internal notes on a business chat for users who cannot read the business.

Run from the app folder: ../../env/bin/python -B -m unittest discover -s tests -p 'integration_note_access_http.py'
Fixtures are clearly named, reusable local records. API credentials are ephemeral.
"""
import json
import os
import secrets
import sys
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from wsgiref.simple_server import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[1]
SITES = '/home/sakthi/development/pilot/benches/version_16/sites'
os.environ['SITES_PATH'] = SITES
sys.path.insert(0, str(ROOT))
import frappe
import frappe.app
import requests


def connect():
    frappe.init(site='yrp.site', sites_path=SITES)
    frappe.connect()
    frappe.set_user('Administrator')
    frappe.flags.mute_emails = True
    frappe.conf.relay_automation_enabled = 0


def fixture(doctype, filters, values):
    name = frappe.db.get_value(doctype, filters, 'name')
    return frappe.get_doc(doctype, name) if name else frappe.get_doc(dict(doctype=doctype, **values)).insert()


def api_user(email, role):
    user = fixture('User', {'email': email}, {'email': email, 'first_name': 'Local note verifier',
        'send_welcome_email': 0, 'roles': [{'role': role}]})
    user.api_key, user.api_secret, user.enabled = secrets.token_hex(12), secrets.token_hex(24), 1
    user.save()
    return user.name, (user.api_key, user.get_password('api_secret'))


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


class NoteAccessHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        for name in ('enqueue', 'publish_realtime', 'sendmail'):
            cls.stack.enter_context(patch.object(frappe, name))
        connect()
        cls.reader, cls.reader_key = api_user('relay-note-reader@example.invalid', 'Relay Communication Team User')
        cls.outsider, cls.outsider_key = api_user('relay-note-outsider@example.invalid', 'Relay Communication User')
        customer = fixture('Customer', {'customer_name': 'Local note access customer'}, {'customer_name': 'Local note access customer',
            'customer_type': 'Company', 'gst_category': 'Unregistered'})
        person = fixture('Contact', {'first_name': 'Local note access Ravi'}, {'first_name': 'Local note access Ravi',
            'links': [{'link_doctype': 'Customer', 'link_name': customer.name}]})
        contact = fixture('Relay Contact', {'contact': person.name}, {'contact': person.name, 'display_name': 'Local note access Ravi'})
        channel = fixture('Relay Channel', {'title': 'Local note access line'}, {'title': 'Local note access line', 'channel': 'Email',
            'account': 'local-note-access', 'enabled': 0, 'mailbox_address': 'note-access@example.invalid'})
        fixture('Relay Message', {'relay_contact': contact.name, 'content': 'Local note access hello'}, {
            'relay_contact': contact.name, 'channel': channel.name, 'direction': 'Incoming', 'content': 'Local note access hello',
            'sender_endpoint': 'ravi-note@example.invalid', 'message_type': 'text',
            'message_data': json.dumps({'kind': 'text', 'text': 'Local note access hello'})})
        frappe.db.commit()
        frappe.set_user(cls.reader)
        assert not frappe.has_permission('Customer', 'read'), 'The reader must not read Customer for this test'
        frappe.set_user('Administrator')
        cls.contact, cls.customer = contact.name, customer.name
        frappe.destroy()

        def application(environ, start_response):
            environ['HTTP_X_FRAPPE_SITE_NAME'] = 'yrp.site'
            return frappe.app.application(environ, start_response)
        cls.server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}/api/method/relay_core.collaboration.'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)
        connect()
        for name in (cls.reader, cls.outsider):
            user = frappe.get_doc('User', name)
            user.api_key = user.api_secret = None
            user.enabled = 0
            user.save()
        frappe.db.commit(); frappe.destroy()
        cls.stack.close()

    def call(self, method, key, **values):
        headers = {'Authorization': 'token %s:%s' % key}
        if method == 'comments':
            return requests.get(self.base + method, params=values, headers=headers, timeout=20)
        return requests.post(self.base + method, json=values, headers=headers, timeout=20)

    def test_chat_reader_without_business_read_adds_and_lists_a_note(self):
        response = self.call('add', self.reader_key, contact=self.contact, body='Call back tomorrow', request_key=secrets.token_hex(12))
        self.assertEqual(response.status_code, 200, response.text[:400])
        note = response.json()['message']
        self.assertEqual((note['body'], note['author'], note['can_edit']), ('Call back tomorrow', self.reader, True))
        self.assertEqual(set(note), {'name', 'body', 'deleted', 'author', 'author_name', 'creation', 'modified', 'messages',
                                     'reply_to', 'can_edit', 'assigned_to', 'task_status', 'can_complete', 'mentions'})
        listed = self.call('comments', self.reader_key, contact=self.contact)
        self.assertEqual(listed.status_code, 200, listed.text[:400])
        self.assertIn(note['name'], [row['name'] for row in listed.json()['message']['items']])
        self.assertEqual(frappe_value(note['name']), ('Customer', self.customer), 'The note keeps its business')

    def test_user_who_cannot_open_the_chat_is_denied(self):
        response = self.call('add', self.outsider_key, contact=self.contact, body='Not mine', request_key=secrets.token_hex(12))
        self.assertEqual(response.status_code, 403, response.text[:400])
        self.assertEqual(self.call('comments', self.outsider_key, contact=self.contact).status_code, 403)


def frappe_value(name):
    connect()
    try:
        return tuple(frappe.db.get_value('Relay Internal Comment', name, ['business_doctype', 'business_name']))
    finally:
        frappe.destroy()


if __name__ == '__main__':
    unittest.main()
