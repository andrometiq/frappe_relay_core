"""Durable skill decisions; all outbound text uses the message action journal."""
import json
import frappe
from relay_core.automation.queue import QUEUE
from relay_core.ai.tools import as_user
from relay_core.automation.service import internal_save, lock_run, lock_contact, message_hash, latest_message, outgoing_run
from relay_core.automation.contracts import event_key, action_key


def skill_for(message):
    if not frappe.db.exists('Relay AI Skill', {'channel': message.channel, 'enabled': 1}):
        return None
    from relay_core.business_access import reference
    business = reference(message)
    if not business:
        return None
    names = frappe.get_all('Relay AI Skill', filters={'channel': message.channel,
        'business_doctype': business[0], 'enabled': 1}, pluck='name', limit_page_length=2)
    if len(names) > 1:
        from relay_core.ai.configuration import skill_conflict
        raise ValueError(skill_conflict(message.channel, business[0], names))
    return frappe.get_doc('Relay AI Skill', names[0]) if names else None


def create_run(message, skill):
    from relay_core.email_preferences import automatic_allowed
    from relay_core.automation.provenance import context_of
    provenance = context_of(message)
    if not automatic_allowed(provenance):
        return {'status': 'Ignored'}
    if provenance.get('provider') == 'Email':
        from relay_core.email_preferences import automatic_reply_exists
        if automatic_reply_exists(message):
            return {'status': 'Ignored'}
    contact = lock_contact(message.relay_contact)
    if contact.automation_paused:
        return {'status': 'Paused'}
    run = frappe.get_doc({'doctype': 'Relay Automation Run', 'event_key': event_key(message.name),
        'message': message.name, 'skill': skill.name, 'skill_version': str(skill.modified),
        'execution_user': skill.run_as_user, 'message_hash': message_hash(message),
        'status': 'Pending', 'generation': int(contact.automation_generation or 0)})
    internal_save(run, new=True)
    frappe.enqueue('relay_core.automation.service.process', name=run.name, queue=QUEUE, timeout=90, enqueue_after_commit=True)
    return {'name': run.name, 'status': run.status}


def context(skill, message):
    from relay_core.business_access import reference, candidates
    business = reference(message)
    if not business or business[0] != skill.business_doctype or business not in candidates(message.relay_contact):
        raise ValueError('Business identity is missing or ambiguous')
    contact = frappe.get_doc('Relay Contact', message.relay_contact)
    person = frappe.get_doc('Contact', contact.contact)
    channel = frappe.get_doc('Relay Channel', message.channel)
    if message.channel != skill.channel or channel.channel not in ('WhatsApp', 'Telegram', 'Email') or not channel.enabled:
        raise ValueError('Skill channel is unavailable')
    if message.direction != 'Incoming' or message.message_type not in ('text', '', None):
        raise ValueError('This skill requires an incoming text message')
    from relay_core.identity import authenticated_sender
    from relay_core.automation.provenance import context_of, conversation_key
    sender = authenticated_sender(message, channel)
    conversation = conversation_key(message.channel, message.sender_endpoint, context_of(message))
    if message.get('conversation_key') != conversation or not channel.get('company'):
        raise ValueError('Conversation or company scope is missing')
    # A linked but disabled/denied user must never fall back to a broader identity.
    user = person.get('user') or skill.run_as_user
    from relay_core.permissions import company_allowed
    with as_user(user):
        frappe.get_doc(*business).check_permission('read')
        if not company_allowed(channel.company):
            raise frappe.PermissionError('Conversation company is not accessible')
    scope = dict(sender, site=frappe.local.site, company=channel.company,
        channel=message.channel, conversation=conversation, message=message.name,
        contact=contact.name, person=person.name, business=list(business), user=user)
    return user, business, scope


def decide(skill, message, run_id=None):
    from relay_core.ai.adapter import complete, MAX_PROMPT_LENGTH
    from relay_core.ai.tools import fingerprint
    user, business, scope = context(skill, message)
    text = message.content or ''
    if any(phrase in text.casefold() for phrase in ('talk to a human', 'talk to a person', 'speak to a human', 'hand this to a person')):
        return {'handoff': True, 'reply': '', 'reason': 'Sender requested a person', 'user': user, 'reads': []}
    history = conversation_history(skill, message, user, business, scope)
    while True:
        prompt = json.dumps({'history': history, 'incoming': text}, default=str)
        if len(prompt) <= MAX_PROMPT_LENGTH:
            decision = complete(skill, user, business, prompt, run_id, scope=scope)
            return dict(decision, scope=fingerprint(scope))
        if not history:
            raise ValueError('Incoming message exceeds the skill prompt budget')
        history.pop(0)


