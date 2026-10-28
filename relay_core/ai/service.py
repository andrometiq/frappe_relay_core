"""Durable skill decisions; all outbound text uses the message action journal."""
import json
import time
import hashlib
import frappe
from relay_core.automation.queue import QUEUE
from relay_core.ai.tools import as_user
from relay_core.automation.service import internal_save, lock_run, lock_contact, message_hash, latest_message, outgoing_run
from relay_core.automation.contracts import action_key


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
    if message.direction != 'Incoming' or message.message_type not in ('text', '', None, 'photo', 'image'):
        raise ValueError('This skill requires incoming text or an image')
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
        # Apply field permissions to a fresh copy, leaving the coordination source intact.
        source = frappe.get_doc('Relay Message', message.name)
        source.check_permission('read')
        source.apply_fieldlevel_read_permissions()
        if any(source.get(field) != message.get(field) for field in
               ('content', 'message_data', 'provider_context', 'sender_endpoint')):
            raise frappe.PermissionError('Source message fields are not accessible')
        frappe.get_doc(*business).check_permission('read')
        if not company_allowed(channel.company):
            raise frappe.PermissionError('Conversation company is not accessible')
    scope = dict(sender, site=frappe.local.site, company=channel.company,
        channel=message.channel, conversation=conversation, message=message.name,
        contact=contact.name, person=person.name, business=list(business), user=user)
    return user, business, scope


def decide(skill, message, run_id=None, *, deadline=None):
    from relay_core.ai.adapter import complete, MAX_PROMPT_LENGTH
    from relay_core.ai.tools import fingerprint
    deadline = deadline or time.monotonic() + 20
    user, business, scope = context(skill, message)
    text = message.content or ''
    from relay_core.ai.matching import human_request
    if human_request(text):
        return {'handoff': True, 'reply': '', 'reason': 'Sender requested a person', 'user': user, 'reads': []}
    history = conversation_history(skill, message, user, business, scope)
    if message.message_type in ('photo', 'image'):
        from relay_core.automation.multimodal import context as media_context
        from relay_core.ai.adapter import observe_image
        from relay_core.automation.service import reserve_attempt
        from relay_core.ai.adapter import require_vision
        require_vision(frappe.get_doc('AI Model', skill.ai_model))
        with as_user(user):
            text, images = media_context({'allow_images': True}, message, run_id)
        check_continuation(run_id)
        if run_id:
            reserve_attempt(skill)
        text = json.dumps({'caption': text, 'image_observation': observe_image(skill, images, run_id, deadline=deadline)})
    while True:
        prompt = json.dumps({'history': history, 'incoming': text}, default=str)
        if len(prompt) <= MAX_PROMPT_LENGTH:
            options = {"deadline": deadline} if deadline else {}
            if run_id:
                run = frappe.get_doc('Relay Automation Run', run_id)
                if run.get('search_plan') and run.stage == 'Event':
                    options['search'] = json.loads(run.search_plan)['plan']
            check_continuation(run_id)
            decision = complete(skill, user, business, prompt, run_id, scope=scope, **options)
            return dict(decision, scope=fingerprint(scope))
        if not history:
            raise ValueError('Incoming message exceeds the skill prompt budget')
        history.pop(0)


def check_continuation(run_id):
    """Refresh state after slow work, releasing Relay locks before model I/O."""
    if not run_id:
        return  # Saved-event previews have no operational episode.
    frappe.db.commit()
    run = frappe.get_doc('Relay Automation Run', run_id)
    skill = frappe.get_doc('Relay AI Skill', run.skill)
    message = frappe.get_doc('Relay Message', run.message)
    current(run, skill, message)
    frappe.db.commit()


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


def search_scope(scope):
    from relay_core.ai.tools import fingerprint
    return fingerprint({key: value for key, value in scope.items() if key != 'message'})


def confirmation_required(skill, plan):
    from relay_core.ai.tools import contracts
    reference = next(row for row in contracts(skill) if row['name'] == plan['reference'])
    return (skill.get('search_confirmation') != 'When required'
            or reference['doctype'] == 'GL Entry' or 'Ledger' in reference['doctype'])


