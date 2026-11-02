"""Site enrolment: config and setup codes, the Hub proof, failures that keep the old link, and the Hub REST call."""
import hashlib
import hmac
import json
import threading
import unittest
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core.onboarding import enrolment
from relay_core.onboarding.messages import OnboardingError

TOKEN = 'relay_enrol_' + 'a' * 64
HUB = 'http://127.0.0.1:18091'
RESULT = {'site_id': 'acme-localhost', 'mcp_url': HUB + '/mcp', 'hub_token': 'relay_' + 'b' * 64,
          'hub_origin': HUB, 're_enrolled': False}


class FakeCache:
    def __init__(self):
        self.values = {}
        self.lock = Mock(side_effect=lambda *a, **k: nullcontext())

    def make_key(self, key):
        return 'site:' + key

    def set_value(self, key, value, expires_in_sec=None):
        self.values[key] = value

    def get_value(self, key):
        return self.values.get(key)

    def delete_value(self, key):
        self.values.pop(key, None)


def throw(message, exception=ValueError):
    raise exception(message)


def fake_frappe(conf=None, roles=('System Manager',)):
    settings = _dict(save=Mock())
    settings.update = lambda values: dict.update(settings, values)
    return SimpleNamespace(conf=_dict(conf or {}), cache=FakeCache(), local=SimpleNamespace(site='acme.localhost'),
                           utils=SimpleNamespace(get_url=lambda: 'http://acme.localhost:8001', now_datetime=lambda: 'now'),
                           db=SimpleNamespace(commit=Mock(), exists=Mock(return_value=False),
                                              get_single_value=Mock(return_value='Acme')),
                           defaults=SimpleNamespace(get_global_default=Mock(return_value=None)),
                           get_single=Mock(return_value=settings), get_roles=Mock(return_value=list(roles)),
                           throw=throw, PermissionError=PermissionError, settings=settings)


class SetupCredentialTests(unittest.TestCase):
    def credential(self, code='', **conf):
        with patch.object(enrolment, 'frappe', fake_frappe(conf)):
            return enrolment.setup_credential(code)

    def test_site_config_token_needs_no_code(self):
        self.assertEqual(self.credential(relay_hub_origin=HUB + '/', relay_enrolment_token=TOKEN), (HUB, TOKEN, 'Site config'))

    def test_no_config_asks_for_a_setup_code(self):
        with self.assertRaises(OnboardingError) as caught:
            self.credential()
        self.assertEqual(caught.exception.code, 'setup_code_required')

    def test_a_pasted_setup_link_names_its_hub(self):
        origin, code, source = self.credential('  https://hub.example.com/hub/enrol?code=' + TOKEN + ' ')
        self.assertEqual((origin, code, source), ('https://hub.example.com/hub', TOKEN, 'Setup code'))

    def test_a_bare_code_uses_the_configured_hub(self):
        self.assertEqual(self.credential(TOKEN, relay_hub_origin=HUB)[:2], (HUB, TOKEN))

    def test_bad_codes_and_plain_http_hubs_are_refused(self):
        for code, conf, expected in (('short', {'relay_hub_origin': HUB}, 'setup_code_invalid'),
                                     (TOKEN, {}, 'hub_origin_missing'),
                                     ('http://hub.example.com/enrol?code=' + TOKEN, {}, 'hub_origin_missing'),
                                     (TOKEN, {'relay_hub_origin': 'https://u:p@hub.example.com'}, 'hub_origin_missing')):
            with self.subTest(code=code, conf=conf), self.assertRaises(OnboardingError) as caught:
                self.credential(code, **conf)
            self.assertEqual(caught.exception.code, expected)


