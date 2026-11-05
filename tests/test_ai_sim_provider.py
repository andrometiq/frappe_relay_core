"""Fake and replay providers over real loopback HTTP, and the Hub callback signature the driver sends."""
import json
import tempfile
import unittest
import urllib.error
import urllib.request

from relay_core.ai.sim import driver, fake_provider
from relay_core.ai.sim.fake_provider import FakeProvider, ReplayStore, Script

PLAN = {'purpose': 'show the October ledger', 'reference': 'erpnext.customer_ledger',
        'fields': ['name', 'company', 'posting_date', 'voucher_type', 'voucher_no', 'debit', 'credit'],
        'arguments': {'filters': {'posting_date': ['between', ['2026-10-01', '2026-10-31']]}, 'limit': 20}}
SCENARIOS = [
    {'id': 'core.ledger.confirm.en', 'skill': 'Sim support', 'turns': [
        {'in': 'Send my October ledger', 'decision': {'reply': '', 'handoff': False, 'reason': '', 'data_question': True,
                                                     'search': PLAN}},
        {'in': 'yes', 'decision': {'reply': 'ok', 'handoff': False, 'reason': '', 'data_question': True}}]},
    {'id': 'core.ledger.other.en', 'skill': 'Sim support', 'turns': [
        {'in': 'yes', 'decision': {'reply': 'other', 'handoff': False, 'reason': '', 'data_question': False}},
        {'in': 'Slow please', 'decision': {'fault': 'timeout', 'data_question': True}}]},
]
TOOLS = [{'type': 'function', 'function': {'name': 'SEARCH', 'parameters': {}}}]


def system(search=None) -> str:
    return 'Rules\nReply language:\nEnglish\nAuthorized search:\n' + json.dumps(search) + '\nSkill:\nSim'


def body(text: str, *, search=None, tools=True, tool_turns=0) -> dict:
    messages = [{'role': 'system', 'content': system(search)},
                {'role': 'user', 'content': [{'type': 'text', 'text': json.dumps({'incoming': text})}]}]
    for index in range(tool_turns):
        messages += [{'role': 'assistant', 'content': '', 'tool_calls': [{'id': f'call_{index + 1}'}]},
                     {'role': 'tool', 'tool_call_id': f'call_{index + 1}', 'content': '{}'}]
    value = {'model': fake_provider.MODEL_ID, 'messages': messages}
    if tools:
        value.update(tools=TOOLS, tool_choice='auto')
    return value