def declare_search(run, skill, message, decision):
    from relay_core.ai.tools import contracts
    from relay_core.automation.contracts import validate_search, canonical
    if decision.get('handoff') or decision.get('reads') or run.get('search_plan'):
        return
    plan = decision.get('search')
    if not plan:
        return
    plan = validate_search(plan, contracts(skill))
    user, business, scope = current(run, skill, message)
    record = dict(plan=plan, scope=search_scope(scope), version=str(skill.modified), ticket=run.ticket,
        generation=int(run.generation or 0), ownership_generation=int(frappe.db.get_value(
            'Relay Ticket', run.ticket, 'generation') or 0),
        origin=run.name, source=message.name, source_hash=message_hash(message), confirmed_by=None, consumed_by=None)
    run.search_plan, run.stage = json.dumps(record), 'Search'
    statement = (f"I will search {plan['reference']} to {plan['purpose']}. "
                 f"Fields: {', '.join(plan['fields'])}. Search: {canonical(plan['arguments'])}.")
    if confirmation_required(skill, plan):
        statement += ' Please confirm this exact search by replying yes, or tell me what to change.'
    if len(statement) > 2000:
        raise ValueError('Search declaration is too large')
    decision.update(reply=statement, search=plan)


def search_request_key(message, user):
    from relay_core.automation.provenance import context_of
    prefix = 'email:' if context_of(message).get('provider') == 'Email' else ''
    return hashlib.sha256((prefix + user + ':' + action_key(message.name, 'search')).encode()).hexdigest()


def check_search(run, skill, record):
    """Revalidate the durable declaration and its journal receipt on every read."""
    from relay_core.ai.tools import contracts
    from relay_core.automation.contracts import validate_search
    message = frappe.get_doc('Relay Message', run.message)
    user, business, scope = current(run, skill, message)
    validate_search(record['plan'], contracts(skill))
    if (record['scope'] != search_scope(scope) or record['version'] != str(skill.modified)
            or record['ticket'] != run.ticket or record['generation'] != int(run.generation or 0)
            or record['ownership_generation'] != int(frappe.db.get_value(
                'Relay Ticket', run.ticket, 'generation') or 0)):
        raise ValueError('Declared search scope changed')
    origin = frappe.get_doc('Relay Automation Run', record['origin'])
    original = json.loads(origin.search_plan)
    source = frappe.get_doc('Relay Message', record['source'])
    source.check_permission('read')
    if (origin.message != source.name or origin.skill != skill.name or origin.skill_version != str(skill.modified)
            or origin.ticket != run.ticket or original['plan'] != record['plan']
            or original['scope'] != record['scope'] or message_hash(source) != record['source_hash']
            or search_scope(context(skill, source)[2]) != record['scope']):
        raise ValueError('Declared search source changed')
    receipt = frappe.db.get_value('Relay Message Action', {'request_key': search_request_key(source, origin.execution_user)},
        ['status', 'source_message', 'payload'], as_dict=True)
    if (not receipt or receipt.status != 'Submitted' or receipt.source_message != source.name
            or json.loads(receipt.payload).get('automation_run') != origin.name):
        raise ValueError('Search announcement is not confirmed submitted')
    return original


def authorize_search(run_id, skill, contract, arguments):
    if not run_id:
        raise ValueError('Preview cannot read undeclared business data')
    run = lock_run(run_id)
    if not run.get('search_plan') or run.stage != 'Event' or run.status not in ('Pending', 'Deciding', 'Delivering', 'Completed'):
        raise ValueError('Declare the search before reading')
    record = json.loads(run.search_plan)
    original = check_search(run, skill, record)
    if confirmation_required(skill, record['plan']) and (
            record['confirmed_by'] != run.message or original['consumed_by'] != run.name):
        raise ValueError('Confirm the exact search before reading')
    expected = record['plan']['arguments']
    if contract['method'] == 'get_list':
        expected = dict(filters=expected.get('filters', {}), limit=expected.get('limit', 20))
        arguments = dict(filters=arguments.get('filters', {}), limit=arguments.get('limit', 20)) if not set(arguments) - {'filters', 'limit'} else arguments
    if contract['name'] != record['plan']['reference'] or contract['fields'] != record['plan']['fields'] or arguments != expected:
        raise ValueError('Search differs from the declared plan')


