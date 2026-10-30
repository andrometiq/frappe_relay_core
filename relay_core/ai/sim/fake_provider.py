"""Loopback OpenRouter chat-completions stand-in: scripted decisions (fake tier) or recorded responses (replay tier)."""
import hashlib
import json
import pathlib
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = '127.0.0.1', 18090
BASE_URL = f'http://{HOST}:{PORT}/api/v1'
MODEL_ID = 'relay-sim'
CHAT_PATH = '/api/v1/chat/completions'
MATCHING_PREFIX = 'Classify the incoming message'
AUTHORIZED = re.compile(r'\nAuthorized search:\n(.*?)\nSkill:\n', re.DOTALL)
CONTENT_ONLY = ('search', 'calls', 'execute', 'match', 'json', 'fault')


def user_text(body: dict) -> str:
    """Text of the first user message, whether a string or OpenAI content parts."""
    message = next((row for row in body.get('messages', []) if row.get('role') == 'user'), {})
    content = message.get('content') or ''
    if isinstance(content, list):
        return ''.join(part.get('text', '') for part in content if isinstance(part, dict))
    return content


def system_text(body: dict) -> str:
    return next((row.get('content') or '' for row in body.get('messages', []) if row.get('role') == 'system'), '')


def incoming(body: dict) -> str:
    """The customer text Core put in the user turn: its JSON `incoming`, else the raw text."""
    text = user_text(body)
    try:
        value = json.loads(text)
    except ValueError:
        return text
    return value.get('incoming', text) if isinstance(value, dict) else text


def completion(message: dict, body: dict) -> dict:
    prompt = len(json.dumps(body.get('messages', []), ensure_ascii=False)) // 4
    output = len(json.dumps(message, ensure_ascii=False)) // 4
    reason = 'tool_calls' if message.get('tool_calls') else 'stop'
    return {'id': 'sim-' + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16],
            'object': 'chat.completion', 'model': MODEL_ID,
            'choices': [{'index': 0, 'message': message, 'finish_reason': reason}],
            'usage': {'prompt_tokens': prompt, 'completion_tokens': output, 'total_tokens': prompt + output}}


def content(value: dict, body: dict) -> dict:
    return completion({'role': 'assistant', 'content': json.dumps(value, ensure_ascii=False)}, body)


