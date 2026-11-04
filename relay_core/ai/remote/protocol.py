"""The signed contract between a site and the bench AI service. Plain Python: the service imports it without Frappe."""
import hashlib
import hmac
import json
import re
import time

STREAM_PREFIX = 'relay:ai:requests:'
GROUP = 'relay-ai-service'
HEARTBEAT = 'relay:ai:service:heartbeat'
HEARTBEAT_SECONDS = 15
MAX_DELIVERIES = 2  # The first delivery and at most one re-queue after a service crash.
MAX_SKEW = 300
ENTRY_LIFETIME = 3600  # A queued entry may wait for capacity or a restart; the site watchdog bounds the run.
MIN_SECRET = 32
SITE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
REQUEST_ID = re.compile(r'[0-9a-f]{64}')


class InvalidSignature(ValueError):
    pass


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str).encode()


def body_key(url: str, body: dict) -> str:
    """The provider request without credentials; the same turn always has the same key."""
    return hashlib.sha256(canonical({'url': url, 'body': body})).hexdigest()


def request_id(site: str, run: str, key: str) -> str:
    return hashlib.sha256(f'{site}\n{run}\n{key}'.encode()).hexdigest()


def stream(site: str) -> str:
    """One stream per site, so a burst from one site cannot hold back the others."""
    return STREAM_PREFIX + site


def sign(secret: str, purpose: str, raw: bytes, timestamp: int | str) -> str:
    """HMAC-SHA256 over `purpose.timestamp.body`; the purpose keeps a stream entry from passing as a callback."""
    if not isinstance(secret, str) or len(secret) < MIN_SECRET:
        raise InvalidSignature('AI service secret is not configured')
    return hmac.new(secret.encode(), f'{purpose}.{timestamp}.'.encode() + raw, hashlib.sha256).hexdigest()


def verify(secret: str, purpose: str, raw: bytes, timestamp, signature, now: float | None = None,
           max_age: int = MAX_SKEW) -> dict:
    """The JSON object `raw`, or InvalidSignature when it is unsigned, tampered or older than `max_age` seconds."""
    try:
        age = abs((time.time() if now is None else now) - int(timestamp))
    except (TypeError, ValueError):
        raise InvalidSignature('Invalid timestamp') from None
    if age > max_age:
        raise InvalidSignature('Expired signature')
    if not isinstance(signature, str) or not hmac.compare_digest(signature, sign(secret, purpose, raw, timestamp)):
        raise InvalidSignature('Invalid signature')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise InvalidSignature('Expected a JSON object')
    return value


def signed_entry(secret: str, site: str, identifier: str, timestamp: int | None = None) -> dict:
    """The stream entry for one request: it names the request; the provider call itself stays on the site."""
    timestamp = int(time.time()) if timestamp is None else timestamp
    raw = canonical({'site': site, 'id': identifier})
    return {'site': site, 'id': identifier, 'ts': str(timestamp), 'sig': sign(secret, 'entry', raw, timestamp)}


def verify_entry(secrets: dict, entry: dict, now: float | None = None) -> tuple[str, str]:
    """(site, request id) of a stream entry signed with that site's own secret."""
    site, identifier = entry.get('site'), entry.get('id')
    if not isinstance(site, str) or not SITE.fullmatch(site) or site not in secrets:
        raise InvalidSignature('Unknown site')
    if not isinstance(identifier, str) or not REQUEST_ID.fullmatch(identifier):
        raise InvalidSignature('Invalid request id')
    verify(secrets[site], 'entry', canonical({'site': site, 'id': identifier}), entry.get('ts'), entry.get('sig'), now, ENTRY_LIFETIME)
    return site, identifier