def continue_search(run, message):
    """Only the next exact affirmative may consume a delivered plan, once."""
    rows = frappe.get_all('Relay Automation Run', filters={'ticket': run.ticket, 'name': ['!=', run.name]},
        fields=['name'], order_by='creation desc, name desc', limit_page_length=1)
    if not rows:
        return False
    previous = lock_run(rows[0].name)
    if not previous.get('search_plan') or previous.stage != 'Search' or previous.status != 'Completed':
        return False
    record = json.loads(previous.search_plan)
    if record.get('consumed_by'):
        return False
    if (message.content or '').strip().casefold().rstrip('.!') not in ('yes', 'confirm', 'confirmed', 'yes please', 'yes, please'):
        return False
    skill = frappe.get_doc('Relay AI Skill', previous.skill)
    run.skill, run.skill_version, run.execution_user = skill.name, previous.skill_version, previous.execution_user
    with as_user(run.execution_user):
        check_search(run, skill, record)
    record['consumed_by'] = run.name
    previous.search_plan = json.dumps(record)
    internal_save(previous)
    record['confirmed_by'] = message.name
    run.search_plan, run.stage = json.dumps(record), 'Event'
    from relay_core.ai.tools import fingerprint
    run.scope_fingerprint = fingerprint(context(skill, message)[2])
    internal_save(run)
    return True


def search_delivered(run, skill):
    """An uncertain send stays Delivering; only its Submitted receipt advances."""
    record = json.loads(run.search_plan)
    if confirmation_required(skill, record['plan']):
        run.status = 'Completed'  # This message is complete; the next message confirms.
    else:
        run.stage, run.status, run.decision = 'Event', 'Pending', None
    internal_save(run)


def current(run, skill, message):
    contact = lock_contact(message.relay_contact)
    from relay_core.tickets import check_episode
    try:
        check_episode(run)
    except ValueError as exc:
        raise Superseded(str(exc)) from exc
    if not skill.enabled or str(skill.modified) != run.skill_version or contact.automation_paused or int(contact.automation_generation or 0) != int(run.generation):
        raise Superseded('Conversation or skill changed')
    if message_hash(message) != run.message_hash or not latest_message(message):
        raise Superseded('Incoming message changed or was superseded')
    resolved = context(skill, message)
    if run.get('scope_fingerprint'):
        from relay_core.ai.tools import fingerprint
        if fingerprint(resolved[2]) != run.scope_fingerprint:
            raise Superseded('Identity scope changed after event matching')
    return resolved


def process(name, *, deadline=None):
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
                decision = decide(skill, message, run.name, deadline=deadline)
                frappe.db.commit()
                run = lock_run(name)
                if run.status != 'Deciding':
                    return
                skill.reload(); message.reload()
                current(run, skill, message)
                declare_search(run, skill, message, decision)
                run.decision = json.dumps(decision)
                internal_save(run); frappe.db.commit()
            if skill.mode == 'Shadow':
                run.status = 'Shadow'; internal_save(run); frappe.db.commit(); return
            if decision['handoff']:
                handoff(run, skill, decision['reason'] or 'Outside the configured skill')
            else:
                from relay_core.flows.actions import validate_sequence
                if run.stage != 'Search':
                    validate_sequence(skill, decision.get('actions', []))
                    if decision['reply'].strip():
                        raise ValueError('Business replies require a declared EXECUTE action')
                delivery_scope(run, skill, message, decision)
                for step in range(len(decision.get('actions', []))):
                    from relay_core.flows.actions import execute_ai
                    outcome = execute_ai(run.name, step)
                    delivery_scope(run, skill, message, decision)
                    frappe.db.commit()  # Local write and journal result commit together.
                    if outcome['status'] == 'Awaiting approval':
                        return
                    if 'reply' in outcome.get('result', {}):
                        result = dispatch_reply(run, skill, message, outcome['result']['reply'], slot=f'event_reply_{step}')
                        if result['status'] != 'Submitted':
                            run = lock_run(name)
                            run.status = 'Delivering'
                            internal_save(run); frappe.db.commit(); return
                if decision.get('actions'):
                    # Execution may be slow; never dispatch using the old scope.
                    run = lock_run(name)
                    skill.reload(); message.reload()
                    delivery_scope(run, skill, message, decision)
                result = dispatch_reply(run, skill, message, decision['reply'], slot='search') if run.stage == 'Search' else {'status': 'Submitted'}
                run = lock_run(name)
                if run.status in ('Pending', 'Deciding'):
                    run.status = 'Completed' if result['status'] == 'Submitted' else 'Delivering'
                    if run.stage == 'Search' and result['status'] == 'Submitted':
                        search_delivered(run, skill)
                    internal_save(run)
            frappe.db.commit()
            if run.status == 'Pending' and run.stage == 'Event':
                return process(run.name, deadline=deadline)
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
    recheck(skill, user, business, decision.get('reads', []), scope,
        authorize=lambda contract, arguments: authorize_search(run.name, skill, contract, arguments))


