"""Provider turns of a run job with the AI service on.

frappe_tools' client posts with `requests` itself, so it has no seam for another transport. Relay builds, parses and
logs each turn with frappe_tools' own public functions and sends it through `site.post`, which answers from a stored
service result, hands the turn to the service, or posts from this worker. Outside a service run job every call goes
to frappe_tools unchanged.
"""
import time

import frappe
import requests
from frappe_tools.ai import accounts, agent, client
from frappe_tools.ai.providers import ProviderError, codex, error_message
from frappe_tools.utils import llm
from rq.timeouts import JobTimeoutException

from relay_core.ai.remote import site


class AgentRun(agent.AgentRun):
    """frappe_tools' tool loop, whose turns go through `try_model` in a service run job."""

    def run_route(self, account, model: str, prompts: tuple, options: dict, context: dict) -> dict:
        if not site.is_active():
            return super().run_route(account, model, prompts, options, context)
        system, user, schema = prompts
        adapter = client.PROVIDERS[account.get('provider')]
        messages = [adapter.user_message(user, [])]
        definitions = [tool.definition for tool in self.tools.values()]
        while True:
            final = self.calls_left <= 0

            def build(adapter, credentials, model):
                return adapter.build_turn(credentials, model, system, messages, schema, options, definitions, final)

            outcome = try_model(account, model, build, options, context, self.deadline)
            calls = outcome['result']['tool_calls'] if outcome['ok'] else []
            if not calls:
                return outcome
            if final:
                return {'ok': False, 'retryable': False, 'error': frappe._('Model called tools after the limit')}
            messages.extend(adapter.continuation(outcome['result']['response'], self.run_tools(calls)))


def try_model(account, model: str, build, options: dict, context: dict, deadline: float | None = None) -> dict:
    """`client.try_model`, with each attempt sent through `site.post` in a service run job."""
    if not site.is_active():
        return client.try_model(account, model, build, options, context, deadline)
    for number in range(1, options['attempts'] + 1):
        outcome = attempt(account, model, build, client.bounded_options(options, deadline), context, deadline)
        if outcome['ok']:
            return outcome
        if deadline is not None and time.monotonic() >= deadline:
            raise client.DeadlineReached(frappe._('The AI time budget ended during the request'))
        if not outcome['retryable']:
            return outcome
        if number < options['attempts']:
            time.sleep(min(2 * number, 8))
    return outcome


def attempt(account, model: str, build, options: dict, context: dict, deadline: float | None) -> dict:
    """One logged attempt; a turn handed to the service is logged once, when a later hop replays its result."""
    started, state, handed = time.monotonic(), client.new_state(), False
    try:
        execute(account, model, build, options, state, deadline)
        state.update(status='Success', error=None)
    except site.Handed:
        handed = True
        raise
    except JobTimeoutException:
        state.update(status='Timeout', error=frappe._('AI job timed out'))
        raise
    except client.DeadlineReached as exc:
        state.update(status='Timeout', error=str(exc))
        raise
    except Exception as exc:
        client.record_failure(state, exc)
    finally:
        replayed = state.get('latency_ms') is not None
        latency = state['latency_ms'] if replayed else int((time.monotonic() - started) * 1000)
        if not handed and (not replayed or site.is_first_replay(state['url'], state['body'])):
            log(state, account, model, latency, context)
    if state['status'] != 'Success':
        return {'ok': False, 'error': state['error'], 'retryable': state['retryable']}
    return {'ok': True, 'result': {'data': state['data'], 'usage': state['usage'],
            'model': f"{account.get('provider')}/{model}", 'latency_ms': latency,
            'finish_reason': state['finish_reason'], 'tool_calls': state['calls'], 'response': state['result']}}


def execute(account, model: str, build, options: dict, state: dict, deadline: float | None) -> None:
    """`client.execute` with `site.post` as the transport; a replayed turn records the service's provider latency."""
    credentials = accounts.credentials(account, client.bounded_options(options, deadline)['timeout'])
    state['secrets'] = [credentials.get(field) for field in ('api_key', 'access_token', 'refresh_token')]
    adapter = client.PROVIDERS[account.get('provider')]
    state['url'], headers, state['body'] = build(adapter, credentials, model)
    is_stream = adapter is codex
    response, state['latency_ms'] = site.post(account.name, state['url'], headers, state['body'],
                                              client.bounded_options(options, deadline)['timeout'])
    try:
        state['http_status'] = response.status_code
        if not is_stream:
            response._content = client.read_body(response, deadline)
        if response.status_code >= 400:
            try:
                state['result'] = response.json()
            except ValueError:
                text = llm.redact_secrets(response.text or '', state['secrets'])
                state['result'] = {'non_json_response': text[:4000]}
            message = error_message(state['result']) or frappe._('Provider returned HTTP {0}').format(response.status_code)
            raise ProviderError(message, response.status_code)
        parsed = codex.parse_response(response, deadline) if is_stream else adapter.parse_response(response)
        state['raw_text'], state['usage'], state['finish_reason'], state['result'] = parsed
        if deadline is not None and time.monotonic() >= deadline:
            raise requests.Timeout(frappe._('The AI answer arrived after the time budget ended'))
        state['calls'] = adapter.tool_calls(state['result']) if state['body'].get('tools') else []
        state['data'] = llm.safe_json_loads(state['raw_text'])
        if state['data'] is None and not state['calls'] and options.get('require_json', True):
            raise ValueError(frappe._('could not parse JSON from model response. Raw begins: {0}').format(
                llm.redact_secrets(state['raw_text'], state['secrets'])[:200] or frappe._('<empty response>')))
    finally:
        response.close()


def log(state: dict, account, model: str, latency: int, context: dict) -> None:
    llm.log_call(model=f"{account.get('provider')}/{model}", provider=account.get('provider'), status=state['status'],
                 http_status=state['http_status'], latency_ms=latency, usage=state['usage'], body=state['body'],
                 result=state['result'], error=state['error'], raw_text=state['raw_text'],
                 finish_reason=state['finish_reason'], secrets=state['secrets'], **context)
