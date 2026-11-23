"""Local relay.test HTTP acceptance of the ticket list: contact and update time per row, hidden contacts and guests.

Run from the app folder: SITES_PATH=../../sites ../../env/bin/python -B -m unittest discover -s tests -p 'integration_ticket_list_http.py'
Needs one ticket on relay.test whose first message has a contact. Fixture users are reusable; API credentials are ephemeral.
"""
import os
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
sys.path.insert(0, str(ROOT / 'tests'))
import frappe
import frappe.app
import requests
from integration_access_http import connect, remove_from_types, user_with_key


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


class TicketListHttpTests(unittest.TestCase):
    MANAGER, OUTSIDER = 'relay-ticket-list-manager@example.invalid', 'relay-ticket-list-outsider@example.invalid'

    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        for name in ('enqueue', 'sendmail'):
            cls.stack.enter_context(patch.object(frappe, name))
        connect()
        cls.manager = user_with_key(cls.MANAGER, 'Local ticket list manager', ['Relay Communication Manager'])
        cls.outsider = user_with_key(cls.OUTSIDER, 'Local ticket list outsider', ['Relay Communication User'])
        remove_from_types(cls.OUTSIDER)
        link = frappe.get_all('Relay Ticket Message', filters={'parenttype': 'Relay Ticket', 'idx': 1}, fields=['parent', 'message'], limit=1)
        if not link:
            raise unittest.SkipTest('relay.test has no ticket with a linked message')
        cls.ticket = link[0].parent
        contact = frappe.db.get_value('Relay Message', link[0].message, 'relay_contact')
        cls.contact_title = frappe.db.get_value('Relay Contact', contact, 'display_name')
        frappe.db.commit()
        frappe.destroy()

        def application(environ, start_response):
            environ['HTTP_X_FRAPPE_SITE_NAME'] = 'relay.test'
            return frappe.app.application(environ, start_response)
        cls.server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/api/method/relay_core.tickets.directory'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)
        connect()
        for email in (cls.MANAGER, cls.OUTSIDER):
            user = frappe.get_doc('User', email)
            user.api_key = user.api_secret = None
            user.enabled = 0
            user.save()
        frappe.db.commit(); frappe.destroy()
        cls.stack.close()

    def rows(self, headers):
        response = requests.get(self.url, params={'query': ''}, headers=headers, timeout=30)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()['message']
        self.assertEqual(set(result), {'items', 'next', 'group_fields'})
        return {row['name']: row for row in result['items']}

    def test_rows_carry_the_contact_and_the_update_time(self):
        rows = self.rows(self.manager)
        row = rows[self.ticket]
        self.assertEqual(row['contact_title'], self.contact_title)
        self.assertTrue(row['modified'])
        self.assertTrue(all('contact_title' in item and 'modified' in item for item in rows.values()))

    def test_a_user_outside_the_business_type_sees_no_contact(self):
        row = self.rows(self.outsider).get(self.ticket)
        self.assertTrue(row is None or row['contact_title'] == '', row)

    def test_guest_is_denied(self):
        self.assertEqual(requests.get(self.url, timeout=30).status_code, 403)


if __name__ == '__main__':
    unittest.main()