class ConnectTests(unittest.TestCase):
    def setUp(self):
        self.frappe = fake_frappe({'relay_hub_origin': HUB, 'relay_enrolment_token': TOKEN})
        self.settings = {}
        user = SimpleNamespace(name='relay-hub@acme.localhost')
        patches = [patch.object(enrolment, 'frappe', self.frappe),
                   patch('relay_core.settings.value', side_effect=self.settings.get),
                   patch.object(enrolment, 'service_user', return_value=user),
                   patch.object(enrolment, 'rotate_secret', return_value=('key', 'new-secret', 'old-secret')),
                   patch.object(enrolment, 'restore_secret'), patch.object(enrolment, 'check'),
                   patch('relay_core.channel_sync.sync')]
        self.mocks = [item.start() for item in patches]
        for item in patches:
            self.addCleanup(item.stop)
        self.restore = self.mocks[4]

    def hub(self, *, fail=None):
        """A Hub that checks the proof the way the real one does."""
        def enrol(origin, credential, body):
            self.request = (origin, credential, body)
            if fail:
                raise OnboardingError(fail)
            challenge = 'c' * 64
            with patch.object(enrolment, 'frappe', self.frappe):
                self.frappe.get_roles.return_value = ['Relay Hub Service']
                answer = enrolment.proof(body['nonce'], challenge)['proof']
            message = f"{body['nonce']}:{challenge}:{body['origin']}".encode()
            if answer != hmac.new(body['callback_secret'].encode(), message, hashlib.sha256).hexdigest():
                raise OnboardingError('proof_failed')
            return dict(RESULT)
        return patch.object(enrolment, 'request_enrolment', side_effect=enrol)

    def test_site_links_itself_and_saves_the_hub_credentials(self):
        with self.hub():
            self.assertEqual(enrolment.connect(), {'connected': True, 'account': 'acme-localhost', 're_enrolled': False})
        origin, credential, body = self.request
        self.assertEqual((origin, credential), (HUB, TOKEN))
        self.assertEqual((body['origin'], body['site_name'], body['core_api_key'], body['core_api_secret']),
                         ('http://acme.localhost:8001', 'acme.localhost', 'key', 'new-secret'))
        saved = self.frappe.settings
        self.assertEqual((saved['hub_url'], saved['hub_account'], saved['hub_token'], saved['callback_secret']),
                         (HUB + '/mcp', 'acme-localhost', RESULT['hub_token'], body['callback_secret']))
        self.assertEqual((saved['hub_origin'], saved['enrolment_source']), (HUB, 'Site config'))
        self.assertEqual(self.frappe.cache.values, {})
        self.restore.assert_not_called()

    def test_a_hub_refusal_saves_nothing_and_restores_the_old_secret(self):
        with self.hub(fail='origin_not_allowed'), self.assertRaises(OnboardingError) as caught:
            enrolment.connect()
        self.assertEqual(caught.exception.code, 'origin_not_allowed')
        self.assertNotIn('hub_token', self.frappe.settings)
        self.restore.assert_called_once_with('relay-hub@acme.localhost', 'old-secret')
        self.assertEqual(self.frappe.cache.values, {})

    def test_a_second_request_sees_the_link_and_does_not_enrol_again(self):
        self.settings.update(relay_hub_url=HUB + '/mcp', relay_hub_token='t' * 40, relay_hub_account='acme-localhost')
        with self.hub() as enrol:
            self.assertEqual(enrolment.connect()['account'], 'acme-localhost')
        enrol.assert_not_called()
        self.frappe.cache.lock.assert_called_once_with('site:relay-enrolment', timeout=120, blocking_timeout=60)

    def test_reconnect_enrols_again(self):
        self.settings.update(relay_hub_url=HUB + '/mcp', relay_hub_token='t' * 40, relay_hub_account='old')
        with self.hub() as enrol:
            enrolment.connect(reconnect=True)
        enrol.assert_called_once()


class ProofTests(unittest.TestCase):
    def proof(self, nonce, roles=('Relay Hub Service',), pending=None):
        frappe = fake_frappe(roles=roles)
        frappe.cache.values[enrolment.PENDING] = pending
        with patch.object(enrolment, 'frappe', frappe):
            return enrolment.proof(nonce, 'c' * 64), frappe

    def test_only_the_hub_service_role_gets_an_answer(self):
        pending = {'nonce': 'a' * 64, 'secret': 's' * 64, 'origin': 'http://acme.localhost:8001'}
        with self.assertRaises(PermissionError):
            self.proof('a' * 64, roles=('System Manager',), pending=pending)

    def test_an_unknown_or_reused_nonce_is_refused(self):
        pending = {'nonce': 'a' * 64, 'secret': 's' * 64, 'origin': 'http://acme.localhost:8001'}
        answer, frappe = self.proof('a' * 64, pending=pending)
        self.assertEqual(len(answer['proof']), 64)
        self.assertNotIn(enrolment.PENDING, frappe.cache.values)
        for nonce, state in (('b' * 64, pending), ('a' * 64, None), ('not hex', pending)):
            with self.subTest(nonce=nonce), self.assertRaises(PermissionError):
                self.proof(nonce, pending=state)


class Hub(BaseHTTPRequestHandler):
    replies = {}

    def do_POST(self):
        self.server.seen.append((self.path, self.headers.get('Authorization'), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
        status, body, headers = self.replies[self.path]
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Hub)
        self.server.seen = []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'

    def call(self, status, body, headers=None):
        if body == 'ok':
            body = dict(RESULT, mcp_url=self.origin + '/hub/mcp', hub_origin=self.origin + '/hub')
        Hub.replies = {'/hub/api/enrol': (status, body if isinstance(body, str) else json.dumps(body), headers or {})}
        return enrolment.request_enrolment(self.origin + '/hub', TOKEN, {'origin': 'x'})

    def test_success_returns_the_checked_answer_and_sends_the_bearer_token(self):
        result = self.call(201, 'ok')
        self.assertEqual((result['site_id'], result['hub_origin']), ('acme-localhost', self.origin + '/hub'))
        self.assertEqual(self.server.seen[0][:2], ('/hub/api/enrol', 'Bearer ' + TOKEN))

    def test_hub_error_codes_and_failures_map_to_codes(self):
        cases = ((403, {'error': {'code': 'origin_not_allowed', 'message': 'no'}}, {}, 'origin_not_allowed'),
                 (429, 'busy', {}, 'rate_limited'), (502, '', {}, 'hub_unavailable'),
                 (302, '', {'Location': 'https://evil.example/'}, 'hub_unavailable'),
                 (201, 'not json', {}, 'hub_response_invalid'),
                 (201, {'site_id': 'bad id', 'mcp_url': 'x', 'hub_token': 'y'}, {}, 'hub_response_invalid'))
        for status, body, headers, code in cases:
            with self.subTest(status=status, code=code), self.assertRaises(OnboardingError) as caught:
                self.call(status, body, headers)
            self.assertEqual(caught.exception.code, code)

    def test_an_unreachable_hub_is_unavailable(self):
        with self.assertRaises(OnboardingError) as caught:
            enrolment.request_enrolment('http://127.0.0.1:9', TOKEN, {})
        self.assertEqual(caught.exception.code, 'hub_unavailable')


if __name__ == '__main__':
    unittest.main()
