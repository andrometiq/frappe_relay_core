"""Bench AI service contract and daemon: signing, request ids, timeouts and fail-closed results."""
import asyncio
import json
import time
import unittest
from types import SimpleNamespace

import httpx

from relay_core.ai.remote import daemon, protocol

SECRET_A, SECRET_B = 'a' * 40, 'b' * 40
URL = 'http://127.0.0.1:18490/codex/responses'
BODY = {'model': 'gpt-test', 'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'hello'}]}]}
SSE = ('data: {"type":"response.output_text.delta","delta":"{\\"ok\\":true}"}\n\n'
       'data: {"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":3,'
       '"output_tokens":2},"output":[]}}\n\n')


class Protocol(unittest.TestCase):
    def test_a_signed_body_verifies_and_any_change_is_refused(self):
        raw, now = protocol.canonical({'id': 'x'}), int(time.time())
        signature = protocol.sign(SECRET_A, raw, now)
        self.assertEqual(protocol.verify(SECRET_A, raw, now, signature), {'id': 'x'})
        for raw_in, secret, stamp in ((raw + b' ', SECRET_A, now), (raw, SECRET_B, now), (raw, SECRET_A, now + 1)):
            with self.subTest(secret=secret[0], stamp=stamp), self.assertRaises(protocol.InvalidSignature):
                protocol.verify(secret, raw_in, stamp, signature)

    def test_an_old_callback_and_a_short_secret_are_refused(self):
        raw, then = b'{}', int(time.time()) - protocol.MAX_SKEW - 5
        with self.assertRaisesRegex(protocol.InvalidSignature, 'Expired'):
            protocol.verify(SECRET_A, raw, then, protocol.sign(SECRET_A, raw, then))
        with self.assertRaisesRegex(protocol.InvalidSignature, 'not configured'):
            protocol.sign('short', raw, then)

    def test_an_entry_verifies_only_with_its_own_sites_secret(self):
        entry = protocol.signed_entry(SECRET_A, 'a.local', 'f' * 64)
        self.assertEqual(protocol.verify_entry({'a.local': SECRET_A}, entry), ('a.local', 'f' * 64))
        forged = dict(entry, site='b.local')
        with self.assertRaises(protocol.InvalidSignature):
            protocol.verify_entry({'a.local': SECRET_A, 'b.local': SECRET_B}, forged)
        with self.assertRaisesRegex(protocol.InvalidSignature, 'Unknown site'):
            protocol.verify_entry({'b.local': SECRET_B}, entry)

    def test_the_same_turn_has_the_same_request_id_whatever_its_credentials(self):
        key = protocol.body_key(URL, BODY)
        self.assertEqual(key, protocol.body_key(URL, json.loads(json.dumps(BODY))))
        self.assertNotEqual(key, protocol.body_key(URL, dict(BODY, model='other')))
        self.assertEqual(protocol.request_id('a.local', 'AR-1', key), protocol.request_id('a.local', 'AR-1', key))
        self.assertNotEqual(protocol.request_id('a.local', 'AR-1', key), protocol.request_id('b.local', 'AR-1', key))


class Service(unittest.TestCase):
    def setUp(self):
        self.calls, self.acked, self.delay = [], [], 0
        self.redis = SimpleNamespace(xack=self.xack)

    async def xack(self, *args):
        self.acked.append(args[-1])

    async def respond(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith('.request'):
            self.calls.append(('request', request.headers['host']))
            return httpx.Response(200, json={'message': {'status': 'ready', 'url': URL, 'headers': {}, 'body': BODY,
                                                         'timeout': 1, 'deadline': time.time() + 30}})
        if request.url.path.endswith('.result'):
            payload = json.loads(request.content)
            protocol.verify(SECRET_A, request.content, request.headers['X-Relay-AI-Timestamp'],
                            request.headers['X-Relay-AI-Signature'])
            self.calls.append(('result', payload))
            return httpx.Response(200, json={'message': {'status': 'stored'}})
        self.calls.append(('provider', request.url.path))
        await asyncio.sleep(self.delay)
        return httpx.Response(200, text=SSE)

    def run_entry(self, deliveries=1, entry=None):
        async def go():
            async with httpx.AsyncClient(transport=httpx.MockTransport(self.respond)) as http:
                service = daemon.Service(self.redis, http, {'a.local': SECRET_A}, 'http://127.0.0.1:8000')
                await service.handle('1-0', entry or protocol.signed_entry(SECRET_A, 'a.local', 'e' * 64), deliveries)
                return service
        return asyncio.run(go())

    def test_a_request_reaches_the_provider_and_its_answer_goes_back_signed(self):
        service = self.run_entry()
        self.assertEqual([call[0] for call in self.calls], ['request', 'provider', 'result'])
        self.assertEqual(self.calls[0][1], 'a.local')
        self.assertEqual(self.calls[2][1], {'id': 'e' * 64, 'status': 200, 'body': SSE})
        self.assertEqual((self.acked, service.counts['done']), (['1-0'], 1))

    def test_a_slow_provider_becomes_a_timeout_result(self):
        self.delay = 2
        self.run_entry()
        self.assertEqual(self.calls[-1][1]['error'], 'timeout')
        self.assertEqual(self.acked, ['1-0'])

    def test_a_request_requeued_more_than_once_fails_closed_without_a_provider_call(self):
        self.run_entry(deliveries=protocol.MAX_DELIVERIES + 1)
        self.assertEqual([call[0] for call in self.calls], ['result'])
        self.assertEqual(self.calls[0][1]['error'], 'lost')

    def test_a_forged_entry_is_dropped_without_any_call(self):
        self.run_entry(entry=protocol.signed_entry(SECRET_B, 'a.local', 'e' * 64))
        self.assertEqual((self.calls, self.acked), ([], ['1-0']))


if __name__ == '__main__':
    unittest.main()
