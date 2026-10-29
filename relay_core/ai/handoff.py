"""One idempotent, assigned human handoff for automation failures."""
import hashlib
import json
from contextvars import ContextVar

import frappe
from relay_core.automation.queue import QUEUE
from relay_core.automation.service import internal_save
from relay_core.tickets import ensure_episode, hold_episode, episode_owner_allowed as eligible


ACKNOWLEDGEMENT = 'Thank you for letting us know. A person from our team will follow up with you.'
outgoing_notice = ContextVar('relay_handoff_notice', default=False)


def handoff(run, skill, reason):
    if skill.get('mode') == 'Shadow':
        run.status, run.reason = 'Shadow', reason[:500]
        internal_save(run)
        return
    message = frappe.get_doc('Relay Message', run.message)
    original = frappe.session.user
    try:
        # A service write may route an authorization failure, but never disclose its data.
        frappe.set_user('Administrator')
        fallback = frappe.get_single('Relay Settings').get('ai_handoff_owner')
        owner = next((user for user in (skill.get('handoff_owner'), fallback) if eligible(user, message)), None)
        if not owner:
            raise ValueError('Configure an accessible handoff owner or fallback owner')
        # Admission uses this run's existing decision for customer intent and links its trigger.
        ticket = ensure_episode(message, owner=owner, run=run, reason=reason)
        ticket = hold_episode(ticket.name)
        run.ticket, run.status, run.reason = ticket.name, 'Handoff', reason[:500]
        queue_acknowledgement(run, ticket, user=run.execution_user)
        internal_save(run)
        return ticket.name
    finally:
        frappe.set_user(original)


def queue_acknowledgement(run, ticket, *, user):
    """Persist a fixed notice intent with the service hold's generation, never model text."""
    decision = json.loads(run.get('decision') or '{}')
    if decision.get('handoff_notice'):
        return
    decision.update(handoff_notice='Pending', notice_generation=int(ticket.generation or 0), notice_user=user)
    run.decision = json.dumps(decision)
    frappe.enqueue('relay_core.ai.handoff.acknowledge', name=run.name, queue=QUEUE, enqueue_after_commit=True)


def notice_scope(run, message):
    from relay_core.automation.channel import identity, enabled
    from relay_core.automation.service import message_hash, lock_contact
    from relay_core import ai_features
    decision = json.loads(run.decision or '{}')
    ticket = frappe.get_doc('Relay Ticket', run.ticket, for_update=True)
    channel = frappe.get_doc('Relay Channel', message.channel)
    contact = lock_contact(message.relay_contact)
    if (run.status != 'Handoff' or not decision.get('handoff_notice')
            or not frappe.conf.get('relay_automation_enabled') or not ai_features.is_enabled()
            or not channel.enabled or not enabled(channel)
            or not ticket.ai_disabled or not ticket.active_scope_key or ticket.ownership_actor != 'Administrator'
            or int(ticket.generation or 0) != decision.get('notice_generation')
            or message.name != run.message or message.get('ticket') != run.ticket
            or message_hash(message) != run.message_hash
            or contact.automation_paused or int(contact.automation_generation or 0) != int(run.generation or 0)
            or ticket.company != channel.company or ticket.conversation_key != message.conversation_key
            or (ticket.business_doctype, ticket.business_name) != (message.business_doctype, message.business_name)
            or frappe.session.user != decision.get('notice_user')):
        raise ValueError('Handoff acknowledgement scope changed')
    # Same verified endpoint and readable linked business as channel admission.
    identity(message, channel)


def authorize_notice(action, message):
    """Only the fixed, journaled notice may cross its own hold; staff takeover still fences it."""
    from relay_core.ai.service import reply_key
    payload = json.loads(action.payload)
    run = frappe.get_doc('Relay Automation Run', payload['automation_run'])
    prefix = 'email:' if action.operation == 'email' else ''
    key = hashlib.sha256((prefix + frappe.session.user + ':' + reply_key(message.name, 'handoff', run)).encode()).hexdigest()
    body = payload.get('email_values', {}).get('body') if prefix else payload.get('content', {}).get('text')
    if action.request_key != key or body != ACKNOWLEDGEMENT or action.operation not in ('text', 'email'):
        raise ValueError('Invalid handoff acknowledgement')
    notice_scope(run, message)


def acknowledge(name):
    from relay_core.automation.service import lock_run, outgoing_run
    from relay_core.ai.service import send_reply
    from relay_core.ai.tools import as_user
    from relay_core.test_mode import TestModeBlocked
    run = lock_run(name)
    decision = json.loads(run.decision or '{}')
    if run.status != 'Handoff' or decision.get('handoff_notice') != 'Pending':
        return
    token, notice = outgoing_run.set(run.name), outgoing_notice.set(True)
    try:
        with as_user(decision['notice_user']):
            message = frappe.get_doc('Relay Message', run.message)
            notice_scope(run, message)
            result = send_reply(message, ACKNOWLEDGEMENT, slot='handoff')
            # Queued/uncertain sends are recovered by the existing message journal.
            decision['handoff_notice'] = 'Journaled' if result['status'] in (
                'Submitted', 'Queued', 'Uncertain', 'Dispatching') else 'Blocked'
    except (TestModeBlocked, ValueError, frappe.PermissionError):
        decision['handoff_notice'] = 'Blocked'
        frappe.log_error(title='Relay handoff acknowledgement blocked')
    finally:
        outgoing_notice.reset(notice)
        outgoing_run.reset(token)
    run = lock_run(name)
    run.decision = json.dumps(decision)
    internal_save(run)
    frappe.db.commit()


def recover_acknowledgements():
    for name in frappe.get_all('Relay Automation Run', filters={'status': 'Handoff',
            'decision': ['like', '%"handoff_notice": "Pending"%']}, pluck='name',
            order_by='modified asc', limit_page_length=20):
        frappe.enqueue('relay_core.ai.handoff.acknowledge', name=name, queue=QUEUE)