def send_reply(message, reply, *, slot='reply'):
    from relay_core.automation.provenance import context_of
    context = context_of(message)
    key = action_key(message.name, slot)
    if context.get('provider') == 'Email':
        from relay_core.email import send
        subject = context.get('subject') or 'Reply'
        if not subject.lower().startswith('re:'):
            subject = 'Re: ' + subject
        return send([message.sender_endpoint], subject, reply, request_key=key,
                    message=message.name, auto_submitted=1)
    from relay_core.messaging import send
    return send(message.name, 'text', {'text': reply}, key, quote=0)


def dispatch_reply(run, skill, message, reply, *, slot):
    delivery_scope(run, skill, message)
    token = outgoing_run.set(run.name)
    try:
        result = send_reply(message, reply, **({'slot': slot} if slot != 'reply' else {}))
    finally:
        outgoing_run.reset(token)
    if result['status'] not in ('Submitted', 'Queued', 'Uncertain', 'Dispatching'):
        raise ValueError('Reply delivery requires review')
    return result


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
        steps = json.loads(run.decision or '{}').get('actions', [])
        prefix = 'email:' if action.operation == 'email' else ''
        # Explicit replies resume the persisted chain after receipt recovery.
        # A delayed receipt cannot reopen an already completed chain.
        if any(action.request_key == hashlib.sha256((prefix + run.execution_user + ':' +
                action_key(run.message, f'event_reply_{step}')).encode()).hexdigest() for step in range(len(steps))):
            if run.status != 'Completed':
                run.status = 'Pending'
                internal_save(run)
                frappe.enqueue('relay_core.automation.service.process', name=run.name, queue=QUEUE, enqueue_after_commit=True)
            frappe.db.commit()
            return
        # Delayed duplicate announcement callbacks must not complete a later reply.
        if action.request_key == search_request_key(frappe.get_doc('Relay Message', run.message), run.execution_user) and run.stage != 'Search':
            return
        run.status = 'Completed'
        if run.stage == 'Search':
            search_delivered(run, frappe.get_doc('Relay AI Skill', run.skill))
            if run.status == 'Pending':
                frappe.enqueue('relay_core.automation.service.process', name=run.name, queue=QUEUE, enqueue_after_commit=True)
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
    newer = frappe.qb.DocType('Relay Message Action').as_('newer_announcement_or_reply')
    rows = (frappe.qb.from_(run).join(action).on(run.message == action.source_message)
        .left_join(newer).on((newer.source_message == action.source_message) & (newer.name > action.name)
                            & newer.payload.like('%"automation_run":%'))
        .select(action.name).where(run.skill.isnotnull())
        .where(newer.name.isnull())
        .where(action.payload.like('%"automation_run":%'))
        .where(((run.status == 'Delivering') & action.status.isin(['Submitted', 'Rejected']))
               | ((run.status == 'Completed') & (action.status == 'Rejected')))
        .orderby(run.modified).limit(20).run(as_dict=True))
    for row in rows:
        frappe.enqueue('relay_core.ai.service.complete_delivery', action=row.name, queue=QUEUE)


def defer_handoff(name):
    frappe.db.rollback()
    run = lock_run(name)
    from relay_core.tickets import hold_episode
    if run.get('ticket'):
        actor = frappe.session.user
        try:
            frappe.set_user('Administrator')
            hold_episode(run.ticket)
        finally:
            frappe.set_user(actor)
    run.reason = 'Handoff owner unavailable; automation paused pending recovery'
    internal_save(run); frappe.db.commit()
    frappe.log_error(title='Relay handoff unavailable', message='Configure an enabled owner with conversation access')