class Script:
    """Scripted turns keyed by (scenario id, turn index). The driver cues the turn it is about to post."""

    def __init__(self, scenarios: list[dict]):
        self.turns = {(row['id'], index): turn for row in scenarios for index, turn in enumerate(row['turns']) if 'in' in turn}
        self.skills = {row['id']: row.get('skill', '') for row in scenarios}
        self.cue_key = None
        self.calls = []
        self.lock = threading.Lock()

    def cue(self, scenario_id: str, turn: int) -> None:
        with self.lock:
            self.cue_key = (scenario_id, turn)

    def lookup(self, text: str) -> tuple:
        """The turn whose text is in the user turn; the cue settles repeated texts such as a bare 'yes'."""
        found = [key for key, turn in self.turns.items() if turn['in'].strip() == text.strip()]
        if self.cue_key in found or not found:
            return self.cue_key
        return found[0] if len(found) == 1 else self.cue_key

    def answer(self, body: dict) -> tuple[int, dict]:
        system = system_text(body)
        with self.lock:
            key = self.lookup(incoming(body))
        turn = self.turns.get(key)
        if turn is None:
            return 404, {'error': {'message': 'No scripted turn for this request', 'code': 404}}
        decision = turn.get('decision') or {}
        if decision.get('fault') == 'timeout':
            return 504, {'error': {'message': 'Upstream timed out', 'code': 504}}
        if system.startswith(MATCHING_PREFIX):
            kind, response = 'match', content(self.match(key, decision, body), body)
        elif body.get('tools') or '\nReply language:\n' in system:
            kind, response = 'decision', self.decide(decision, body, system)
        else:
            kind, response = 'json', content(decision.get('json', {'lines': []}), body)
        with self.lock:
            self.calls.append({'scenario': key[0], 'turn': key[1], 'kind': kind,
                               'tool_calls': tool_calls(response), 'text_in_user_turn': turn['in'] in user_text(body)})
        return 200, response

    def match(self, key: tuple, decision: dict, body: dict) -> dict:
        if 'match' in decision:
            return decision['match']
        try:
            targets = json.loads(user_text(body)).get('targets', [])
        except (ValueError, AttributeError):
            targets = []
        skill = self.skills.get(key[0], '')
        scores = [{'id': row['id'], 'score': 1.0 if row['id'] == skill or row['id'].startswith(skill + '-') else 0.0}
                  for row in targets if isinstance(row, dict) and 'id' in row]
        return {'human_request': False, 'decline': False, 'scores': scores}

    def decide(self, decision: dict, body: dict, system: str) -> dict:
        """One planned tool call per round while tools are allowed, then the decision JSON."""
        planned = planned_calls(decision, system)
        done = sum(1 for row in body.get('messages', []) if row.get('role') == 'tool')
        if done < len(planned) and body.get('tools') and body.get('tool_choice') != 'none':
            name, arguments = planned[done]
            call = {'id': f'call_{done + 1}', 'type': 'function',
                    'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}
            return completion({'role': 'assistant', 'content': '', 'tool_calls': [call]}, body)
        value = {key: item for key, item in decision.items() if key not in CONTENT_ONLY}
        value.setdefault('data_question', bool(planned))
        for key, default in (('reply', ''), ('handoff', False), ('reason', '')):
            value.setdefault(key, default)
        return content(value, body)


def planned_calls(decision: dict, system: str) -> list[tuple[str, dict]]:
    """Explicit `calls`, else the authorized search Core offers, else the declared search, then EXECUTE steps."""
    if 'calls' in decision:
        return [(row['name'], row['arguments']) for row in decision['calls']]
    calls = []
    found = AUTHORIZED.search(system)
    authorized = json.loads(found.group(1)) if found else None
    search = authorized or decision.get('search')
    if search:
        calls.append(('SEARCH', {key: search[key] for key in ('purpose', 'reference', 'arguments')}))
    calls.extend(('EXECUTE', {'action': row['action'], 'parameters': row['parameters']}) for row in decision.get('execute', []))
    return calls


def tool_calls(response: dict) -> list[dict]:
    message = (response.get('choices') or [{}])[0].get('message') or {}
    result = []
    for call in message.get('tool_calls') or []:
        arguments = json.loads(call['function']['arguments'])
        inner = arguments.get('arguments') or {}
        result.append({'name': call['function']['name'], 'reference': arguments.get('reference') or arguments.get('action'),
                       'filters': inner.get('filters'), 'limit': inner.get('limit')})
    return result


class ReplayStore:
    """Recorded responses keyed by sha256 of system, user turn, tools and capability hashes. A miss fails."""

    def __init__(self, path: pathlib.Path, capability_hashes: dict[str, str]):
        self.path = pathlib.Path(path)
        self.hashes = capability_hashes
        self.records = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.misses = []
        self.calls = []
        self.lock = threading.Lock()

    def key(self, body: dict) -> str:
        value = [system_text(body), user_text(body), body.get('tools') or [], sorted(self.hashes.items()),
                 [row for row in body.get('messages', []) if row.get('role') in ('assistant', 'tool')]]
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def record(self, body: dict, response: dict) -> None:
        with self.lock:
            self.records[self.key(body)] = response

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.records, sort_keys=True, ensure_ascii=False, indent=1))

    def answer(self, body: dict) -> tuple[int, dict]:
        key = self.key(body)
        with self.lock:
            response = self.records.get(key)
            if response:
                self.calls.append({'key': key, 'tool_calls': tool_calls(response)})
            else:
                self.misses.append(key)
        if response is None:
            return 409, {'error': {'message': 'Replay miss', 'code': 409}}
        return 200, response


class FakeProvider:
    """`with FakeProvider(script) as provider:` serves `script.answer` on 127.0.0.1:18090 in a thread."""

    def __init__(self, answers, host: str = HOST, port: int = PORT):
        self.answers = answers
        self.server = ThreadingHTTPServer((host, port), handler(answers))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f'http://{host}:{port}/api/v1'

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def handler(answers):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != CHAT_PATH:
                return self.reply(404, {'error': {'message': 'Not found', 'code': 404}})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)))
            except ValueError:
                return self.reply(400, {'error': {'message': 'Invalid JSON', 'code': 400}})
            self.reply(*answers.answer(body))

        def reply(self, status: int, value: dict):
            raw = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    return Handler
