"""Local relay.test HTTP acceptance of the Access page API: shapes, manager changes, denied users and guests.

Run from the app folder: SITES_PATH=../../sites ../../env/bin/python -B -m unittest discover -s tests -p 'integration_access_http.py'
Fixtures are clearly named, reusable local users and one fixture team. API credentials are ephemeral.
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
SITES = os.environ['SITES_PATH']
sys.path.insert(0, str(ROOT))
import frappe
import frappe.app
import requests

USER, MANAGER = 'Relay Communication User', 'Relay Communication Manager'
ROW_KEYS = {'user', 'full_name', 'image', 'role', 'team_user', 'teams', 'business_types', 'role_locked'}
TEAM = 'Relay Access Fixture Team'


def connect():
    frappe.init(site='relay.test', sites_path=SITES)
    frappe.connect()
    frappe.set_user('Administrator')
    frappe.flags.mute_emails = True


def user_with_key(email, name, roles):
    if not frappe.db.exists('User', email):
        frappe.get_doc({'doctype': 'User', 'email': email, 'first_name': name, 'send_welcome_email': 0,
                        'roles': [{'role': role} for role in roles]}).insert()
    user = frappe.get_doc('User', email)
    user.set('roles', [{'role': role} for role in roles])
    key, secret = secrets.token_hex(12), secrets.token_hex(24)
    user.api_key, user.api_secret, user.enabled = key, secret, 1
    user.save()
    return {'Authorization': f'token {key}:{secret}'}


def remove_from_types(user):
    for name in frappe.get_all('Relay Contact Type User', filters={'user': user, 'parenttype': 'Relay Contact Type'}, pluck='parent'):
        doc = frappe.get_doc('Relay Contact Type', name)
        doc.set('users', [{'user': row.user} for row in doc.users if row.user != user])
        doc.save()


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


class AccessHttpTests(unittest.TestCase):
    MANAGER_USER, AGENT, TARGET = ('relay-access-manager@example.invalid', 'relay-access-agent@example.invalid',
                                   'relay-access-target@example.invalid')

    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        for name in ('enqueue', 'sendmail'):
            cls.stack.enter_context(patch.object(frappe, name))
        connect()
        cls.manager = user_with_key(cls.MANAGER_USER, 'Local access manager', [MANAGER])
        cls.agent = user_with_key(cls.AGENT, 'Local access agent', [USER])
        user_with_key(cls.TARGET, 'Local access target', [USER, 'Dashboard Manager'])
        remove_from_types(cls.TARGET)
        team = frappe.db.get_value('Relay Team', {'title': TEAM}) or None
        doc = frappe.get_doc('Relay Team', team) if team else frappe.new_doc('Relay Team')
        doc.title = TEAM
        doc.set('members', [{'user': cls.MANAGER_USER}])
        doc.save()
        cls.team = doc.name
        cls.business_type = frappe.get_all('Relay Contact Type', pluck='name', limit=1)[0]
        frappe.db.commit()
        frappe.destroy()

        def application(environ, start_response):
            environ['HTTP_X_FRAPPE_SITE_NAME'] = 'relay.test'
            return frappe.app.application(environ, start_response)
        cls.server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/api/method/relay_core.access.'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)
        connect()
        remove_from_types(cls.TARGET)
        frappe.delete_doc('Relay Team', cls.team, ignore_permissions=True, force=True)
        for email in (cls.MANAGER_USER, cls.AGENT, cls.TARGET):
            user = frappe.get_doc('User', email)
            user.api_key = user.api_secret = None
            user.enabled = 0
            user.save()
        frappe.db.commit(); frappe.destroy()
        cls.stack.close()

    def call(self, method, headers=None, **values):
        if method == 'save':
            return requests.post(self.url + method, json=values, headers=headers or {}, timeout=30)
        return requests.get(self.url + method, params=values, headers=headers or {}, timeout=30)

    def roles(self, user):
        connect()
        try:
            return set(frappe.get_roles(user))
        finally:
            frappe.destroy()

    def test_manager_reads_everyone_and_changes_role_teams_and_business_types(self):
        response = self.call('directory', self.manager)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()['message']
        self.assertEqual(set(result), {'can_edit', 'items', 'teams', 'business_types'})
        self.assertTrue(result['can_edit'])
        rows = {row['user']: row for row in result['items']}
        self.assertEqual(set(rows[self.TARGET]), ROW_KEYS)
        self.assertEqual((rows[self.TARGET]['role'], rows[self.TARGET]['role_locked']), ('User', ''))
        self.assertIn('own role', rows[self.MANAGER_USER]['role_locked'])
        self.assertIn({'value': self.team, 'label': TEAM}, result['teams'])

        response = self.call('save', self.manager, user=self.TARGET, role='Manager', team_user=1,
                             teams=[self.team], business_types=[self.business_type])
        self.assertEqual(response.status_code, 200, response.text)
        row = response.json()['message']
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual((row['role'], row['team_user'], row['teams'], row['business_types']),
                         ('Manager', True, [self.team], [self.business_type]))
        roles = self.roles(self.TARGET)
        self.assertIn('Dashboard Manager', roles, 'Roles outside Relay stay')
        self.assertNotIn(USER, roles)

        response = self.call('save', self.manager, user=self.TARGET, role='User', team_user=0, teams=[], business_types=[])
        self.assertEqual(response.status_code, 200, response.text)
        row = response.json()['message']
        self.assertEqual((row['role'], row['team_user'], row['teams'], row['business_types']), ('User', False, [], []))

    def test_manager_cannot_change_own_role_or_save_unknown_values(self):
        self.assertEqual(self.call('save', self.manager, user=self.MANAGER_USER, role='User').status_code, 417)
        self.assertIn(MANAGER, self.roles(self.MANAGER_USER))
        self.assertEqual(self.call('save', self.manager, user=self.TARGET, teams=['Ghost team']).status_code, 417)
        self.assertEqual(self.call('save', self.manager, user=self.TARGET, role='Owner').status_code, 417)
        self.assertEqual(self.call('save', self.manager, user='Administrator', role='User').status_code, 417)

    def test_user_reads_only_own_access_and_cannot_change_it(self):
        response = self.call('directory', self.agent)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()['message']
        self.assertFalse(result['can_edit'])
        self.assertEqual([row['user'] for row in result['items']], [self.AGENT])
        response = self.call('save', self.agent, user=self.TARGET, role='Manager')
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.call('save', self.agent, user=self.AGENT, role='Manager').status_code, 403)
        self.assertEqual(self.call('user_options', self.agent, query='relay').status_code, 403)
        self.assertNotIn(MANAGER, self.roles(self.TARGET))

    def test_manager_searches_staff_users(self):
        response = self.call('user_options', self.manager, query='relay-access')
        self.assertEqual(response.status_code, 200, response.text)
        options = response.json()['message']
        self.assertTrue(all(set(option) == {'value', 'label'} for option in options))
        self.assertIn(self.TARGET, [option['value'] for option in options])

    def test_guest_is_denied(self):
        self.assertEqual(self.call('directory').status_code, 403)
        self.assertEqual(self.call('user_options').status_code, 403)
        self.assertEqual(self.call('save', user=self.TARGET, role='Manager').status_code, 403)


if __name__ == '__main__':
    unittest.main()
