"""Site side of the bench AI service.

A run job builds each provider turn with frappe_tools (see `turns`). With `relay_ai_service` on and the service
alive, `post` hands the turn to the service and the job ends; the service's signed result resumes the run, which
replays its earlier turns from stored results. Credentials stay on the site: the service fetches them per call and
never stores them. When the service is down the turn runs in the worker as before; a request it loses or does not
answer in time fails the run, which hands the conversation to staff.
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


def is_active() -> bool:
    """True inside a run job of a site with the service on: `turns` then sends provider turns through `post`."""
    return turn_state.get() is not None


@contextmanager
def transport(run: str):
    """Within one run job, send provider turns through the AI service. A job that does not hand a turn over ends the
    run's time budget, so a later attempt starts a fresh one."""
    if not is_enabled():
        yield
        return
    state = {'run': run, 'undo': []}
    token = turn_state.set(state)
    try:
        yield
    except Handed:
        release(state)
    else:
        frappe.cache.delete(key('deadline', run))
    finally:
        turn_state.reset(token)


def release(state: dict) -> None:
    frappe.db.rollback()
    for undo in reversed(state['undo']):
        undo()
    frappe.db.commit()


def run_deadline(run: str, stage: str, seconds: float) -> float:
    """The time.monotonic() deadline of `stage` of `run`; in a service run job every job hop of the stage keeps the
    first hop's deadline, so waiting for the service counts against the stage's time budget. The run lease makes this
    read-modify-write safe."""
    if not is_active():
        return time.monotonic() + seconds
    deadlines = json.loads(frappe.cache.get(key('deadline', run)) or '{}')
    if stage not in deadlines:
        deadlines[stage] = time.time() + seconds
        frappe.cache.set(key('deadline', run), json.dumps(deadlines), ex=RESULT_SECONDS)
    return time.monotonic() + deadlines[stage] - time.time()


def post(account: str, url: str, headers: dict, body: dict, timeout: float) -> tuple[requests.Response, int | None]:
    """The provider answer to a turn of the active run and the provider latency the service measured: a stored result,
    else the turn goes to a live service (raising Handed), else it is posted from this worker."""
    run, turn = turn_state.get()['run'], protocol.body_key(url, body)
    stored = frappe.cache.get(key('result', run, turn))
    if stored:
        result = json.loads(stored)
        return response(result), result.get('latency_ms')
    hops = frappe.cache.incr(key('hops', run))
    frappe.cache.expire(key('hops', run), RESULT_SECONDS)
    if hops > MAX_HOPS or not is_service_up():
        return requests.post(url, headers=headers, json=body, timeout=timeout, stream=True), None
    hand(run, turn, account, url, body, timeout)
    raise Handed(run)


def is_first_replay(url: str, body: dict) -> bool:
    """Whether to log a replayed turn: every later hop replays it again, so only the first hop whose work commits
    logs it."""
    name = key('logged', turn_state.get()['run'], protocol.body_key(url, body))
    if frappe.cache.get(name):
        return False
    frappe.db.after_commit.add(lambda: frappe.cache.set(name, 1, ex=RESULT_SECONDS))
    return True


def hand(run: str, turn: str, account: str, url: str, body: dict, timeout: float) -> None:
    """Queue the turn once; a replay of a turn already in the service only ends its job."""
    site = frappe.local.site
    identifier = protocol.request_id(site, run, turn)
    deadline = time.time() + float(timeout)  # Within the run's time budget; a later answer is of no use.
    spec = {'run': run, 'turn': turn, 'account': account, 'url': url, 'body': body, 'timeout': float(timeout),
            'deadline': deadline}
    lifetime = int(timeout) + GRACE_SECONDS + 60
    frappe.cache.set(key('waiting', run), identifier, ex=lifetime)
    if not frappe.cache.set(key('spec', identifier), json.dumps(spec), nx=True, ex=RESULT_SECONDS):
        return
    frappe.cache.zadd(key('inflight'), {identifier: deadline})
    queue_connection().xadd(protocol.stream(site), protocol.signed_entry(secret(), site, identifier),
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


def authenticated(purpose: str) -> dict:
    if not is_enabled():
        frappe.throw('The AI service is off on this site', frappe.PermissionError)
    try:
        return protocol.verify(secret(), purpose, frappe.request.get_data(),
                               frappe.request.headers.get('X-Relay-AI-Timestamp'),
                               frappe.request.headers.get('X-Relay-AI-Signature'))
    except (protocol.InvalidSignature, ValueError):
        frappe.throw('Invalid AI service request', frappe.PermissionError)


@frappe.whitelist(allow_guest=True, methods=['POST'])
def request(**_ignored) -> dict:
    """The provider request with credentials current now; frappe_tools refreshes a ChatGPT login token."""
    spec = spec_for(authenticated('request').get('id'))
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
    value = authenticated('result')
    spec = spec_for(value.get('id'))
    if not spec:
        return {'status': 'gone'}
    if value.get('error') in ERRORS:
        outcome = {'error': value['error'], 'detail': str(value.get('detail') or '')[:300]}
    elif type(value.get('status')) is int and isinstance(value.get('body'), str) and len(value['body']) <= MAX_BODY_CHARS:
        outcome = {'status': value['status'], 'body': value['body']}
        if type(value.get('latency_ms')) is int and value['latency_ms'] >= 0:
            outcome['latency_ms'] = value['latency_ms']
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
                       job_id='relay-ai-resume-' + identifier, deduplicate=True, at_front=True)
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

