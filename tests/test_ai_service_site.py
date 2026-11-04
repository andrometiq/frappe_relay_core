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

    def zcard(self, key):
        return len(self.sorted.get(key, {}))

    def zcount(self, key, low, high):
        return len(self.zrangebyscore(key, low, high))


class SiteSide(unittest.TestCase):
    def setUp(self):
        self.cache, self.stream, self.jobs, self.beat = FakeCache(), [], [], {'ts': time.time()}
        connection = SimpleNamespace(get=lambda key: json.dumps(self.beat), xadd=lambda *args, **kwargs: self.stream.append(args),
                                     xlen=lambda stream: len(self.stream), xpending=lambda stream, group: {'pending': 1})
        self.frappe = SimpleNamespace(cache=self.cache, local=SimpleNamespace(site='a.local'), set_user=Mock(),
            session=SimpleNamespace(user='Guest'),
            conf={'relay_ai_service': 1, 'relay_ai_service_secret': SECRET_A}, db=Mock(),
            enqueue=lambda method, **kwargs: self.jobs.append((method, kwargs)),
            throw=Mock(side_effect=ValueError), PermissionError=PermissionError, ValidationError=ValueError)
        for target, value in (('frappe', self.frappe), ('queue_connection', lambda: connection)):
            patcher = patch.object(site, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        token = site.turn_state.set({'run': 'AR-1', 'undo': []})
        self.addCleanup(site.turn_state.reset, token)

    def hand(self):
        with self.assertRaises(site.Handed):
            site.post('Codex', URL, {'Authorization': 'Bearer secret'}, BODY, 20)

    def identifier(self):
        return protocol.request_id('a.local', 'AR-1', protocol.body_key(URL, BODY))

    def test_a_turn_is_queued_once_without_credentials(self):
        self.hand()
        self.hand()  # The per-minute recovery or a duplicate job replays the same turn.
        self.assertEqual(len(self.stream), 1)
        stream, entry = self.stream[0]
        self.assertEqual((stream, protocol.verify_entry({'a.local': SECRET_A}, entry)), (protocol.stream('a.local'), ('a.local', self.identifier())))
        stored = b''.join(value for value in self.cache.values.values() if isinstance(value, bytes))
        self.assertNotIn(b'Bearer', stored)
        self.assertTrue(site.is_waiting('AR-1'))

    def test_a_stored_result_replays_as_the_providers_own_stream(self):
        from frappe_tools.ai.providers import codex
        self.hand()
        self.assertTrue(site.store(self.identifier(), site.spec_for(self.identifier()), {'status': 200, 'body': SSE}))
        answer, latency = site.post('Codex', URL, {}, BODY, 20)
        self.assertEqual((codex.parse_response(answer)[0], latency), ('{"ok":true}', None))
        self.assertFalse(site.is_waiting('AR-1'))
        self.assertEqual(self.jobs, [('relay_core.automation.service.process', {'name': 'AR-1', 'queue': 'default',
            'job_id': 'relay-ai-resume-' + self.identifier(), 'deduplicate': True, 'at_front': True})])
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
            site.post('Codex', URL, {}, BODY, 20)

    def test_without_a_live_service_the_turn_runs_in_the_worker(self):
        self.beat['ts'] = time.time() - protocol.HEARTBEAT_SECONDS - 1
        with patch.object(site.requests, 'post', return_value='provider answer') as post:
            self.assertEqual(site.post('Codex', URL, {'Authorization': 'x'}, BODY, 20), ('provider answer', None))
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
        self.assertEqual(site.turn_state.get(), {'run': 'AR-1', 'undo': []})  # The job's outer state is back.

    def test_a_finished_turn_keeps_its_attempt_and_spend_when_a_later_turn_is_handed(self):
        undone = []
        with patch.object(site, 'is_enabled', return_value=True), site.transport('AR-1'):
            site.on_handed(lambda: undone.append('matching spend'))
            site.settled()
            site.on_handed(lambda: undone.append('reply spend'))
            raise site.Handed('AR-1')
        self.assertEqual(undone, ['reply spend'])

    def test_a_handed_turn_must_answer_within_its_own_timeout(self):
        before = time.time()
        self.hand()
        self.assertLessEqual(site.spec_for(self.identifier())['deadline'], time.time() + 20)
        self.assertGreaterEqual(site.spec_for(self.identifier())['deadline'], before + 20)

    def test_a_replayed_turn_reports_the_provider_latency_the_service_measured(self):
        self.hand()
        result = {'id': self.identifier(), 'status': 200, 'body': SSE, 'latency_ms': 3210}
        with patch.object(site, 'authenticated', return_value=result):
            self.assertEqual(site.result(), {'status': 'stored'})
        self.assertEqual(site.post('Codex', URL, {}, BODY, 20)[1], 3210)

    def test_a_result_with_a_bad_latency_is_stored_without_it(self):
        self.hand()
        with patch.object(site, 'authenticated', return_value={'id': self.identifier(), 'status': 200, 'body': SSE,
                                                               'latency_ms': '9'}):
            site.result()
        self.assertIsNone(site.post('Codex', URL, {}, BODY, 20)[1])

    def test_a_replayed_turn_is_logged_by_the_first_hop_that_commits(self):
        callbacks = []
        self.frappe.db.after_commit = SimpleNamespace(add=callbacks.append)
        self.assertTrue(site.is_first_replay(URL, BODY))
        self.assertTrue(site.is_first_replay(URL, BODY))  # That hop rolled back: its log row is gone.
        callbacks[-1]()  # This hop commits.
        self.assertFalse(site.is_first_replay(URL, BODY))

    def test_every_hop_of_a_stage_keeps_the_first_hops_deadline(self):
        first = site.run_deadline('AR-1', 'Event', 60)
        with patch.object(site.time, 'time', return_value=time.time() + 25):
            later = site.run_deadline('AR-1', 'Event', 60)  # The resume job, 25 s later.
            matching = site.run_deadline('AR-1', 'Matching', 40)
        self.assertAlmostEqual(first - later, 25, delta=0.5)
        self.assertAlmostEqual(matching - time.monotonic(), 40, delta=0.5)

    def test_a_job_that_does_not_hand_a_turn_ends_the_runs_deadline(self):
        with patch.object(site, 'is_enabled', return_value=True), site.transport('AR-1'):
            site.run_deadline('AR-1', 'Event', 60)
        self.assertIsNone(self.cache.get(site.key('deadline', 'AR-1')))
        with patch.object(site, 'is_enabled', return_value=True), site.transport('AR-1'):
            site.run_deadline('AR-1', 'Event', 60)
            raise site.Handed('AR-1')
        self.assertIsNotNone(self.cache.get(site.key('deadline', 'AR-1')))

    def test_outside_a_service_run_job_each_deadline_is_fresh(self):
        site.turn_state.set(None)
        site.run_deadline('AR-1', 'Event', 60)
        with patch.object(site.time, 'monotonic', return_value=time.monotonic() + 30):
            self.assertAlmostEqual(site.run_deadline('AR-1', 'Event', 60) - site.time.monotonic(), 60, delta=0.5)
        self.assertEqual(self.cache.values, {})

    def test_a_service_run_job_leaves_frappe_tools_modules_alone(self):
        from frappe_tools.ai import accounts, client
        with patch.object(site, 'is_enabled', return_value=True), site.transport('AR-1'):
            self.assertIs(client.requests, requests)
            self.assertIs(client.accounts, accounts)
            self.assertTrue(site.is_active())

    def test_health_shows_only_this_sites_share_of_the_service(self):
        self.beat.update(consumer='host:1', in_flight=7, queued=9, active={'a.local': 3, 'b.local': 4},
                         counts={'done': 5})
        self.hand()
        with patch('relay_core.permissions.require_access') as access:
            health = site.health()
        access.assert_called_once_with(configure=True)
        self.assertEqual({key: health[key] for key in ('enabled', 'alive', 'site_in_flight', 'service_in_flight',
                                                       'stream_length', 'unacknowledged', 'waiting_turns', 'overdue_turns')},
                         {'enabled': True, 'alive': True, 'site_in_flight': 3, 'service_in_flight': 7,
                          'stream_length': 1, 'unacknowledged': 1, 'waiting_turns': 1, 'overdue_turns': 0})
        self.assertNotIn('b.local', json.dumps(health))

    def test_health_refuses_a_user_who_cannot_configure_relay(self):
        with patch('relay_core.permissions.require_access', side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                site.health()


if __name__ == '__main__':
    unittest.main()
