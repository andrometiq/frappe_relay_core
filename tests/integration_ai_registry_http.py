"""Local relay.test HTTP acceptance of code tool approval; only worktree code, no model or channel calls.

Run from the app folder: SITES_PATH=<bench>/sites ../../env/bin/python -B -m unittest discover -s tests -p 'integration_ai_registry_http.py'
Fixtures are fake (Acme Textiles), reusable and removed or disabled afterwards. API credentials are ephemeral.
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

from relay_core.ai.registry import ToolContext, relay_tool

KEY = 'acme.open_orders'


@relay_tool(audience='customer', label='Open orders', business_doctype='Customer')
def open_orders(limit: int = 5, *, ctx: ToolContext) -> dict:
    """List the sender's own open orders."""
    return {'limit': limit}


def connect():
    frappe.init(site='relay.test', sites_path=SITES)
    frappe.connect()
    frappe.set_user('Administrator')
    frappe.flags.mute_emails = True


def api_user(email, role):
    name = frappe.db.get_value('User', {'email': email}, 'name')
    user = frappe.get_doc('User', name) if name else frappe.get_doc({'doctype': 'User', 'email': email,
        'first_name': 'Acme Textiles registry ' + role, 'send_welcome_email': 0, 'roles': [{'role': role}]}).insert()
    key, secret = secrets.token_hex(12), secrets.token_hex(24)
    user.api_key, user.api_secret, user.enabled = key, secret, 1
    user.save()
    return user.name, f'token {key}:{secret}'


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


class ToolApprovalHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        for name in ('enqueue', 'publish_realtime', 'sendmail'):
            cls.stack.enter_context(patch.object(frappe, name))
        connect()
        from relay_core.ai.capabilities import DOCTYPE, manifest_hash
        from relay_core.ai.registry.sync import manifest
        cls.ai_enabled = frappe.db.get_single_value('Relay Settings', 'enable_ai_features')
        frappe.db.set_single_value('Relay Settings', 'enable_ai_features', 1)
        cls.manager, cls.manager_token = api_user('relay-registry-manager@example.invalid', 'System Manager')
        cls.agent, cls.agent_token = api_user('relay-registry-agent@example.invalid', 'Relay Communication User')
        frappe.delete_doc(DOCTYPE, KEY, force=True, ignore_missing=True)
        cls.manifest = manifest(open_orders, KEY, 'acme_app', 'acme_app.relay.tools.open_orders')
        cls.digest = manifest_hash(cls.manifest)
        frappe.get_doc(dict(doctype=DOCTYPE, name=KEY, capability_key=KEY, app='acme_app', kind='Tool',
            business_doctype='Customer', label='Open orders', enabled=1, status='Pending approval', current_hash=cls.digest,
            manifest=json.dumps(cls.manifest, sort_keys=True))).db_insert()
        frappe.db.commit()
        frappe.destroy()

        def application(environ, start_response):
            environ['HTTP_X_FRAPPE_SITE_NAME'] = 'relay.test'
            return frappe.app.application(environ, start_response)
        cls.server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/api/method/relay_core.ai.capabilities.approve'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)
        connect()
        frappe.delete_doc('Relay AI Capability', KEY, force=True, ignore_missing=True)
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
        return requests.post(self.url, json={'name': KEY}, headers={'Authorization': token}, timeout=30)

    def row(self):
        connect()
        try:
            return frappe.db.get_value('Relay AI Capability', KEY, ['status', 'approved_hash'], as_dict=True)
        finally:
            frappe.destroy()

    def test_1_a_non_manager_cannot_approve_a_tool(self):
        response = self.approve(self.agent_token)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(self.digest, response.text)
        self.assertEqual(self.row().status, 'Pending approval')

    def test_2_a_manager_approves_the_exact_code_hash(self):
        response = self.approve(self.manager_token)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['message'], {'name': KEY, 'status': 'Approved', 'approved_hash': self.digest})
        self.assertEqual(self.row().approved_hash, self.digest)

    def test_3_an_uninstalled_tool_goes_missing_and_cannot_be_approved(self):
        connect()
        try:
            from relay_core.ai.capabilities import sync
            sync()
            frappe.db.commit()
        finally:
            frappe.destroy()
        self.assertEqual(self.row().status, 'Missing')
        self.assertGreaterEqual(self.approve(self.manager_token).status_code, 400)
        self.assertEqual(self.row().status, 'Missing')


if __name__ == '__main__':
    unittest.main()
