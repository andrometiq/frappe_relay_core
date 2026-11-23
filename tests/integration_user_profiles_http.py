"""Local relay.test HTTP acceptance of user_profiles: own edits, denied edits of others, guest denial and response shapes.

Run from the app folder: SITES_PATH=../../sites ../../env/bin/python -B -m unittest discover -s tests -p 'integration_user_profiles_http.py'
Fixtures are clearly named, reusable local users. API credentials are ephemeral.
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

PROFILE_KEYS = {'user', 'full_name', 'user_image', 'display_name', 'job_title', 'status', 'status_text', 'status_clear_at',
                'theme', 'density', 'notify_messages', 'notify_mentions', 'notify_sound'}


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
    key, secret = secrets.token_hex(12), secrets.token_hex(24)
    user.api_key, user.api_secret, user.enabled = key, secret, 1
    user.save()
    return {'Authorization': f'token {key}:{secret}'}


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


class UserProfilesHttpTests(unittest.TestCase):
    AGENT, OTHER = 'relay-profile-agent@example.invalid', 'relay-profile-other@example.invalid'

    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        for name in ('enqueue', 'sendmail'):
            cls.stack.enter_context(patch.object(frappe, name))
        connect()
        cls.agent = user_with_key(cls.AGENT, 'Local profile agent', ['Relay Communication User'])
        cls.other = user_with_key(cls.OTHER, 'Local profile colleague', ['Relay Communication User'])
        for user in (cls.AGENT, cls.OTHER):
            frappe.db.delete('Relay User Profile', {'user': user})
        frappe.db.commit()
        frappe.destroy()

        def application(environ, start_response):
            environ['HTTP_X_FRAPPE_SITE_NAME'] = 'relay.test'
            return frappe.app.application(environ, start_response)
        cls.server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/api/method/relay_core.user_profiles.'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)
        connect()
        for email in (cls.AGENT, cls.OTHER):
            user = frappe.get_doc('User', email)
            user.api_key = user.api_secret = None
            user.enabled = 0
            user.save()
        frappe.db.commit(); frappe.destroy()
        cls.stack.close()

    def call(self, method, headers=None, **values):
        if method == 'update':
            return requests.post(self.url + method, json=values, headers=headers or {}, timeout=20)
        return requests.get(self.url + method, params=values, headers=headers or {}, timeout=20)

    def test_own_profile_update_and_read(self):
        response = self.call('update', self.agent, display_name='Profile agent', job_title='Sales coordinator',
                             status='Busy', status_text='At dispatch', clear_after='1h', theme='Dark')
        self.assertEqual(response.status_code, 200, response.text)
        profile = response.json()['message']
        self.assertEqual(set(profile), PROFILE_KEYS)
        self.assertEqual((profile['user'], profile['status'], profile['theme']), (self.AGENT, 'Busy', 'Dark'))
        self.assertTrue(profile['status_clear_at'])
        read = self.call('get', self.agent)
        self.assertEqual(read.status_code, 200)
        self.assertEqual(read.json()['message']['job_title'], 'Sales coordinator')

    def test_editing_or_reading_another_users_profile_is_denied(self):
        response = self.call('update', self.agent, user=self.OTHER, status='Away')
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.call('get', self.agent, user=self.OTHER).status_code, 403)
        self.assertNotEqual(self.call('get', self.other).json()['message']['status'], 'Away')

    def test_guest_is_denied(self):
        self.assertEqual(self.call('get').status_code, 403)
        self.assertEqual(self.call('update', status='Away').status_code, 403)

    def test_invalid_values_are_refused(self):
        self.assertEqual(self.call('update', self.agent, status='Sleeping').status_code, 417)
        self.assertEqual(self.call('update', self.agent, owner='x').status_code, 417)

    def test_cards_show_public_fields(self):
        self.call('update', self.other, display_name='Profile colleague', status='Do not disturb')
        response = self.call('cards', self.agent, users=f'["{self.OTHER}"]')
        self.assertEqual(response.status_code, 200)
        card = response.json()['message']['items'][0]
        self.assertEqual(set(card), {'user', 'name', 'image', 'job_title', 'status', 'status_text'})
        self.assertEqual((card['name'], card['status']), ('Profile colleague', 'Do not disturb'))


if __name__ == '__main__':
    unittest.main()
