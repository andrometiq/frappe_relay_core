"""Forward new customer messages to a Genie hooks communicator, signed like GitHub webhooks.

Each forwarded message has one Relay Genie Delivery row: its tries live in the database, so a retry or a voice
note's wait survives a cache flush or a worker restart, and the watchdog notes a chat left unanswered."""
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
from frappe.utils import add_to_date, get_datetime, get_system_timezone, now_datetime

from relay_core import features
from relay_core.automation.queue import QUEUE, after_message_commit

DELIVERY = 'Relay Genie Delivery'
TIMEOUT = 10
# Seconds after each failed try. Six tries in about 30 minutes.
BACKOFF = (60, 120, 300, 600, 900)
MAX_ATTEMPTS = len(BACKOFF) + 1
# A queued or running try owns its row this long; the scheduler sends a row again only after it.
LEASE_SECONDS = 120
WATCH_MINUTES = 10
BATCH = 100
NOTE = 'Not answered automatically; please reply.'
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
    if doc.get('genie_enabled') and not (doc.get('genie_url') and doc.get('genie_secret') and doc.get('genie_user')):
        frappe.throw('Set the Genie URL, secret and Relay user before you turn Genie on')
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
    if allowed and doc.get('business_doctype') not in allowed:
        return False
    return not is_taken_over(doc.relay_contact, doc)


def is_taken_over(contact: str, message=None) -> bool:
    """True when staff own the chat: the Relay automation's rule (a paused contact, or a held episode ticket), less
    the Genie user's own holds. A pause for an active MCP claim is the claim's (its guard stops another sender),
    and a ticket held by the Genie user's own reply is Genie's."""
    paused, generation = frappe.db.get_value('Relay Contact', contact, ['automation_paused', 'automation_generation'])
    if paused and not is_claim_pause(contact, generation):
        return True
    ticket = held_ticket(message) if message else None
    return bool(ticket and ticket.ai_disabled and ticket.ownership_actor != frappe.db.get_single_value('Relay Settings', 'genie_user'))


def is_claim_pause(contact: str, generation) -> bool:
    """The contact's pause belongs to an active MCP chat claim. Reads the claim without ending an expired one."""
    from relay_core.mcp_tools.coordination import CLAIMS
    claim = frappe.cache.hget(CLAIMS, contact)
    claim = json.loads(claim) if claim else None
    return bool(claim and claim['until'] > time.time() and claim.get('paused_generation')
                and int(claim['paused_generation']) == int(generation or 0))


def held_ticket(message):
    """The ownership of the message's active episode ticket, or None when it has none."""
    from relay_core.tickets import _episode_scope
    try:
        _, key = _episode_scope(message)
    except ValueError:
        return None
    return frappe.db.get_value('Relay Ticket', {'active_scope_key': key}, ['ai_disabled', 'ownership_actor'], as_dict=True)


def is_chat_taken_over(contact: str) -> bool:
    """is_taken_over for the chat's newest customer message, for reply_context."""
    newest = frappe.get_all('Relay Message', filters={'relay_contact': contact, 'direction': 'Incoming'}, pluck='name',
                            order_by='name desc', limit_page_length=1)
    return is_taken_over(contact, frappe.get_doc('Relay Message', newest[0]) if newest else None)


def job_id(message: str) -> str:
    return 'relay-genie:' + message


def enqueue(message: str, after_commit: bool = False) -> None:
    frappe.enqueue('relay_core.genie.deliver', message=message, queue=QUEUE, timeout=TIMEOUT + 20,
                   job_id=job_id(message), deduplicate=True, enqueue_after_commit=after_commit)


def lease_end():
    return add_to_date(now_datetime(), seconds=LEASE_SECONDS)


@after_message_commit
def on_message(doc, method=None):
    """Runs in the inbound drain. A Genie problem must never stop the other inbound work. The row commits with the
    drain's message, so the scheduler sends it even when the queued job is lost."""
    try:
        if handles(doc) and not frappe.db.exists(DELIVERY, doc.name):
            frappe.get_doc({'doctype': DELIVERY, 'message': doc.name, 'relay_contact': doc.relay_contact,
                            'status': 'Pending', 'attempts': 0, 'next_try': lease_end()}).insert(ignore_permissions=True)
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


