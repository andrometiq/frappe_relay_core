"""Local relay.test HTTP acceptance of conversation_threads.threads, the thread filter of business_inbox.messages and the
channel marks of inbox.directory; only worktree code, no external delivery.

Run from the app folder: ../../env/bin/python -B -m unittest discover -s tests -p 'integration_conversation_threads_http.py'
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
SITES = os.environ['SITES_PATH']
sys.path.insert(0, str(ROOT))
import frappe
import frappe.app
import requests

CUSTOMER = 'Local threads customer'
# (channel index, endpoint, direction, text): two endpoints on our first mailbox, and the first endpoint again on the second.
MESSAGES = [(0, 'ravi@example.invalid', 'Incoming', 'Local threads first mailbox hello'),
            (0, 'ravi.home@example.invalid', 'Incoming', 'Local threads home address hello'),
            (1, 'ravi@example.invalid', 'Outgoing', 'Local threads second mailbox reply'),
            (1, 'ravi@example.invalid', 'Incoming', 'Local threads second mailbox answer')]


def connect():
    frappe.init(site='relay.test', sites_path=SITES)
    frappe.connect()
    frappe.set_user('Administrator')
    frappe.flags.mute_emails = True
    frappe.conf.relay_automation_enabled = 0


def fixture(doctype, filters, values):
    name = frappe.db.get_value(doctype, filters, 'name')
    return frappe.get_doc(doctype, name) if name else frappe.get_doc(dict(doctype=doctype, **values)).insert()


def api_user(email, role):
    user = fixture('User', {'email': email}, {'email': email, 'first_name': 'Local threads verifier', 'send_welcome_email': 0,
                                              'roles': [{'role': role}]})
    user.api_key, user.api_secret, user.enabled = secrets.token_hex(12), secrets.token_hex(24), 1
    user.save()
    return user.name, (user.api_key, user.get_password('api_secret'))


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


class ConversationThreadHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        for name in ('enqueue', 'publish_realtime', 'sendmail'):
            cls.stack.enter_context(patch.object(frappe, name))
        connect()
        cls.reader, cls.reader_key = api_user('relay-threads-reader@example.invalid', 'System Manager')
        cls.outsider, cls.outsider_key = api_user('relay-threads-outsider@example.invalid', 'Relay Communication Team User')
        customer = fixture('Customer', {'customer_name': CUSTOMER}, {'customer_name': CUSTOMER, 'customer_type': 'Company',
                                                                     'gst_category': 'Unregistered'})
        person = fixture('Contact', {'first_name': 'Local threads Ravi'}, {'first_name': 'Local threads Ravi',
            'links': [{'link_doctype': 'Customer', 'link_name': customer.name}]})
        contact = fixture('Relay Contact', {'contact': person.name}, {'contact': person.name, 'display_name': 'Local threads Ravi'})
        channels = [fixture('Relay Channel', {'title': title}, {'title': title, 'channel': 'Email', 'account': 'local-threads',
                                                                 'enabled': 0, 'mailbox_address': address})
                    for title, address in (('Local threads mailbox A', 'threads-a@example.invalid'),
                                           ('Local threads mailbox B', 'threads-b@example.invalid'))]
        names = []
        for index, endpoint, direction, text in MESSAGES:
            fixture('Relay Contact Endpoint', {'relay_contact': contact.name, 'channel': channels[index].name, 'endpoint': endpoint},
                    {'relay_contact': contact.name, 'channel': channels[index].name, 'endpoint': endpoint, 'verified': 1})
            names.append(fixture('Relay Message', {'relay_contact': contact.name, 'content': text}, {
                'relay_contact': contact.name, 'channel': channels[index].name, 'direction': direction, 'content': text,
                'sender_endpoint': endpoint, 'message_type': 'text', 'business_doctype': 'Customer', 'business_name': customer.name,
                'message_data': json.dumps({'kind': 'text', 'text': text})}).name)
        # Every run starts with no reads and the three incoming messages unread.
        frappe.db.delete('Relay Message Read', {'message': ['in', names]})
        frappe.db.set_value('Relay Chat', {'business_doctype': 'Customer', 'business_name': customer.name},
                            {'unread_count': 3, 'is_unread': 1}, update_modified=False)
        frappe.db.commit()
        cls.customer, cls.contact, cls.names = customer.name, contact.name, names
        cls.channels = [channel.name for channel in channels]
        frappe.destroy()

        def application(environ, start_response):
            environ['HTTP_X_FRAPPE_SITE_NAME'] = 'relay.test'
            return frappe.app.application(environ, start_response)
        cls.server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}/api/method/relay_core.'

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

    def get(self, method, params, key=None):
        headers = {'Authorization': 'token %s:%s' % (key or self.reader_key)} if key is not False else {}
        return requests.get(self.base + method, params=params, headers=headers, timeout=30)

    def threads(self, **params):
        response = self.get('conversation_threads.threads', params)
        self.assertEqual(response.status_code, 200, response.text[:400])
        return response.json()['message']['items']

    def test_01_each_endpoint_on_each_channel_is_its_own_thread(self):
        for items in (self.threads(doctype='Customer', name=self.customer), self.threads(contact=self.contact)):
            self.assertEqual([(item['channel'], item['endpoint'], item['unread']) for item in items], [
                (self.channels[0], 'ravi.home@example.invalid', 1), (self.channels[0], 'ravi@example.invalid', 1),
                (self.channels[1], 'ravi@example.invalid', 1)])
            item = items[2]
            self.assertEqual(set(item), {'key', 'relay_contact', 'contact_label', 'frappe_contact', 'channel', 'provider', 'channel_label',
                                         'channel_address', 'endpoint', 'last_message', 'last_at', 'last_direction', 'preview', 'unread', 'handle',
                                         'first_unread'})
            self.assertEqual((item['key'], item['provider'], item['last_message'], item['first_unread'], item['last_direction']),
                             ('|'.join((self.contact, self.channels[1], 'ravi@example.invalid')), 'Email', self.names[3], self.names[3], 'Incoming'))

    def test_02_the_timeline_filter_keeps_one_thread(self):
        response = self.get('business_inbox.messages', {'doctype': 'Customer', 'name': self.customer, 'channel': self.channels[1],
                                                        'sender_endpoint': 'ravi@example.invalid'})
        self.assertEqual(response.status_code, 200, response.text[:400])
        self.assertEqual([row['name'] for row in response.json()['message']['items']], self.names[2:])
        bad = self.get('business_inbox.messages', {'doctype': 'Customer', 'name': self.customer, 'sender_endpoint': 'x' * 201})
        self.assertEqual(bad.status_code, 417)

    def test_03_the_list_row_marks_its_channels_and_the_unread_ones(self):
        response = self.get('inbox.directory', {'rows': 'business', 'query': CUSTOMER})
        self.assertEqual(response.status_code, 200, response.text[:400])
        row = next(item for item in response.json()['message']['items'] if item.get('record') == self.customer)
        self.assertEqual(sorted((mark['channel'], mark['endpoint'], mark['unread']) for mark in row['threads']), [
            (self.channels[0], 'ravi.home@example.invalid', True), (self.channels[0], 'ravi@example.invalid', True),
            (self.channels[1], 'ravi@example.invalid', True)])
        self.assertEqual((row['last_direction'], row['open_tickets']), ('Incoming', 0))

    def test_04_reading_one_thread_keeps_the_others_unread(self):
        response = requests.post(self.base + 'business_inbox.mark_visible', json={'doctype': 'Customer', 'name': self.customer,
            'messages': json.dumps([self.names[0]]), 'last_read': self.names[0]},
            headers={'Authorization': 'token %s:%s' % self.reader_key}, timeout=30)
        self.assertEqual(response.status_code, 200, response.text[:400])
        items = self.threads(doctype='Customer', name=self.customer)
        self.assertEqual([item['unread'] for item in items], [1, 0, 1])
        row = next(item for item in self.get('inbox.directory', {'rows': 'business', 'query': CUSTOMER}).json()['message']['items']
                   if item.get('record') == self.customer)
        self.assertEqual(row['unread'], 2, 'The list count matches the threads')

    def test_05_a_user_who_cannot_read_the_record_or_chat_is_denied(self):
        self.assertEqual(self.get('conversation_threads.threads', {'doctype': 'Customer', 'name': self.customer}, self.outsider_key).status_code, 403)
        self.assertEqual(self.get('conversation_threads.threads', {'contact': self.contact}, self.outsider_key).status_code, 403)
        self.assertIn(self.get('conversation_threads.threads', {'contact': self.contact}, False).status_code, (401, 403))
        both = self.get('conversation_threads.threads', {'contact': self.contact, 'doctype': 'Customer', 'name': self.customer})
        self.assertEqual(both.status_code, 417, 'A request names one chat or one business record')


if __name__ == '__main__':
    unittest.main()
