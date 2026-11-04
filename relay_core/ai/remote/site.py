"""Site side of the bench AI service.

A run job builds each provider turn as today. With `relay_ai_service` on and the service alive, the turn goes to the
service and the job ends; the service's signed result resumes the run, which replays its earlier turns from stored
results. Credentials stay on the site: the service fetches them per call and never stores them. When the service
is down the turn runs in the worker as before; a request it loses or does not answer in time fails the run, which
hands the conversation to staff.
"""
import json
import time
from contextlib import contextmanager
from contextvars import ContextVar

import frappe
import requests
from redis.exceptions import RedisError

from relay_core.ai.remote import protocol

PREFIX = 'relay-ai-remote'
GRACE_SECONDS = 30
RESULT_SECONDS = 3600
MAX_HOPS = 12  # A turn whose body changes on every replay falls back to the worker instead of looping.
MAX_BODY_CHARS = 4 * 1024 * 1024
HEADER_OPTIONS = {'temperature': 0, 'max_tokens': 1, 'json_mode': False}
ERRORS = {'timeout': requests.Timeout, 'unavailable': requests.ConnectionError, 'lost': requests.ConnectionError}

turn_state = ContextVar('relay_ai_remote_turn', default=None)


class Handed(BaseException):
    """The provider turn waits in the AI service. A BaseException, so provider error handling never treats it as a
    failed call; `transport` ends the job quietly."""


def is_enabled() -> bool:
    return bool(frappe.conf.get('relay_ai_service')) and len(secret()) >= protocol.MIN_SECRET


def secret() -> str:
    return frappe.conf.get('relay_ai_service_secret') or ''


def queue_connection():
    from frappe.utils.background_jobs import get_redis_conn
    return get_redis_conn()


def is_service_up() -> bool:
    try:
        beat = json.loads(queue_connection().get(protocol.HEARTBEAT) or '{}')
    except (RedisError, ValueError):
        return False
    return time.time() - float(beat.get('ts') or 0) < protocol.HEARTBEAT_SECONDS


def key(*parts) -> bytes:
    """A site-scoped cache key; RedisWrapper's own `exists` must get it with shared=True."""
    return frappe.cache.make_key(':'.join((PREFIX, *parts)))


def on_handed(undo) -> None:
    """Register work to undo when this job hands its turn over, such as a counted attempt or reserved spend."""
    state = turn_state.get()
    if state is not None:
        state['undo'].append(undo)


def settled() -> None:
    """The turns so far are final: a later hand-over in this job must not undo their attempt or spend."""
    state = turn_state.get()
    if state is not None:
        state['undo'].clear()


def is_waiting(run: str) -> bool:
    return bool(frappe.cache.exists(key('waiting', run), shared=True))


@contextmanager
def transport(run: str):
    """Within one run job, send provider turns through the AI service. Swaps frappe_tools' module seams, which a
    `transport` hook in frappe_tools' client should replace."""
    if not is_enabled():
        yield
        return
    from frappe_tools.ai import client
    state = {'run': run, 'undo': [], 'account': None, 'handed': False}
    token = turn_state.set(state)
    seams = {'requests': client.requests, 'accounts': client.accounts, '_log_attempt': client._log_attempt}
    client.requests, client.accounts = Requests(state, seams['requests']), Accounts(state, seams['accounts'])
    client._log_attempt = lambda *args: None if state['handed'] else seams['_log_attempt'](*args)
    try:
        yield
    except Handed:
        release(state)
    finally:
        for name, value in seams.items():
            setattr(client, name, value)
        turn_state.reset(token)


def release(state: dict) -> None:
    frappe.db.rollback()
    for undo in reversed(state['undo']):
        undo()
    frappe.db.commit()


class Requests:
    """`requests` as frappe_tools' client sees it in a run job; only `post` changes."""

    def __init__(self, state: dict, module):
        self.state, self.module = state, module

    def __getattr__(self, name):
        return getattr(self.module, name)

    def post(self, url, *, headers, json, timeout, stream=False):
        return send(self.state, url, headers, json, timeout)


class Accounts:
    """Records which account a turn uses, so the service can fetch its current credentials."""

    def __init__(self, state: dict, module):
        self.state, self.module = state, module

    def __getattr__(self, name):
        return getattr(self.module, name)

    def credentials(self, account, timeout=120):
        self.state['account'] = account.name if hasattr(account, 'name') else None
        return self.module.credentials(account, timeout)


def send(state: dict, url: str, headers: dict, body: dict, timeout: float):
    run, turn = state['run'], protocol.body_key(url, body)
    stored = frappe.cache.get(key('result', run, turn))
    if stored:
        return response(json.loads(stored))
    hops = frappe.cache.incr(key('hops', run))
    frappe.cache.expire(key('hops', run), RESULT_SECONDS)
    if not state['account'] or hops > MAX_HOPS or not is_service_up():
        return requests.post(url, headers=headers, json=body, timeout=timeout, stream=True)
    hand(run, turn, state['account'], url, body, timeout)
    state['handed'] = True
    raise Handed(run)


