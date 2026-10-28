"""Local yrp.site HTTP acceptance of contacts.set_links: a Relay manager edits business links of a linked contact.

Run from the app folder: ../../env/bin/python -B -m unittest discover -s tests -p 'integration_contact_links_http.py'
Fixtures are clearly named, reusable local records. API credentials are ephemeral.
"""
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
    user = fixture('User', {'email': email}, {'email': email, 'first_name': 'Local link verifier',
        'send_welcome_email': 0, 'roles': [{'role': role}]})
    user.api_key, user.api_secret, user.enabled = secrets.token_hex(12), secrets.token_hex(24), 1
    user.save()
    return user.name, (user.api_key, user.get_password('api_secret'))


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


class ContactLinksHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        for name in ('enqueue', 'publish_realtime', 'sendmail'):
            cls.stack.enter_context(patch.object(frappe, name))
        connect()
        cls.manager, cls.manager_key = api_user('relay-link-manager@example.invalid', 'Relay Communication Manager')
        cls.staff, cls.staff_key = api_user('relay-link-staff@example.invalid', 'Relay Communication Team User')
        supplier = fixture('Supplier', {'supplier_name': 'Local link access supplier'}, {'supplier_name': 'Local link access supplier',
            'supplier_type': 'Company', 'gst_category': 'Unregistered'})
        person = fixture('Contact', {'first_name': 'Local link access Ravi'}, {'first_name': 'Local link access Ravi'})
        fixture('Relay Contact', {'contact': person.name}, {'contact': person.name, 'display_name': 'Local link access Ravi'})
        frappe.db.commit()
        for user in (cls.manager, cls.staff):
            frappe.set_user(user)
            assert not frappe.has_permission('Contact', 'write', doc=person), 'Verifiers must not write the Contact'
            assert frappe.has_permission('Supplier', 'read'), 'Verifiers must read the Supplier'
        frappe.set_user('Administrator')
        cls.person, cls.supplier = person.name, supplier.name
        frappe.destroy()

        def application(environ, start_response):
            environ['HTTP_X_FRAPPE_SITE_NAME'] = 'yrp.site'
            return frappe.app.application(environ, start_response)
        cls.server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/api/method/relay_core.contacts.set_links'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)
        connect()
        for name in (cls.manager, cls.staff):
            user = frappe.get_doc('User', name)
            user.api_key = user.api_secret = None
            user.enabled = 0
            user.save()
        frappe.db.commit(); frappe.destroy()
        cls.stack.close()

    def setUp(self):
        connect()
        person = frappe.get_doc('Contact', self.person)
        person.set('links', [{'link_doctype': 'Supplier', 'link_name': self.supplier}])
        person.save()
        frappe.db.commit(); frappe.destroy()

    def post(self, key, links):
        return requests.post(self.url, json={'contact': self.person, 'links': links},
                             headers={'Authorization': 'token %s:%s' % key}, timeout=20)

    def test_manager_removes_and_adds_a_link_on_a_linked_contact(self):
        response = self.post(self.manager_key, [])
        self.assertEqual(response.status_code, 200, response.text[:400])
        self.assertEqual(response.json()['message']['links'], [])
        self.assertEqual(set(response.json()['message']), {'contact', 'relay_contact', 'links', 'primary'})
        response = self.post(self.manager_key, [{'doctype': 'Supplier', 'name': self.supplier}])
        self.assertEqual(response.status_code, 200, response.text[:400])
        self.assertEqual(response.json()['message']['links'], [{'doctype': 'Supplier', 'name': self.supplier}])

    def test_non_manager_without_contact_write_is_denied(self):
        response = self.post(self.staff_key, [])
        self.assertEqual(response.status_code, 403, response.text[:400])
        connect()
        try:
            self.assertEqual(len(frappe.get_doc('Contact', self.person).links), 1, 'A denied request keeps the link')
        finally:
            frappe.destroy()


if __name__ == '__main__':
    unittest.main()