def admit(run):
    """Match outside the drain lock, then durably select one event before tools."""
    from relay_core.ai import matching
    from relay_core.ai.tools import fingerprint
    from relay_core.automation.service import episode, triage
    deadline = time.monotonic() + 40
    message = frappe.get_doc('Relay Message', run.message)
    try:
        ticket = episode(run, message)
        from relay_core.tickets import check_episode
        try:
            check_episode(run)
        except ValueError as exc:
            raise Superseded(str(exc)) from exc
        contact = lock_contact(message.relay_contact)
        if ticket.ai_disabled or contact.automation_paused or int(contact.automation_generation or 0) != int(run.generation):
            run.status, run.reason = 'Cancelled', 'Conversation is owned by staff'
            internal_save(run); frappe.db.commit(); return
        if message_hash(message) != run.message_hash or not latest_message(message):
            raise Superseded('Incoming message changed or was superseded')
        if continue_search(run, message):
            frappe.db.commit()
            return process(run.name, deadline=deadline)
        skills = matching.candidates(message)
        contexts = {skill.name: context(skill, message) for skill in skills}
        scopes = {name: fingerprint(value[2]) for name, value in contexts.items()}
        # Only prior announcements without business reads can enter matching.
        # The existing history reader rechecks source access and the exact scope.
        history = []
        for skill in skills:
            for item in conversation_history(skill, message, *contexts[skill.name]):
                if item not in history:
                    history.append(item)
        history = history[-6:]
        while len(json.dumps(history)) > 6000:
            history.pop(0)
        versions = {skill.name: str(skill.modified) for skill in skills}
        if int(run.attempts or 0) >= 2:
            raise ValueError('Matching attempt limit reached')
        run.status, run.attempts = 'Deciding', int(run.attempts or 0) + 1
        internal_save(run); frappe.db.commit()
        result = matching.select(message, skills, run.name, deadline, history=history)
        frappe.db.commit()
        run = lock_run(run.name)
        if run.status != 'Deciding' or run.stage != 'Matching':
            return
        message.reload()
        try:
            check_episode(run)
        except ValueError as exc:
            raise Superseded(str(exc)) from exc
        contact = lock_contact(message.relay_contact)
        if (contact.automation_paused or int(contact.automation_generation or 0) != int(run.generation)
                or frappe.db.get_value('Relay Ticket', run.ticket, 'ai_disabled')
                or message_hash(message) != run.message_hash or not latest_message(message)):
            raise Superseded('Conversation changed while matching')
        fresh = matching.candidates(message)
        if versions != {s.name: str(s.modified) for s in fresh}:
            raise ValueError('Event configuration changed while matching')
        if scopes != {s.name: fingerprint(context(s, message)[2]) for s in fresh}:
            raise ValueError('Identity scope changed while matching')
        run.match_result = json.dumps(dict(result, versions=versions))
        if not result['selected']:
            triage(run, message, result['reason'])
        else:
            skill = next(s for s in fresh if s.name == result['selected'])
            run.skill, run.skill_version = skill.name, str(skill.modified)
            run.execution_user = context(skill, message)[0]
            run.scope_fingerprint = scopes[skill.name]
            run.stage, run.attempts, run.status = 'Event', 0, 'Pending'
            episode(run, message)
            if skill.execution_policy == 'Ticket only':
                run.status = 'Shadow' if skill.mode == 'Shadow' else 'Completed'
                run.reason = 'Event recorded for staff review'
            internal_save(run)
        frappe.db.commit()
    except frappe.QueryDeadlockError:
        raise
    except Superseded:
        frappe.db.rollback()
        run = lock_run(run.name)
        run.status, run.reason = 'Cancelled', 'Conversation or message changed'
        internal_save(run); frappe.db.commit(); return
    except Exception:
        frappe.db.rollback()
        run = lock_run(run.name)
        run.match_result = json.dumps(dict(selected=None, scores=[], method='failed',
                                          reason='Event matching or authorization failed'))
        triage(run, message, 'Event matching or authorization failed; review required')
        frappe.db.commit(); return
    if run.status == 'Pending' and run.stage == 'Event':
        return process(run.name, deadline=deadline)
