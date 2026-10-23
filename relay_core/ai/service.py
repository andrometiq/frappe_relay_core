"""Durable skill decisions; all outbound text uses the message action journal."""
import hashlib
import json
import frappe
from relay_core.ai.tools import as_user
from relay_core.automation.service import internal_save, lock_run, lock_contact, message_hash, latest_message, outgoing_run
from relay_core.automation.contracts import event_key, action_key


def skill_for(message):
    from relay_core.business_access import reference
    business = reference(message)
    if not business:
        return None
    names = frappe.get_all('Relay AI Skill', filters={'channel': message.channel,
        'business_doctype': business[0], 'enabled': 1}, pluck='name', limit_page_length=2)
    if len(names) > 1:
        raise ValueError('Only one enabled skill is allowed per channel and business type')
    return frappe.get_doc('Relay AI Skill', names[0]) if names else None


def create_run(message, skill):
    contact = lock_contact(message.relay_contact)
    if contact.automation_paused:
        return {'status': 'Paused'}
    run = frappe.get_doc({'doctype': 'Relay Automation Run', 'event_key': event_key(message.name),
        'message': message.name, 'skill': skill.name, 'skill_version': str(skill.modified),
        'execution_user': skill.run_as_user, 'message_hash': message_hash(message),
        'status': 'Pending', 'generation': int(contact.automation_generation or 0)})
    internal_save(run, new=True)
    frappe.enqueue('relay_core.automation.service.process', name=run.name, queue='short', timeout=90, enqueue_after_commit=True)
    return {'name': run.name, 'status': run.status}


def context(skill, message):
    from relay_core.business_access import reference, candidates
    business = reference(message)
    if not business or business[0] != skill.business_doctype or business not in candidates(message.relay_contact):
        raise ValueError('Business identity is missing or ambiguous')
    contact = frappe.get_doc('Relay Contact', message.relay_contact)
    person = frappe.get_doc('Contact', contact.contact)
    key = hashlib.sha256((message.channel + ':' + (message.sender_endpoint or '')).encode()).hexdigest()
    if frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': key, 'verified': 1}, 'relay_contact') != contact.name:
        raise ValueError('Endpoint verification is missing or revoked')
    channel = frappe.get_doc('Relay Channel', message.channel)
    if message.channel != skill.channel or channel.channel != 'WhatsApp' or not channel.enabled:
        raise ValueError('Skill channel is unavailable')
    if message.direction != 'Incoming' or message.message_type not in ('text', '', None):
        raise ValueError('This skill requires an incoming text message')
    # A linked but disabled/denied user must never fall back to a broader identity.
    user = person.get('user') or skill.run_as_user
    with as_user(user):
        frappe.get_doc(*business).check_permission('read')
    return user, business


def decide(skill, message, run_id=None):
    from relay_core.ai.adapter import complete, MAX_PROMPT_LENGTH
    user, business = context(skill, message)
    text = message.content or ''
    # Bounded history lets a sender agree to a previously offered date range.
    history = frappe.get_list('Relay Message', filters={'conversation_key': message.conversation_key,
        'business_doctype': business[0], 'business_name': business[1], 'name': ['<', message.name]},
        fields=['direction', 'content'], order_by='name desc', page_length=6) if message.get('conversation_key') else []
    history = list(reversed(history))
    while True:
        prompt = json.dumps({'history': history, 'incoming': text}, default=str)
        if len(prompt) <= MAX_PROMPT_LENGTH:
            return complete(skill, user, business, prompt, run_id)
        if not history:
            raise ValueError('Incoming message exceeds the skill prompt budget')
        history.pop(0)


class Superseded(ValueError):
    pass


def current(run, skill, message):
    contact = lock_contact(message.relay_contact)
    if not skill.enabled or str(skill.modified) != run.skill_version or contact.automation_paused or int(contact.automation_generation or 0) != int(run.generation):
        raise Superseded('Conversation or skill changed')
    if message_hash(message) != run.message_hash or not latest_message(message):
        raise Superseded('Incoming message changed or was superseded')
    return context(skill, message)


def process(name):
    from relay_core.ai.handoff import handoff
    run = lock_run(name)
    if run.status not in ('Pending', 'Deciding'):
        return
    skill = frappe.get_doc('Relay AI Skill', run.skill)
    if run.reason == 'Handoff owner unavailable; automation paused pending recovery':
        handoff(run, skill, 'Decision or authorization failed; review required')
        frappe.db.commit()
        return
    try:
        with as_user(run.execution_user):
            message = frappe.get_doc('Relay Message', run.message)
            message.check_permission('read')
            current(run, skill, message)
            decision = json.loads(run.decision) if run.decision else None
            if decision is None:
                if int(run.attempts or 0) >= 2:
                    raise ValueError('AI attempt limit reached')
                from relay_core.automation.service import reserve_attempt
                reserve_attempt(skill)
                run.status, run.attempts = 'Deciding', int(run.attempts or 0) + 1
                internal_save(run); frappe.db.commit()
                decision = decide(skill, message, run.name)
                frappe.db.commit()
                run = lock_run(name)
                if run.status != 'Deciding':
                    return
                skill.reload(); message.reload()
                current(run, skill, message)
                run.decision = json.dumps(decision)
                internal_save(run); frappe.db.commit()
            if skill.mode == 'Shadow':
                run.status = 'Shadow'; internal_save(run); frappe.db.commit(); return
            if decision['handoff']:
                handoff(run, skill, decision['reason'] or 'Outside the configured skill')
            else:
                delivery_scope(run, skill, message, decision)
                from relay_core.messaging import send
                token = outgoing_run.set(run.name)
                try:
                    result = send(message.name, 'text', {'text': decision['reply']}, action_key(message.name, 'reply'), quote=0)
                finally:
                    outgoing_run.reset(token)
                if result['status'] not in ('Submitted', 'Queued', 'Uncertain', 'Dispatching'):
                    raise ValueError('Reply delivery requires review')
                run.status = 'Completed'
                internal_save(run)
            frappe.db.commit()
    except Superseded:
        frappe.db.rollback()
        run = lock_run(name)
        run.status, run.reason = 'Cancelled', 'Conversation, message or skill changed'
        internal_save(run); frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        run = lock_run(name)
        if run.status not in ('Pending', 'Deciding'):
            return
        if skill.mode == 'Shadow':
            run.status, run.reason = 'Shadow', 'Decision or authorization failed'
            internal_save(run)
        else:
            try:
                handoff(run, skill, 'Decision, delivery or authorization failed; review required')
            except Exception:
                # Leave the run recoverable if every configured owner is unavailable.
                frappe.db.rollback()
                contact = lock_contact(frappe.get_doc('Relay Message', run.message).relay_contact)
                if not contact.automation_paused:
                    contact.automation_generation = int(contact.automation_generation or 0) + 1
                contact.automation_paused = 1
                contact.save(ignore_permissions=True)
                run.reason = 'Handoff owner unavailable; automation paused pending recovery'
                internal_save(run); frappe.db.commit()
                frappe.log_error(title='Relay handoff unavailable', message='Configure an enabled owner with conversation access')
                return
        frappe.db.commit()


def delivery_scope(run, skill, message, decision=None):
    from relay_core.ai.tools import recheck
    decision = decision if decision is not None else json.loads(run.decision)
    user, business = current(run, skill, message)
    if decision.get('user') != user:
        raise ValueError('Conversation user changed')
    recheck(skill, user, business, decision.get('reads', []))
