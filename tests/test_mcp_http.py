"""MCP HTTP contracts on a real site. Run with RELAY_TEST_SITE=yrp.site and RELAY_AUTOMATION_TEST_SITES=<sites path>."""
import os
import secrets
import threading
import unittest
from unittest.mock import patch
from wsgiref.simple_server import WSGIRequestHandler, make_server

SITES = os.environ.get('RELAY_AUTOMATION_TEST_SITES')
PATH = '/api/method/relay_core.mcp.endpoint'


class Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(SITES, 'needs RELAY_AUTOMATION_TEST_SITES and a test site')
class MCPHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import frappe
        import frappe.app
        from channel_site_fixtures import init, user
        cls.site = init()
        cls.operator = user('relay-mcp-operator@example.invalid')
        cls.outsider = 'relay-mcp-outsider@example.invalid'
        if not frappe.db.exists('User', cls.outsider):
            with patch('frappe.core.doctype.user.user.throttle_user_creation'):
                frappe.get_doc({'doctype': 'User', 'email': cls.outsider, 'first_name': 'MCP Outsider', 'send_welcome_email': 0}).insert()
        cls.password = secrets.token_hex(16)
        cls.tokens = {}
        for actor in (cls.operator, cls.outsider):
            key, secret = secrets.token_hex(12), secrets.token_hex(24)
            doc = frappe.get_doc('User', actor)
            doc.api_key, doc.api_secret = key, secret
            doc.save(ignore_permissions=True)
            cls.tokens[actor] = 'token ' + key + ':' + secret
        from frappe.utils.password import update_password
        update_password(cls.operator, cls.password)
        frappe.db.commit()
        cls.hidden = cls.hidden_contact(frappe)

        def application(environ, start_response):
            environ['HTTP_X_FRAPPE_SITE_NAME'] = cls.site
            return frappe.app.application(environ, start_response)
        cls.server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    @classmethod
    def hidden_contact(cls, frappe):
        """A Relay Contact the operator cannot read, found with the real permission rules."""
        for name in frappe.get_all('Relay Contact', pluck='name', order_by='name desc', limit_page_length=300):
            if not frappe.has_permission('Relay Contact', 'read', doc=name, user=cls.operator):
                return name
        return None

    def post(self, body, headers=None, session=None):
        import requests
        return (session or requests).post(self.base + PATH, json=body, headers=headers or {}, timeout=60)

    def tool(self, name, arguments, actor=None):
        body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}
        response = self.post(body, {'Authorization': self.tokens[actor or self.operator]})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['result']

    def test_authentication_and_browser_rules(self):
        import requests
        body = {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}
        self.assertEqual(self.post(body).status_code, 401)
        session = requests.Session()
        login = session.post(self.base + '/api/method/login', json={'usr': self.operator, 'pwd': self.password}, timeout=30)
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.post(body, session=session).status_code, 401)  # A cookie session is not enough.
        token = {'Authorization': self.tokens[self.operator]}
        self.assertEqual(self.post(body, dict(token, Origin='https://browser.test')).status_code, 403)
        self.assertEqual(self.post(body, token).json()['result'], {})

    def test_user_without_relay_role_is_refused(self):
        response = self.post({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, {'Authorization': self.tokens[self.outsider]})
        self.assertEqual(response.status_code, 403)

    def test_core_permission_checks_run(self):
        result = self.tool('campaigns_create', {'title': 'MCP deny check', 'channel': 'none', 'rows': [{'phone': '91'}]})
        self.assertTrue(result['isError'])
        self.assertTrue(result['content'][0]['text'].startswith('Not permitted'), result)

    def test_contact_outside_scope_returns_no_data(self):
        if not self.hidden:
            self.skipTest('every contact is visible to the operator on this site')
        result = self.tool('contacts_read', {'contact': self.hidden})
        self.assertTrue(result['isError'])
        self.assertRegex(result['content'][0]['text'], '^(Not permitted|Not found)')
        self.assertNotIn('phone', result['structuredContent'])

    def test_oversized_request_is_rejected(self):
        body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': 'guide_read', 'arguments': {'padding': 'x' * (1024 * 1024 + 10)}}}
        self.assertEqual(self.post(body, {'Authorization': self.tokens[self.operator]}).status_code, 413)

    def test_listing_and_guide(self):
        response = self.post({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, {'Authorization': self.tokens[self.operator]})
        names = {entry['name'] for entry in response.json()['result']['tools']}
        self.assertTrue({'changes_since', 'chat_claim', 'chat_send_text', 'campaigns_control'} <= names)
        self.assertIn('Safe polling loop', self.tool('guide_read', {})['structuredContent']['guide'])


if __name__ == '__main__':
    unittest.main()
