"""Relay AI hand-over: a new customer message goes to the Live Relay AI skill whose AI Model is a conversation agent.

frappe_tools holds the agent's endpoint, secret and model (AI Provider Account and AI Model). The agent answers the
whole chat through the Relay MCP as the skill's Run as user. Relay hands each message over once, in a background job;
retries and unanswered chats are the agent's job. A voice note goes at once, with Relay's transcript when it has one."""
import json
import re
import time
from datetime import UTC
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_datetime, get_system_timezone

from relay_core import ai_features, features
from relay_core.automation.queue import QUEUE, after_message_commit

ROUTE = 'relay'
TIMEOUT = 10
SKIPPED_KINDS = ('system', 'reaction')
GROUP_CHAT_TYPES = ('group', 'supergroup', 'channel')
CONTACT_DETAIL = re.compile(r'@|^[\d\s()+.-]+$')


def is_group(doc) -> bool:
    from relay_core.automation.provenance import context_of
    context = context_of(doc)
    return bool(context.get('group_id') or context.get('chat_type') in GROUP_CHAT_TYPES)


def live_agent_skill(doc):
    """The first Live skill of Relay AI's candidates for the message whose AI Model is a conversation agent."""
    from frappe_tools.ai.conversation import is_conversation_agent

    from relay_core.ai.matching import candidates
    return next((skill for skill in candidates(doc)
                 if skill.mode == 'Automatic' and skill.ai_model and is_conversation_agent(skill.ai_model)), None)


def agent_skill(doc):
    """The skill whose agent, not the Relay automation, answers this message; None leaves it to Relay."""
    if doc.get('legacy_source') or doc.direction != 'Incoming' or doc.get('message_type') in SKIPPED_KINDS:
        return None
    if not ai_features.is_enabled() or not features.is_automation_allowed(doc.relay_contact):
        return None  # While automation is limited to test contacts, only those contacts go to an agent.
    from relay_core.automation.provenance import context_of
    from relay_core.email_preferences import automatic_allowed
    from relay_core.opt_out import is_keyword
    if is_keyword(doc) or is_group(doc) or not automatic_allowed(context_of(doc)):
        return None
    skill = live_agent_skill(doc)
    if not skill or is_taken_over(doc.relay_contact, doc, skill.run_as_user):
        return None
    return skill


def handles(doc) -> bool:
    return agent_skill(doc) is not None


def handles_safely(doc) -> bool:
    """handles() for the other inbound handlers: an unexpected error is logged and the message stays Relay's, so the
    inbound drain never rolls back and retries the message for a hand-over problem."""
    try:
        return handles(doc)
    except Exception:
        frappe.log_error(title='Relay AI hand-over check failed', message=f'Message {doc.name} stays with the Relay automation.')
        return False


def is_taken_over(contact: str, message=None, agent_user: str | None = None) -> bool:
    """True when staff own the chat: the Relay automation's rule (a paused contact, or a held episode ticket), less
    the agent's own holds. A pause for an active MCP claim is the claim's (its guard stops another sender),
    and a ticket held by the agent user's own reply is the agent's."""
    paused, generation = frappe.db.get_value('Relay Contact', contact, ['automation_paused', 'automation_generation'])
    if paused and not is_claim_pause(contact, generation):
        return True
    ticket = held_ticket(message) if message else None
    return bool(ticket and ticket.ai_disabled and ticket.ownership_actor != agent_user)


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
    message = frappe.get_doc('Relay Message', newest[0]) if newest else None
    skill = live_agent_skill(message) if message else None
    return is_taken_over(contact, message, skill.run_as_user if skill else None)


def job_id(message: str) -> str:
    return 'relay-ai-hand-over:' + message


@after_message_commit
def on_message(doc, method=None):
    """Runs in the inbound drain. A hand-over problem must never stop the other inbound work."""
    try:
        if handles(doc):
            frappe.enqueue('relay_core.ai.hand_over.deliver', message=doc.name, queue=QUEUE, timeout=TIMEOUT + 20,
                           job_id=job_id(doc.name), deduplicate=True, enqueue_after_commit=True)
    except Exception:
        frappe.log_error(title='Relay AI hand-over enqueue failed', message=f'Message {doc.name} was not handed over.')


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
            'text': doc.get('transcript') or doc.get('content') or '', 'transcript': doc.get('transcript') or '',
            'transcript_status': doc.get('transcript_status') or '', 'message_type': doc.get('message_type') or 'text',
            'has_media': has_media(doc), 'business': business(doc), 'timestamp': utc_stamp(doc.get('sent_at') or doc.creation)}


def deliver(message: str) -> None:
    """The background job: hand the message to its skill's agent once. A refusal is logged, never retried."""
    from frappe_tools.ai.conversation import HandOverError, hand_over
    doc = frappe.get_doc('Relay Message', message)
    skill = agent_skill(doc)
    if not skill:
        return  # Staff took the chat over, or the skill changed, after the message was queued.
    try:
        hand_over(skill.ai_model, ROUTE, payload(doc), headers={'X-Relay-Delivery': doc.name}, timeout=TIMEOUT)
    except HandOverError as error:
        frappe.log_error(title='Relay AI hand-over failed', message=f'Message {doc.name} was not accepted: {error}')
