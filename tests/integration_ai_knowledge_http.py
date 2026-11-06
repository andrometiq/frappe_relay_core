"""Local relay.test HTTP acceptance of knowledge source approval; only worktree code, no model or channel calls.

Run from the app folder: SITES_PATH=<bench>/sites ../../env/bin/python -B -m unittest discover -s tests -p 'integration_ai_knowledge_http.py'
Fixtures are fake (Acme Textiles), reusable and removed or disabled afterwards. API credentials are ephemeral.
"""
import os
import sys
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parents[1]
SITES = os.environ['SITES_PATH']
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import frappe
import frappe.app
import requests

from integration_ai_registry_http import Quiet, api_user

SOURCE = 'Relay AI Knowledge Source'
METHOD = 'relay_core.relay_core.doctype.relay_ai_knowledge_source.relay_ai_knowledge_source.approve'


def connect():
    os.chdir(SITES)
    frappe.init(site='relay.test', sites_path=SITES)
    frappe.connect()
    frappe.set_user('Administrator')


class SourceApprovalHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        for name in ('enqueue', 'publish_realtime', 'sendmail'):
            cls.stack.enter_context(patch.object(frappe, name))
        connect()
        cls.ai_enabled = frappe.db.get_single_value('Relay Settings', 'enable_ai_features')
        frappe.db.set_single_value('Relay Settings', 'enable_ai_features', 1)
        cls.manager, cls.manager_token = api_user('relay-knowledge-manager@example.invalid', 'System Manager')
        cls.agent, cls.agent_token = api_user('relay-knowledge-agent@example.invalid', 'Relay Communication User')
        cls.base = frappe.get_doc(dict(doctype='Relay AI Knowledge Base', title='Acme Textiles staff projects',
                                       audience='staff', run_as_user=cls.manager)).insert()
        cls.source = frappe.get_doc(dict(doctype=SOURCE, title='Acme Textiles projects', knowledge_base=cls.base.name,
            source_type='DocType', reference_doctype='Project', content_fields='project_name')).insert()
        frappe.db.commit()
        frappe.destroy()

        def application(environ, start_response):
            environ['HTTP_X_FRAPPE_SITE_NAME'] = 'relay.test'
            return frappe.app.application(environ, start_response)
        cls.server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/api/method/{METHOD}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)
        connect()
        frappe.delete_doc(SOURCE, cls.source.name, force=True, ignore_missing=True)
        frappe.delete_doc('Relay AI Knowledge Base', cls.base.name, force=True, ignore_missing=True)
        frappe.db.set_single_value('Relay Settings', 'enable_ai_features', cls.ai_enabled or 0)
        for name in (cls.manager, cls.agent):
            user = frappe.get_doc('User', name)
            user.api_key = user.api_secret = None
            user.enabled = 0
            user.save()
        frappe.db.commit()
        frappe.destroy()
        cls.stack.close()

    def approve(self, token):
        return requests.post(self.url, json={'name': self.source.name}, headers={'Authorization': token}, timeout=30)

    def row(self):
        connect()
        try:
            return frappe.db.get_value(SOURCE, self.source.name, ['current_hash', 'approved_hash', 'approved_by'], as_dict=True)
        finally:
            frappe.destroy()

    def test_1_a_non_manager_cannot_approve_a_source(self):
        response = self.approve(self.agent_token)
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.row().approved_hash)

    def test_2_a_manager_approves_the_exact_configuration(self):
        response = self.approve(self.manager_token)
        self.assertEqual(response.status_code, 200, response.text)
        row = self.row()
        self.assertEqual(response.json()['message'], {'name': self.source.name, 'approved_hash': row.current_hash})
        self.assertEqual((row.approved_hash, row.approved_by), (row.current_hash, self.manager))


if __name__ == '__main__':
    unittest.main()