def conversation_history(skill, message, user, business, scope):
    """Keep scoped announcements; old business results require a fresh authorized read."""
    from relay_core.ai.tools import fingerprint
    history = []
    try:
        with as_user(user):
            sources = frappe.get_list('Relay Message', filters={'conversation_key': message.conversation_key,
                'business_doctype': business[0], 'business_name': business[1], 'direction': 'Incoming',
                'name': ['<', message.name]}, fields=['name', 'content'], order_by='name desc', page_length=3)
            for source in reversed(sources):
                source = frappe.get_doc('Relay Message', source.name)
                source.check_permission('read')
                source.apply_fieldlevel_read_permissions()
                # The journal is internal coordination metadata. Only a reply with
                # no business reads and this exact permission-checked source scope
                # may cross into history; audit records themselves stay private.
                stored = frappe.db.get_value('Relay Automation Run', {'message': source.name,
                    'skill': skill.name, 'skill_version': str(skill.modified), 'status': 'Completed'},
                    'decision')
                try:
                    decision = json.loads(stored)
                except (TypeError, ValueError):
                    continue
                if (not isinstance(decision, dict) or decision.get('reads') != [] or decision.get('handoff')
                        or decision.get('user') != user
                        or decision.get('scope') != fingerprint(dict(scope, message=source.name))
                        or not isinstance(decision.get('reply'), str) or len(decision['reply']) > 2000):
                    continue
                if not isinstance(source.get('content'), str):
                    continue
                history.extend([{'direction': 'Incoming', 'content': source.content},
                    {'direction': 'Outgoing', 'content': decision['reply']}])
    except frappe.PermissionError:
        return []  # Optional history never borrows the run-as user's broader access.
    return history


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
                token = outgoing_run.set(run.name)
                try:
                    result = send_reply(message, decision['reply'])
                finally:
                    outgoing_run.reset(token)
                if result['status'] not in ('Submitted', 'Queued', 'Uncertain', 'Dispatching'):
                    raise ValueError('Reply delivery requires review')
                run = lock_run(name)
                if run.status in ('Pending', 'Deciding'):
                    run.status = 'Completed' if result['status'] == 'Submitted' else 'Delivering'
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
                defer_handoff(run.name)
                return
        frappe.db.commit()


def delivery_scope(run, skill, message, decision=None):
    from relay_core.ai.tools import recheck, fingerprint
    decision = decision if decision is not None else json.loads(run.decision)
    user, business, scope = current(run, skill, message)
    if decision.get('user') != user or decision.get('scope') != fingerprint(scope):
        raise ValueError('Conversation scope changed')
    recheck(skill, user, business, decision.get('reads', []), scope)


def send_reply(message, reply):
    from relay_core.automation.provenance import context_of
    context = context_of(message)
    key = action_key(message.name, 'reply')
    if context.get('provider') == 'Email':
        from relay_core.email import send
        subject = context.get('subject') or 'Reply'
        if not subject.lower().startswith('re:'):
            subject = 'Re: ' + subject
        return send([message.sender_endpoint], subject, reply, request_key=key,
                    message=message.name, auto_submitted=1)
    from relay_core.messaging import send
    return send(message.name, 'text', {'text': reply}, key, quote=0)


def complete(action):
    if action.status in ('Submitted', 'Rejected') and json.loads(action.payload).get('automation_run'):
        frappe.enqueue('relay_core.ai.service.complete_delivery', action=action.name,
                       queue=QUEUE, enqueue_after_commit=True)


def complete_delivery(action):
    from relay_core.ai.handoff import handoff
    frappe.db.get_value('Relay Message Action', action, 'name', for_update=True)
    action = frappe.get_doc('Relay Message Action', action)
    name = json.loads(action.payload).get('automation_run')
    if not name or action.status not in ('Submitted', 'Rejected'):
        return
    run = lock_run(name)
    if (not run.get('skill') or run.message != action.source_message
            or run.status not in ('Pending', 'Deciding', 'Delivering', 'Completed')):
        return
    if action.status == 'Submitted':
        run.status = 'Completed'
        internal_save(run)
    else:
        skill = frappe.get_doc('Relay AI Skill', run.skill)
        try:
            handoff(run, skill, 'Reply delivery rejected; review required')
        except Exception:
            defer_handoff(run.name)
            return
    frappe.db.commit()


def recover_deliveries():
    run = frappe.qb.DocType('Relay Automation Run')
    action = frappe.qb.DocType('Relay Message Action')
    rows = (frappe.qb.from_(run).join(action).on(run.message == action.source_message)
        .select(action.name).where(run.skill.isnotnull())
        .where(action.payload.like('%"automation_run":%'))
        .where(((run.status == 'Delivering') & action.status.isin(['Submitted', 'Rejected']))
               | ((run.status == 'Completed') & (action.status == 'Rejected')))
        .orderby(run.modified).limit(20).run(as_dict=True))
    for row in rows:
        frappe.enqueue('relay_core.ai.service.complete_delivery', action=row.name, queue=QUEUE)


def defer_handoff(name):
    frappe.db.rollback()
    run = lock_run(name)
    contact = lock_contact(frappe.get_doc('Relay Message', run.message).relay_contact)
    if not contact.automation_paused:
        contact.automation_generation = int(contact.automation_generation or 0) + 1
    contact.automation_paused = 1
    contact.save(ignore_permissions=True)
    run.reason = 'Handoff owner unavailable; automation paused pending recovery'
    internal_save(run); frappe.db.commit()
    frappe.log_error(title='Relay handoff unavailable', message='Configure an enabled owner with conversation access')