def deliver(message: str) -> None:
    """One try of a Pending delivery; its row keeps the tries, the next try and the result."""
    row = frappe.db.get_value(DELIVERY, message, ['status', 'attempts'], as_dict=True)
    if not row or row.status != 'Pending':
        return
    doc = frappe.get_doc('Relay Message', message)
    if not handles(doc):
        save(message, status='Skipped')
        return
    attempt = int(row.attempts or 0) + 1
    if doc.get('transcript_status') == 'Pending' and attempt < MAX_ATTEMPTS:
        retry_later(message, attempt, 'Waiting for the voice transcript')  # Send the voice note with its transcript.
        return
    settings = frappe.get_single('Relay Settings')
    secret = settings.get_password('genie_secret', raise_exception=False)
    if not secret:
        fail(message, attempt, 'Set the Genie secret')
        return
    try:
        post(settings.genie_url, secret, doc)
    except DeliveryError as error:
        if attempt < MAX_ATTEMPTS:
            retry_later(message, attempt, str(error))
        else:
            fail(message, attempt, str(error))
        return
    save(message, status='Sent', attempts=attempt, delivered_at=now_datetime(), last_error=None)


def save(message: str, **values) -> None:
    frappe.db.set_value(DELIVERY, message, values)
    frappe.db.commit()


def retry_later(message: str, attempt: int, reason: str) -> None:
    save(message, attempts=attempt, next_try=add_to_date(now_datetime(), seconds=BACKOFF[attempt - 1]), last_error=reason[:140])


def fail(message: str, attempt: int, reason: str) -> None:
    save(message, status='Failed', attempts=attempt, last_error=reason[:140])
    frappe.log_error(title='Relay Genie delivery failed', message=f'Message {message} was not accepted after {attempt} tries: {reason}')


def run_due() -> None:
    """Scheduler, each minute: send the due deliveries, then note the chats left unanswered."""
    retry_due()
    watch()


def retry_due() -> None:
    """Queue the Pending rows whose next try is due. Each one's lease moves first, so the next run skips it while its
    job is queued or running."""
    due = frappe.get_all(DELIVERY, filters={'status': 'Pending', 'next_try': ['<=', now_datetime()]}, pluck='name',
                         order_by='next_try asc', limit_page_length=BATCH)
    for message in due:
        frappe.db.set_value(DELIVERY, message, 'next_try', lease_end(), update_modified=False)
        enqueue(message, after_commit=True)
    frappe.db.commit()


def watch() -> None:
    """A delivered message whose chat has no reply after it and no staff note WATCH_MINUTES later gets one note.
    A claimed chat waits: its holder is answering. The row's follow_up is set once, so a chat is noted once."""
    from relay_core.mcp_tools.coordination import active_claim
    rows = frappe.get_all(DELIVERY, filters={'status': 'Sent', 'follow_up': ['is', 'not set'],
                                             'delivered_at': ['<=', add_to_date(now_datetime(), minutes=-WATCH_MINUTES)]},
                          fields=['name', 'relay_contact'], order_by='delivered_at asc', limit_page_length=BATCH)
    for row in rows:
        if frappe.db.exists('Relay Message', {'relay_contact': row.relay_contact, 'direction': 'Outgoing', 'name': ['>', row.name]}):
            save(row.name, follow_up='Replied')
        elif has_note_after(row.relay_contact, row.name):
            save(row.name, follow_up='Noted')
        elif not active_claim(row.relay_contact):
            save(row.name, follow_up=add_note(row.relay_contact, row.name))


def has_note_after(contact: str, message: str) -> bool:
    created = frappe.db.get_value('Relay Message', message, 'creation')
    return bool(frappe.db.exists('Relay Internal Comment', {'relay_contact': contact, 'deleted': 0, 'creation': ['>=', created]}))


def add_note(contact: str, message: str) -> str:
    """One internal note for staff, keyed by the message, so a repeat returns the first note."""
    from relay_core.collaboration import add
    try:
        add(contact, NOTE, 'genie-watch-' + message, messages=[message])
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title='Relay Genie watchdog note failed', message=f'Chat {contact}, message {message}')
        return 'Note Failed'
    return 'Noted'