def hand(run: str, turn: str, account: str, url: str, body: dict, timeout: float) -> None:
    """Queue the turn once; a replay of a turn already in the service only ends its job."""
    site = frappe.local.site
    identifier = protocol.request_id(site, run, turn)
    deadline = time.time() + float(timeout) + GRACE_SECONDS
    spec = {'run': run, 'turn': turn, 'account': account, 'url': url, 'body': body, 'timeout': float(timeout),
            'deadline': deadline}
    lifetime = int(timeout) + GRACE_SECONDS + 60
    frappe.cache.set(key('waiting', run), identifier, ex=lifetime)
    if not frappe.cache.set(key('spec', identifier), json.dumps(spec), nx=True, ex=RESULT_SECONDS):
        return
    frappe.cache.zadd(key('inflight'), {identifier: deadline})
    queue_connection().xadd(protocol.STREAM, protocol.signed_entry(secret(), site, identifier),
                            maxlen=100000, approximate=True)


def response(result: dict) -> requests.Response:
    """A stored service result as the provider's own HTTP response, or the network error the service saw."""
    if result.get('error'):
        raise ERRORS.get(result['error'], requests.ConnectionError)(result.get('detail') or 'AI service error')
    value = requests.Response()
    value.status_code, value.encoding = int(result['status']), 'utf-8'
    value._content, value._content_consumed = result['body'].encode(), True
    return value


def spec_for(identifier) -> dict | None:
    if not isinstance(identifier, str) or not protocol.REQUEST_ID.fullmatch(identifier):
        frappe.throw('Invalid AI service request', frappe.ValidationError)
    raw = frappe.cache.get(key('spec', identifier))
    return json.loads(raw) if raw else None


def authenticated() -> dict:
    if not is_enabled():
        frappe.throw('The AI service is off on this site', frappe.PermissionError)
    try:
        return protocol.verify(secret(), frappe.request.get_data(), frappe.request.headers.get('X-Relay-AI-Timestamp'),
                               frappe.request.headers.get('X-Relay-AI-Signature'))
    except (protocol.InvalidSignature, ValueError):
        frappe.throw('Invalid AI service request', frappe.PermissionError)


@frappe.whitelist(allow_guest=True, methods=['POST'])
def request(**_ignored) -> dict:
    """The provider request with credentials current now; frappe_tools refreshes a ChatGPT login token."""
    spec = spec_for(authenticated().get('id'))
    if not spec or frappe.cache.exists(key('result', spec['run'], spec['turn']), shared=True):
        return {'status': 'gone'}
    from frappe_tools.ai import accounts, client
    from relay_core.test_mode import ensure_allowed
    ensure_allowed(spec['url'])
    account = frappe.get_doc('AI Provider Account', spec['account'])
    credentials = accounts.credentials(account, int(spec['timeout']))
    headers = client.PROVIDERS[account.provider].build_turn(credentials, spec['body'].get('model'), '', [], None,
                                                            HEADER_OPTIONS)[1]
    return {'status': 'ready', 'url': spec['url'], 'headers': headers, 'body': spec['body'],
            'timeout': spec['timeout'], 'deadline': spec['deadline']}


@frappe.whitelist(allow_guest=True, methods=['POST'])
def result(**_ignored) -> dict:
    """Store the first result of a request and resume its run; a repeated result changes nothing."""
    value = authenticated()
    spec = spec_for(value.get('id'))
    if not spec:
        return {'status': 'gone'}
    if value.get('error') in ERRORS:
        outcome = {'error': value['error'], 'detail': str(value.get('detail') or '')[:300]}
    elif type(value.get('status')) is int and isinstance(value.get('body'), str) and len(value['body']) <= MAX_BODY_CHARS:
        outcome = {'status': value['status'], 'body': value['body']}
    else:
        frappe.throw('Invalid AI service result', frappe.ValidationError)
    return {'status': 'stored' if store(value['id'], spec, outcome) else 'duplicate'}


def store(identifier: str, spec: dict, outcome: dict) -> bool:
    if not frappe.cache.set(key('result', spec['run'], spec['turn']), json.dumps(outcome), nx=True, ex=RESULT_SECONDS):
        return False
    frappe.cache.zrem(key('inflight'), identifier)
    frappe.cache.delete(key('waiting', spec['run']))
    from relay_core.automation.queue import QUEUE
    actor = frappe.session.user
    frappe.set_user('Administrator')  # As the scheduler's recovery queues runs; each run acts as its execution user.
    try:
        frappe.enqueue('relay_core.automation.service.process', name=spec['run'], queue=QUEUE,
                       job_id='relay-ai-resume-' + identifier, deduplicate=True)
    finally:
        frappe.set_user(actor)
    return True


def expire_overdue(now: float | None = None) -> int:
    """Fail requests the service has not answered by their deadline; their runs resume and hand off to staff."""
    if not is_enabled():
        return 0
    overdue = frappe.cache.zrangebyscore(key('inflight'), 0, time.time() if now is None else now, start=0, num=50)
    for identifier in overdue:
        identifier = identifier.decode() if isinstance(identifier, bytes) else identifier
        spec = spec_for(identifier)
        if spec:
            store(identifier, spec, {'error': 'timeout', 'detail': 'The AI service did not answer in time'})
        else:
            frappe.cache.zrem(key('inflight'), identifier)
    return len(overdue)
