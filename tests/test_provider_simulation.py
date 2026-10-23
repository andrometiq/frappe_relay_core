"""Local HTTP provider simulations exercising complete(), not a canned return.

Only the network destination is replaced: production request construction,
headers, response parsing, limits and error handling are exercised unchanged.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
import urllib.request
from unittest.mock import patch
from relay_core.automation import providers


class ProviderHTTPSimulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                server = self.server
                raw = self.rfile.read(int(self.headers['Content-Length']))
                server.requests.append((self.path, dict(self.headers), json.loads(raw)))
                self.send_response(server.status)
                if server.status == 307:
                    self.send_header('Location', server.url + '/redirect-destination')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(server.response)
            def log_message(self, *_):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.url = 'http://127.0.0.1:' + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.original_build_opener = staticmethod(urllib.request.build_opener)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=3)

    def setUp(self):
        self.server.requests = []
        self.server.status = 200
        self.decision = dict(category='Query', brief='தமிழ் கேள்வி', create_ticket=False,
                             reply=None, handoff=True)
        self.targets = []
        owner = self
        class LoopbackOpener:
            def open(self, req, timeout):
                owner.targets.append(req.full_url)
                local = urllib.request.Request(owner.server.url + '/response',
                    data=req.data, headers=dict(req.header_items()), method=req.get_method())
                return owner.original_build_opener(providers.NoRedirect()).open(local, timeout=timeout)
        self.mock = patch.object(urllib.request, 'build_opener', return_value=LoopbackOpener())
        self.mock.start(); self.addCleanup(self.mock.stop)

    def response(self, provider, text, complete=True):
        if provider == 'OpenRouter':
            return {'choices': [{'finish_reason': 'stop' if complete else 'length',
                                 'message': {'content': text}}]}
        if provider in ('Anthropic', 'GLM'):
            return {'stop_reason': 'end_turn' if complete else 'max_tokens',
                    'content': [{'type': 'text', 'text': text}]}
        return {'candidates': [{'finishReason': 'STOP' if complete else 'MAX_TOKENS',
                'content': {'parts': [{'text': 'hidden reasoning', 'thought': True}, {'text': text}]}}]}

    def test_provider_round_trips_preserve_decision_and_authentication(self):
        for provider in ('OpenRouter', 'Anthropic', 'GLM', 'Gemini'):
            with self.subTest(provider=provider):
                self.server.response = json.dumps(self.response(provider, json.dumps(self.decision))).encode()
                result = providers.complete(provider, 'synthetic-model', 'synthetic-secret', 'வணக்கம்')
                self.assertEqual(result, self.decision)
                _, headers, body = self.server.requests[-1]
                headers = {key.lower(): value for key, value in headers.items()}
                key = 'authorization' if provider == 'OpenRouter' else 'x-goog-api-key' if provider == 'Gemini' else 'x-api-key'
                self.assertEqual(headers[key], ('Bearer ' if provider == 'OpenRouter' else '') + 'synthetic-secret')
                self.assertNotIn('synthetic-secret', json.dumps(body))
                self.assertIn('வணக்கம்', json.dumps(body, ensure_ascii=False))
                self.assertTrue(self.targets[-1].startswith('https://'))

    def test_incomplete_decisions_never_escape_adapter(self):
        for provider in ('OpenRouter', 'Anthropic', 'GLM', 'Gemini'):
            with self.subTest(provider=provider):
                self.server.response = json.dumps(self.response(provider, json.dumps(self.decision), False)).encode()
                before = len(self.server.requests)
                with self.assertRaises(providers.ProviderError):
                    providers.complete(provider, 'synthetic-model', 'synthetic-secret', 'hello')
                self.assertEqual(len(self.server.requests), before + 1)

    def test_limits_invalid_json_and_http_errors_are_redacted(self):
        for status, response in [(200, b'x'*262145), (200, b'invalid json'),
                                 (429, b'synthetic-secret rate limited'), (500, b'synthetic-secret upstream failure')]:
            with self.subTest(status=status, size=len(response)):
                self.server.status, self.server.response = status, response
                before = len(self.server.requests)
                with self.assertRaises(providers.ProviderError) as caught:
                    providers.complete('OpenRouter', 'synthetic-model', 'synthetic-secret', 'hello')
                self.assertNotIn('synthetic-secret', str(caught.exception))
                self.assertEqual(len(self.server.requests), before + 1)

    def test_redirect_does_not_forward_credentials(self):
        self.server.status, self.server.response = 307, b'{}'
        with self.assertRaises(providers.ProviderError):
            providers.complete('OpenRouter', 'synthetic-model', 'synthetic-secret', 'hello')
        self.assertEqual(len(self.server.requests), 1)
