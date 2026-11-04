"""Site side of the bench AI service: idempotent hand-over, stored results, fallback and undo."""
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from relay_core.ai.remote import protocol, site
from test_ai_service_protocol import BODY, SECRET_A, SSE, URL


class FakeCache:
    """The Redis commands the site side uses, with site-prefixed keys as RedisWrapper makes them."""

    def __init__(self):
        self.values, self.sorted = {}, {}

    def make_key(self, key):
        return f'site_db|{key}'.encode()

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return None
        self.values[key] = value.encode() if isinstance(value, str) else value
        return True

    def exists(self, key, shared=False):
        assert shared, 'RedisWrapper.exists would prefix the key twice'
        return int(key in self.values)

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def expire(self, key, seconds):
        return True

    def delete(self, key):
        self.values.pop(key, None)

    def zadd(self, key, mapping):
        self.sorted.setdefault(key, {}).update(mapping)

    def zrem(self, key, member):
        self.sorted.get(key, {}).pop(member, None)

    def zrangebyscore(self, key, low, high, start=0, num=None):
        return [member.encode() for member, score in self.sorted.get(key, {}).items() if low <= score <= high][:num]


class SiteSide(unittest.TestCase):
    def setUp(self):
        self.cache, self.stream, self.jobs, self.beat = FakeCache(), [], [], {'ts': time.time()}
        connection = SimpleNamespace(get=lambda key: json.dumps(self.beat), xadd=lambda *args, **kwargs: self.stream.append(args))
        self.frappe = SimpleNamespace(cache=self.cache, local=SimpleNamespace(site='a.local'), set_user=Mock(),
            session=SimpleNamespace(user='Guest'),
            conf={'relay_ai_service': 1, 'relay_ai_service_secret': SECRET_A}, db=Mock(),
            enqueue=lambda method, **kwargs: self.jobs.append((method, kwargs)),
            throw=Mock(side_effect=ValueError), PermissionError=PermissionError, ValidationError=ValueError)
        for target, value in (('frappe', self.frappe), ('queue_connection', lambda: connection)):
            patcher = patch.object(site, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.state = {'run': 'AR-1', 'undo': [], 'account': 'Codex', 'handed': False}

    def hand(self):
        with self.assertRaises(site.Handed):
            site.send(self.state, URL, {'Authorization': 'Bearer secret'}, BODY, 20)

    def identifier(self):
        return protocol.request_id('a.local', 'AR-1', protocol.body_key(URL, BODY))

    def test_a_turn_is_queued_once_without_credentials(self):
        self.hand()
        self.hand()  # The per-minute recovery or a duplicate job replays the same turn.
        self.assertEqual(len(self.stream), 1)
        stream, entry = self.stream[0]
        self.assertEqual((stream, protocol.verify_entry({'a.local': SECRET_A}, entry)), (protocol.STREAM, ('a.local', self.identifier())))
        stored = b''.join(value for value in self.cache.values.values() if isinstance(value, bytes))
        self.assertNotIn(b'Bearer', stored)
        self.assertTrue(site.is_waiting('AR-1'))

    def test_a_stored_result_replays_as_the_providers_own_stream(self):
        from frappe_tools.ai.providers import codex
        self.hand()
        self.assertTrue(site.store(self.identifier(), site.spec_for(self.identifier()), {'status': 200, 'body': SSE}))
        answer = site.send(self.state, URL, {}, BODY, 20)
        self.assertEqual(codex.parse_response(answer)[0], '{"ok":true}')
        self.assertFalse(site.is_waiting('AR-1'))
        self.assertEqual(self.jobs, [('relay_core.automation.service.process', {'name': 'AR-1', 'queue': 'default',
            'job_id': 'relay-ai-resume-' + self.identifier(), 'deduplicate': True})])
        self.assertEqual([args.args for args in self.frappe.set_user.call_args_list], [('Administrator',), ('Guest',)])

    def test_a_second_result_is_ignored_and_does_not_resume_twice(self):
        self.hand()
        spec = site.spec_for(self.identifier())
        self.assertTrue(site.store(self.identifier(), spec, {'status': 200, 'body': SSE}))
        self.assertFalse(site.store(self.identifier(), spec, {'error': 'timeout'}))
        self.assertEqual(len(self.jobs), 1)

    def test_a_service_timeout_fails_the_turn_as_a_provider_timeout(self):
        self.hand()
        self.assertEqual(site.expire_overdue(time.time() + 3600), 1)
        with self.assertRaises(requests.Timeout):
            site.send(self.state, URL, {}, BODY, 20)

    def test_without_a_live_service_the_turn_runs_in_the_worker(self):
        self.beat['ts'] = time.time() - protocol.HEARTBEAT_SECONDS - 1
        with patch.object(site.requests, 'post', return_value='provider answer') as post:
            self.assertEqual(site.send(self.state, URL, {'Authorization': 'x'}, BODY, 20), 'provider answer')
        post.assert_called_once()
        self.assertEqual(self.stream, [])

    def test_handing_over_undoes_the_jobs_attempt_and_spend(self):
        undone = []
        with patch.object(site, 'is_enabled', return_value=True), site.transport('AR-1'):
            site.on_handed(lambda: undone.append('attempt'))
            site.on_handed(lambda: undone.append('spend'))
            raise site.Handed('AR-1')
        self.assertEqual(undone, ['spend', 'attempt'])
        self.frappe.db.rollback.assert_called_once()
        self.assertIsNone(site.turn_state.get())


if __name__ == '__main__':
    unittest.main()