def post(url: str, value: dict) -> tuple[int, dict]:
    request = urllib.request.Request(url + '/chat/completions', data=json.dumps(value).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        with error:
            return error.code, json.loads(error.read())


def decision_of(response: dict) -> dict:
    return json.loads(response['choices'][0]['message']['content'])


class FakeTier(unittest.TestCase):
    def setUp(self):
        self.script = Script(SCENARIOS)
        self.provider = FakeProvider(self.script, port=0)
        self.provider.__enter__()
        self.addCleanup(self.provider.__exit__, None, None, None)

    def test_defaults_are_the_spec_address_and_model(self):
        self.assertEqual(fake_provider.BASE_URL, 'http://127.0.0.1:18090/api/v1')
        self.assertEqual(fake_provider.MODEL_ID, 'relay-sim')

    def test_declared_search_is_a_tool_call_then_the_decision_with_data_question(self):
        self.script.cue('core.ledger.confirm.en', 0)
        status, first = post(self.provider.url, body('Send my October ledger'))
        self.assertEqual(status, 200)
        from frappe_tools.ai.providers import openrouter
        calls = openrouter.tool_calls(first)
        self.assertEqual([call['name'] for call in calls], ['SEARCH'])
        self.assertEqual(json.loads(calls[0]['arguments']), {key: PLAN[key] for key in ('purpose', 'reference', 'arguments')})
        _, second = post(self.provider.url, body('Send my October ledger', tool_turns=1))
        self.assertEqual(decision_of(second), {'reply': 'ok', 'handoff': False, 'reason': '', 'data_question': True})
        self.assertEqual(openrouter.parse_response(type('R', (), {'json': lambda self: second})())[2], 'stop')

    def test_authorized_search_is_read_once_after_confirmation(self):
        self.script.cue('core.ledger.confirm.en', 1)
        _, first = post(self.provider.url, body('yes', search=PLAN))
        self.assertEqual(self.script.calls[-1]['tool_calls'],
                         [{'name': 'SEARCH', 'reference': 'erpnext.customer_ledger', 'filters': PLAN['arguments']['filters'],
                           'limit': 20}])
        _, second = post(self.provider.url, body('yes', search=PLAN, tool_turns=1))
        self.assertEqual(decision_of(second)['reply'], 'ok')

    def test_the_cue_settles_a_repeated_text(self):
        self.script.cue('core.ledger.other.en', 0)
        _, response = post(self.provider.url, body('yes', tools=False))
        self.assertEqual(decision_of(response)['reply'], 'other')
        self.assertTrue(self.script.calls[-1]['text_in_user_turn'])

    def test_unique_text_is_found_without_a_cue(self):
        _, response = post(self.provider.url, body('Send my October ledger', tools=False))
        self.assertTrue(decision_of(response)['data_question'])
        status, _ = post(self.provider.url, body('Unknown text', tools=False))
        self.assertEqual(status, 404)

    def test_matching_scores_the_scenario_skill(self):
        self.script.cue('core.ledger.confirm.en', 0)
        prompt = json.dumps({'targets': [{'id': 'Sim support-001', 'target': 'x'}, {'id': 'Sim payments-001', 'target': 'y'}],
                             'incoming': 'Send my October ledger'})
        value = {'messages': [{'role': 'system', 'content': fake_provider.MATCHING_PREFIX + ' against targets.'},
                              {'role': 'user', 'content': prompt}]}
        _, response = post(self.provider.url, value)
        self.assertEqual(decision_of(response), {'human_request': False, 'decline': False, 'scores': [
            {'id': 'Sim support-001', 'score': 1.0}, {'id': 'Sim payments-001', 'score': 0.0}]})

    def test_timeout_fault(self):
        self.script.cue('core.ledger.other.en', 1)
        status, response = post(self.provider.url, body('Slow please'))
        self.assertEqual(status, 504)
        self.assertIn('timed out', response['error']['message'])


class ReplayTier(unittest.TestCase):
    def test_recorded_response_replays_and_a_miss_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f'{directory}/core.json'
            store = ReplayStore(path, {'erpnext.customer_ledger': 'h1'})
            recorded = fake_provider.content({'reply': 'hi', 'handoff': False, 'reason': '', 'data_question': False}, {})
            store.record(body('hello'), recorded)
            store.save()
            replay = ReplayStore(path, {'erpnext.customer_ledger': 'h1'})
            with FakeProvider(replay, port=0) as provider:
                self.assertEqual(post(provider.url, body('hello')), (200, recorded))
                self.assertEqual(post(provider.url, body('hello again'))[0], 409)
            changed = ReplayStore(path, {'erpnext.customer_ledger': 'h2'})
            self.assertEqual(changed.answer(body('hello'))[0], 409)
            self.assertEqual(len(replay.misses), 1)
            self.assertEqual(replay.calls, [{'key': replay.key(body('hello')), 'tool_calls': []}])


class HubSignature(unittest.TestCase):
    def test_the_driver_signs_what_inbound_accepts(self):
        import time
        from relay_core.inbound import authenticated_payload
        secret, account = 's' * 48, 'relay-sim'
        payload = driver.whatsapp_payload('917000000021', 'hello', 'wamid.sim.1')
        raw = json.dumps({'account': account, 'events': [{'id': 1, 'payload': payload}]}).encode()
        headers = driver.signed(raw, secret, str(int(time.time())))
        accepted = authenticated_payload(raw, headers['X-Relay-Timestamp'], headers['X-Relay-Signature'], secret, account)
        message = accepted['events'][0]['payload']['entry'][0]['changes'][0]['value']['messages'][0]
        self.assertEqual((message['from'], message['text']['body']), ('917000000021', 'hello'))
        with self.assertRaises(ValueError):
            authenticated_payload(raw, headers['X-Relay-Timestamp'], headers['X-Relay-Signature'], 't' * 48, account)


class EchoTests(unittest.TestCase):
    def test_a_careless_model_repeats_every_ticket_message_it_was_given(self):
        tickets = {'note': 'data', 'tickets': [{'ticket': 'TKT-00042', 'status': 'Closed', 'messages': [
            {'from': 'customer', 'text': 'Where is my parcel?'}, {'from': 'our team', 'text': 'It left on Monday.'}]}]}
        value = body('Status?', tool_turns=1)
        value['messages'][-1]['content'] = json.dumps(tickets)
        self.assertEqual(fake_provider.echoed(value), ['TKT-00042 Closed Where is my parcel? It left on Monday.'])


if __name__ == '__main__':
    unittest.main()
