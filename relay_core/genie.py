"""Forward new customer messages to a Genie hooks communicator, signed like GitHub webhooks."""
import hashlib
import hmac
import ipaddress
import json
import re
import time
from datetime import UTC
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import frappe
import requests
from frappe.utils import get_datetime, get_system_timezone

from relay_core import features
from relay_core.automation.queue import QUEUE, after_message_commit

TIMEOUT = 10
# Seconds after each failed try. Six tries in about 30 minutes.
BACKOFF = (60, 120, 300, 600, 900)
MAX_ATTEMPTS = len(BACKOFF) + 1
RETRIES = 'relay-genie-retries'
SKIPPED_KINDS = ('system', 'reaction')
GROUP_CHAT_TYPES = ('group', 'supergroup', 'channel')
PRIVATE_NETWORKS = (ipaddress.ip_network('100.64.0.0/10'),)
CONTACT_DETAIL = re.compile(r'@|^[\d\s()+.-]+$')


class DeliveryError(Exception):
    """Genie did not accept the message."""


def validate_url(url: str) -> None:
    """Allow https, and http only to a loopback, private or CGNAT (100.64.0.0/10) address."""
    parts = urlsplit(url or '')
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        frappe.throw('Genie URL must be an http or https link without credentials')
    if parts.scheme == 'https' or parts.hostname == 'localhost':
        return
    try:
        address = ipaddress.ip_address(parts.hostname)
    except ValueError:
        address = None
    if not address or not (address.is_loopback or address.is_private or any(address in net for net in PRIVATE_NETWORKS)):
        frappe.throw('Genie URL must use https, except for a loopback, private or 100.64.0.0/10 address')


def validate_settings(doc) -> None:
    if doc.get('genie_url'):
        validate_url(doc.genie_url)
    if doc.get('genie_enabled') and not (doc.get('genie_url') and doc.get('genie_secret')):
        frappe.throw('Set the Genie URL and secret before you turn Genie on')
    for doctype in business_types(doc.get('genie_business_types')):
        if not frappe.db.exists('Relay Contact Type', doctype):
            frappe.throw(f'Genie business type {doctype} is not a Relay business type')


def business_types(text: str | None) -> set[str]:
    return {line.strip() for line in (text or '').splitlines() if line.strip()}


def is_group(doc) -> bool:
    from relay_core.automation.provenance import context_of
    context = context_of(doc)
    return bool(context.get('group_id') or context.get('chat_type') in GROUP_CHAT_TYPES)


def handles(doc) -> bool:
    """True when Genie, not the Relay automation, answers this message."""
    if doc.get('legacy_source') or doc.direction != 'Incoming' or doc.get('message_type') in SKIPPED_KINDS:
        return False
    if not features.is_enabled('genie') or not frappe.db.get_single_value('Relay Settings', 'genie_url'):
        return False
    from relay_core.automation.provenance import context_of
    from relay_core.email_preferences import automatic_allowed
    from relay_core.opt_out import is_keyword
    if is_keyword(doc) or is_group(doc) or not automatic_allowed(context_of(doc)):
        return False
    allowed = business_types(frappe.db.get_single_value('Relay Settings', 'genie_business_types'))
    return not allowed or doc.get('business_doctype') in allowed


def job_id(message: str) -> str:
    return 'relay-genie:' + message


def enqueue(message: str, attempt: int = 1, after_commit: bool = False) -> None:
    frappe.enqueue('relay_core.genie.deliver', message=message, attempt=attempt, queue=QUEUE, timeout=TIMEOUT + 20,
                   job_id=job_id(message), deduplicate=True, enqueue_after_commit=after_commit)


@after_message_commit
def on_message(doc, method=None):
    """Runs in the inbound drain. A Genie problem must never stop the other inbound work."""
    try:
        if handles(doc):
            enqueue(doc.name, after_commit=True)
    except Exception:
        frappe.log_error(title='Relay Genie enqueue failed', message=f'Message {doc.name} was not sent to Genie.')


def utc_stamp(value) -> str:
    local = get_datetime(value).replace(tzinfo=ZoneInfo(get_system_timezone()))
    return local.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def has_media(doc) -> bool:
    data = doc.get('message_data')
    data = json.loads(data) if isinstance(data, str) and data else data
    return bool(isinstance(data, dict) and data.get('media'))


def business(doc) -> dict | None:
    if not (doc.get('business_doctype') and doc.get('business_name')):
        return None
    from relay_core.business_types import type_label
    return {'doctype': doc.business_doctype, 'doctype_label': type_label(doc.business_doctype), 'name': doc.business_name}


def payload(doc) -> dict:
    """The contract body. It carries no phone number, email address or secret."""
    name = frappe.db.get_value('Relay Contact', doc.relay_contact, 'display_name') or ''
    return {'version': 1, 'site': frappe.local.site, 'message_id': doc.name, 'chat': doc.relay_contact,
            'contact': doc.relay_contact, 'contact_name': '' if CONTACT_DETAIL.search(name) else name,
            'channel': frappe.db.get_value('Relay Channel', doc.channel, 'channel'),
            'text': doc.get('transcript') or doc.get('content') or '', 'message_type': doc.get('message_type') or 'text',
            'has_media': has_media(doc), 'business': business(doc), 'timestamp': utc_stamp(doc.get('sent_at') or doc.creation)}


def signature(secret: str, body: bytes) -> str:
    return 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def post(url: str, secret: str, doc) -> None:
    body = json.dumps(payload(doc), ensure_ascii=False, separators=(',', ':')).encode()
    headers = {'Content-Type': 'application/json', 'X-Hub-Signature-256': signature(secret, body), 'X-Relay-Delivery': doc.name}
    try:
        response = requests.post(url, data=body, headers=headers, timeout=TIMEOUT, allow_redirects=False)
    except requests.RequestException as error:
        raise DeliveryError(type(error).__name__) from None
    if not 200 <= response.status_code < 300:
        raise DeliveryError(f'HTTP {response.status_code}')


def deliver(message: str, attempt: int = 1) -> None:
    doc = frappe.get_doc('Relay Message', message)
    if not handles(doc):
        return
    if doc.get('transcript_status') == 'Pending' and attempt < MAX_ATTEMPTS:
        schedule_retry(message, attempt)  # Send the voice note with its transcript.
        return
    settings = frappe.get_single('Relay Settings')
    secret = settings.get_password('genie_secret', raise_exception=False)
    if not secret:
        frappe.log_error(title='Relay Genie delivery failed', message=f'Message {message} was not sent: set the Genie secret.')
        return
    try:
        post(settings.genie_url, secret, doc)
    except DeliveryError as error:
        if attempt < MAX_ATTEMPTS:
            schedule_retry(message, attempt)
            return
        frappe.log_error(title='Relay Genie delivery failed',
                         message=f'Message {message} was not accepted after {attempt} tries: {error}')


def schedule_retry(message: str, attempt: int) -> None:
    frappe.cache.zadd(frappe.cache.make_key(RETRIES), {f'{attempt + 1}:{message}': time.time() + BACKOFF[attempt - 1]})


def retry_due() -> None:
    """Scheduler: queue the retries whose wait has ended. Each retry is taken by one scheduler run only."""
    key = frappe.cache.make_key(RETRIES)
    for member in frappe.cache.zrangebyscore(key, 0, time.time(), start=0, num=100):
        member = member.decode() if isinstance(member, bytes) else member
        if frappe.cache.zrem(key, member):
            attempt, message = member.split(':', 1)
            enqueue(message, int(attempt))
