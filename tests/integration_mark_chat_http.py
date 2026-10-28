"""Local yrp.site HTTP acceptance of message_reads.mark_chat; only worktree code, no external delivery.

Run from the app folder: ../../env/bin/python -B -m unittest discover -s tests -p 'integration_mark_chat_http.py'
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


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


class MarkChatHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        for name in ('enqueue', 'publish_realtime', 'sendmail'):
            cls.stack.enter_context(patch.object(frappe, name))
        connect()
        user = fixture('User', {'email': 'relay-mark-chat@example.invalid'}, {'email': 'relay-mark-chat@example.invalid',
            'first_name': 'Local mark chat verifier', 'send_welcome_email': 0, 'roles': [{'role': 'System Manager'}]})
        cls.api_key, cls.api_secret = secrets.token_hex(12), secrets.token_hex(24)
        user.api_key, user.api_secret, user.enabled = cls.api_key, cls.api_secret, 1
        user.save()
        person = fixture('Contact', {'first_name': 'Local mark chat Ravi'}, {'first_name': 'Local mark chat Ravi'})
        contact = fixture('Relay Contact', {'contact': person.name}, {'contact': person.name, 'display_name': 'Local mark chat Ravi'})
        channel = fixture('Relay Channel', {'title': 'Local mark chat line'}, {'title': 'Local mark chat line', 'channel': 'Email',
            'account': 'local-mark-chat', 'enabled': 0, 'mailbox_address': 'mark-chat@example.invalid'})
        fixture('Relay Message', {'relay_contact': contact.name, 'content': 'Local mark chat hello'}, {
            'relay_contact': contact.name, 'channel': channel.name, 'direction': 'Incoming', 'content': 'Local mark chat hello',
            'sender_endpoint': 'ravi@example.invalid', 'message_type': 'text',
            'message_data': json.dumps({'kind': 'text', 'text': 'Local mark chat hello'})})
        frappe.db.commit()
        cls.user, cls.contact = user.name, contact.name
        frappe.destroy()

        def application(environ, start_response):
            environ['HTTP_X_FRAPPE_SITE_NAME'] = 'yrp.site'
            return frappe.app.application(environ, start_response)
        cls.server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/api/method/relay_core.message_reads.mark_chat'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)
        connect()
        user = frappe.get_doc('User', cls.user)
        user.api_key = user.api_secret = None
        user.enabled = 0
        user.save()
        frappe.db.commit(); frappe.destroy()
        cls.stack.close()

    def post(self, read, auth=True):
        headers = {'Authorization': f'token {self.api_key}:{self.api_secret}'} if auth else {}
        return requests.post(self.url, json={'contact': self.contact, 'read': read}, headers=headers, timeout=20)

    def test_read_unread_round_trip(self):
        response = self.post(1)
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertEqual(response.json()['message'], {'contact': self.contact, 'unread': 0})
        response = self.post(0)
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertEqual(response.json()['message'], {'contact': self.contact, 'unread': 1})
        self.assertEqual(self.post(1).json()['message']['unread'], 0)

    def test_guest_and_bad_flag_are_denied(self):
        self.assertIn(self.post(1, auth=False).status_code, (401, 403))
        self.assertEqual(self.post(5).status_code, 417)


def api_user(email, role):
    user = fixture('User', {'email': email}, {'email': email, 'first_name': 'Local mark chat verifier',
        'send_welcome_email': 0, 'roles': [{'role': role}]})
    user.api_key, user.api_secret, user.enabled = secrets.token_hex(12), secrets.token_hex(24), 1
    user.save()
    return user.name, (user.api_key, user.get_password('api_secret'))


class MarkBusinessRowHttpTests(unittest.TestCase):
    """A business row stands for every chat linked to its record."""
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        for name in ('enqueue', 'publish_realtime', 'sendmail'):
            cls.stack.enter_context(patch.object(frappe, name))
        connect()
        cls.reader, cls.reader_key = api_user('relay-mark-business@example.invalid', 'System Manager')
        cls.outsider, cls.outsider_key = api_user('relay-mark-outsider@example.invalid', 'Relay Communication Team User')
        customer = fixture('Customer', {'customer_name': 'Local mark business customer'}, {'customer_name': 'Local mark business customer',
            'customer_type': 'Company', 'gst_category': 'Unregistered'})
        channel = fixture('Relay Channel', {'title': 'Local mark chat line'}, {'title': 'Local mark chat line', 'channel': 'Email',
            'account': 'local-mark-chat', 'enabled': 0, 'mailbox_address': 'mark-chat@example.invalid'})
        cls.contacts = []
        for index in (1, 2):
            label = 'Local mark business chat %d' % index
            person = fixture('Contact', {'first_name': label}, {'first_name': label,
                'links': [{'link_doctype': 'Customer', 'link_name': customer.name}]})
            contact = fixture('Relay Contact', {'contact': person.name}, {'contact': person.name, 'display_name': label})
            fixture('Relay Message', {'relay_contact': contact.name, 'content': label + ' hello'}, {
                'relay_contact': contact.name, 'channel': channel.name, 'direction': 'Incoming', 'content': label + ' hello',
                'sender_endpoint': 'business-%d@example.invalid' % index, 'message_type': 'text',
                'message_data': json.dumps({'kind': 'text', 'text': label + ' hello'})})
            cls.contacts.append(contact.name)
        frappe.db.commit()
        cls.customer = customer.name
        frappe.destroy()

        def application(environ, start_response):
            environ['HTTP_X_FRAPPE_SITE_NAME'] = 'yrp.site'
            return frappe.app.application(environ, start_response)
        cls.server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/api/method/relay_core.message_reads.mark_chat'

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

    def post(self, key, read):
        return requests.post(self.url, json={'business_doctype': 'Customer', 'business_name': self.customer, 'read': read},
                             headers={'Authorization': 'token %s:%s' % key}, timeout=20)

    def unread(self):
        connect()
        try:
            frappe.set_user(self.reader)
            from relay_core.inbox import unread_count
            return [unread_count(name) for name in self.contacts]
        finally:
            frappe.destroy()

    def test_business_row_read_and_unread_cover_every_chat(self):
        response = self.post(self.reader_key, 1)
        self.assertEqual(response.status_code, 200, response.text[:400])
        result = response.json()['message']
        self.assertEqual(result['business'], {'doctype': 'Customer', 'name': self.customer})
        self.assertEqual(set(self.contacts) - set(result['contacts']), set())
        self.assertEqual(result['unread'], 0)
        self.assertEqual(self.unread(), [0, 0])
        response = self.post(self.reader_key, 0)
        self.assertEqual(response.status_code, 200, response.text[:400])
        self.assertGreaterEqual(response.json()['message']['unread'], 1, 'The record row is unread for the whole team')
        self.assertEqual(self.unread(), [1, 1])

    def test_user_who_cannot_read_the_business_is_denied(self):
        self.assertEqual(self.post(self.outsider_key, 1).status_code, 403)
        both = requests.post(self.url, json={'contact': self.contacts[0], 'business_doctype': 'Customer',
            'business_name': self.customer, 'read': 1}, headers={'Authorization': 'token %s:%s' % self.reader_key}, timeout=20)
        self.assertEqual(both.status_code, 417, 'A request names one chat or one business row')


if __name__ == '__main__':
    unittest.main()
