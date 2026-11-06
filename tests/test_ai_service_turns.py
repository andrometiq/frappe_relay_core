"""Provider turns of a service run job: frappe_tools builds and parses them, Relay's seam carries them."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from frappe_tools.ai import agent, client

from relay_core.ai.remote import site, turns
from test_ai_service_protocol import BODY, SSE, URL

CONTEXT = dict(extraction=None, target_doctype=None, phase=None, reference_doctype=None, reference_name=None, run_id=None)
OPTIONS = {'timeout': 20, 'attempts': 1, 'temperature': 0, 'max_tokens': 100}


class Account(dict):
    name = 'Load Codex'


def answer(status=200, text=SSE):
    value = requests.Response()
    value.status_code, value.encoding, value._content, value._content_consumed = status, 'utf-8', text.encode(), True
    return value


class Turns(unittest.TestCase):
    def setUp(self):
        self.account = Account(provider='OpenAI Codex')
        token = site.turn_state.set({'run': 'AR-1', 'undo': []})
        self.addCleanup(site.turn_state.reset, token)
        for target, name, value in ((turns, 'frappe', SimpleNamespace(_=lambda text: text)),
                                    (turns.accounts, 'credentials', Mock(return_value={'access_token': 'token-1'})),
                                    (turns.llm, 'log_call', Mock()),
                                    (site, 'is_first_replay', Mock(return_value=True))):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.log = turns.llm.log_call

    def build(self, adapter, credentials, model):
        return URL, {'Authorization': 'Bearer ' + credentials['access_token']}, BODY

    def test_a_replayed_turn_logs_the_provider_latency_the_service_measured(self):
        with patch.object(site, 'post', return_value=(answer(), 3210)) as post:
            outcome = turns.try_model(self.account, 'gpt-test', self.build, OPTIONS, CONTEXT)
        site.is_first_replay.assert_called_once_with(URL, BODY)
        post.assert_called_once_with('Load Codex', URL, {'Authorization': 'Bearer token-1'}, BODY, 20)
        self.assertEqual((outcome['ok'], outcome['result']['data'], outcome['result']['latency_ms']), (True, {'ok': True}, 3210))
        self.assertEqual((self.log.call_args.kwargs['status'], self.log.call_args.kwargs['latency_ms']), ('Success', 3210))
        self.assertEqual(self.log.call_args.kwargs['secrets'], [None, 'token-1', None])

    def test_a_turn_an_earlier_hop_logged_is_not_logged_again(self):
        site.is_first_replay.return_value = False
        with patch.object(site, 'post', return_value=(answer(), 3210)):
            self.assertTrue(turns.try_model(self.account, 'gpt-test', self.build, OPTIONS, CONTEXT)['ok'])
        self.log.assert_not_called()

    def test_a_turn_sent_from_the_worker_is_always_logged(self):
        with patch.object(site, 'post', return_value=(answer(), None)):
            turns.try_model(self.account, 'gpt-test', self.build, OPTIONS, CONTEXT)
        site.is_first_replay.assert_not_called()
        self.log.assert_called_once()

    def test_a_handed_turn_ends_the_job_without_a_call_log(self):
        with patch.object(site, 'post', side_effect=site.Handed('AR-1')), self.assertRaises(site.Handed):
            turns.try_model(self.account, 'gpt-test', self.build, OPTIONS, CONTEXT)
        self.log.assert_not_called()

    def test_a_provider_error_is_logged_and_failed_like_frappe_tools_does(self):
        with patch.object(site, 'post', return_value=(answer(429, '{"error":{"message":"slow down"}}'), 40)):
            outcome = turns.try_model(self.account, 'gpt-test', self.build, OPTIONS, CONTEXT)
        self.assertEqual((outcome['ok'], outcome['retryable']), (False, True))
        self.assertIn('slow down', outcome['error'])
        self.assertEqual((self.log.call_args.kwargs['status'], self.log.call_args.kwargs['http_status']), ('Error', 429))

    def test_a_truncated_answer_fails_with_frappe_tools_hint(self):
        state = client.new_state()
        with patch.object(site, 'post', return_value=(answer(), 40)), \
                patch.object(turns.codex, 'parse_response', return_value=('{"ok":', {}, 'length', {})):
            outcome = turns.try_model(self.account, 'gpt-test', self.build, OPTIONS, CONTEXT)
        state.update(raw_text='{"ok":', finish_reason='length')
        self.assertEqual((outcome['ok'], outcome['error']), (False, client._json_error(state)))
        self.assertIn('Max Tokens', outcome['error'])

    def test_a_service_timeout_fails_the_turn_as_a_timeout(self):
        with patch.object(site, 'post', side_effect=requests.Timeout('The AI service did not answer in time')):
            outcome = turns.try_model(self.account, 'gpt-test', self.build, OPTIONS, CONTEXT)
        self.assertFalse(outcome['ok'])
        self.assertEqual(self.log.call_args.kwargs['status'], 'Timeout')

    def test_outside_a_service_run_job_frappe_tools_runs_the_turn(self):
        site.turn_state.set(None)
        with patch.object(client, 'try_model', return_value={'ok': True}) as original, patch.object(site, 'post') as post:
            self.assertEqual(turns.try_model(self.account, 'gpt-test', self.build, OPTIONS, CONTEXT, 9.0), {'ok': True})
        original.assert_called_once_with(self.account, 'gpt-test', self.build, OPTIONS, CONTEXT, 9.0)
        post.assert_not_called()
        with patch.object(agent.AgentRun, 'run_route', return_value={'ok': True}) as route:
            turns.AgentRun([], [], 9.0).run_route(self.account, 'gpt-test', ('s', 'u', None), OPTIONS, CONTEXT)
        route.assert_called_once()

    def test_a_tool_call_turn_runs_the_tool_and_sends_the_next_turn(self):
        provider = SimpleNamespace(user_message=lambda text, images: {'user': text},
                                   build_turn=lambda *args: (URL, {}, {'messages': list(args[3])}),
                                   continuation=lambda response, outputs: [{'tool': output} for call, output in outputs])
        outcomes = [{'ok': True, 'result': {'tool_calls': [{'name': 'SEARCH', 'arguments': '{}'}], 'response': {}}},
                    {'ok': True, 'result': {'tool_calls': [], 'data': {'reply': 'Done'}}}]
        tool = agent.Tool('SEARCH', 'Search', {'type': 'object'}, lambda: {'rows': 1})
        bodies = []

        def model(account, model_id, build, options, context, deadline):
            bodies.append(build(provider, {}, model_id)[2])
            return outcomes.pop(0)
        with patch.dict(client.PROVIDERS, {'OpenAI Codex': provider}), patch.object(turns, 'try_model', side_effect=model):
            outcome = turns.AgentRun([tool], [], 9e9, max_tool_calls=2).run_route(self.account, 'gpt-test',
                                                                                    ('s', 'u', None), OPTIONS, CONTEXT)
        self.assertEqual(outcome['result']['data'], {'reply': 'Done'})
        self.assertEqual(bodies, [{'messages': [{'user': 'u'}]}, {'messages': [{'user': 'u'}, {'tool': '{"rows": 1}'}]}])


if __name__ == '__main__':
    unittest.main()
