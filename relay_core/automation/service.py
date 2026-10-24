"""Durable skill scheduling and compatibility for existing automation outboxes.

Only background workers commit explicitly. Public enqueue methods rely on the
normal Frappe request transaction. Runtime writes use a private service flag;
all business reads and ticket writes still check the execution user's access.
"""
import hashlib
import json
from contextvars import ContextVar
import frappe
from relay_core.automation.queue import QUEUE, after_message_commit
from frappe.utils import now_datetime, add_to_date
from relay_core.permissions import require_access
from relay_core.automation.contracts import canonical, event_key
from relay_core.automation.providers import ProviderError


outgoing_run = ContextVar('relay_automation_outgoing_run', default=None)


def internal_save(doc, new=False):
    previous = getattr(frappe.flags, 'relay_automation_internal', False)
    frappe.flags.relay_automation_internal = True
    try:
        return doc.insert(ignore_permissions=True) if new else doc.save(ignore_permissions=True)
    finally:
        frappe.flags.relay_automation_internal = previous


def lock_run(name):
    frappe.db.get_value('Relay Automation Run', name, 'name', for_update=True)
    return frappe.get_doc('Relay Automation Run', name)


def lock_contact(name):
    frappe.db.get_value('Relay Contact', name, 'name', for_update=True)
    return frappe.get_doc('Relay Contact', name)


def check_actor(policy):
    user = policy.execution_user
    if user in ('Guest', 'Administrator') or not frappe.db.get_value('User', user, 'enabled'):
        raise ValueError('Execution identity is disabled')
    roles = frappe.get_roles(user)
    if 'System Manager' in roles or 'Relay Communication Manager' not in roles:
        raise ValueError('Execution identity is not permitted')


def message_hash(message):
    def parsed(value):
        if isinstance(value, str):
            try: return json.loads(value)
            except ValueError: return value
        return value
    return hashlib.sha256(canonical({'content': message.content, 'type': message.message_type,
        'context': parsed(message.get('provider_context')), 'data': parsed(message.get('message_data')),
        'business': [message.get('business_doctype'), message.get('business_name')],
        'destination': [message.get('relay_contact'), message.get('channel'), message.get('sender_endpoint'), message.get('conversation_key')]}).encode()).hexdigest()


def business_scope(policy, contact, message=None):
    """Recheck business and channel access at decision and delivery time."""
    business_contact = frappe.get_doc('Contact', contact.contact)
    business_contact.check_permission('read')
    from relay_core.business_access import reference,candidates
    target=reference(message) if message else None
    if not target:
        links={(link.link_doctype,link.link_name) for link in business_contact.links
               if link.link_doctype==policy.business_doctype}
        target=next(iter(links)) if len(links)==1 else None
    if not target or target not in candidates(contact.name):
        raise ValueError('Business identity is missing or ambiguous')
    doctype,name=target
    if doctype!=policy.business_doctype:raise ValueError('Message does not match the policy business type')
    frappe.get_doc(doctype, name).check_permission('read')
    channel = frappe.get_doc('Relay Channel', policy.channel)
    channel.check_permission('read')
    if not channel.enabled or channel.channel!='WhatsApp':
        raise ValueError('Automation currently requires WhatsApp')
    return business_contact, channel, doctype, name


def latest_message(message):
    filters = {'relay_contact': message.relay_contact, 'channel': message.channel, 'direction': 'Incoming'}
    if message.get('conversation_key'):
        filters['conversation_key'] = message.conversation_key
    elif message.sender_endpoint:
        filters['sender_endpoint'] = message.sender_endpoint
    if message.get('business_doctype') and message.get('business_name'):
        filters.update(business_doctype=message.business_doctype, business_name=message.business_name)
    # Supersession is internal coordination, including during admission by an
    # ingress-only user. Content and business reads have separate scope checks.
    # A newer message must cancel this turn even if the actor cannot read it.
    rows = frappe.get_all('Relay Message', filters=filters, fields=['name'], order_by='name desc', limit_page_length=1)
    return bool(rows and rows[0].name == message.name)


def scope(run, policy):
    if not policy.enabled or str(policy.modified) != run.policy_version:
        raise ValueError('Policy changed or disabled')
    check_actor(policy)
    message = frappe.get_doc('Relay Message', run.message)
    message.check_permission('read')
    if run.get('message_hash') and run.message_hash != message_hash(message):
        raise ValueError('Source message changed since automation was queued')
    kind=message.message_type
    if kind not in (None, '', 'text') and not (kind in ('photo','image') and policy.get('allow_images') or kind in ('voice','audio') and policy.get('allow_voice')):
        raise ValueError('Media requires an enabled vision/voice policy')
    if message.direction != 'Incoming' or message.channel != policy.channel:
        raise ValueError('Message does not match policy')
    if not latest_message(message):
        raise ValueError('A newer incoming message superseded this turn')
    contact = frappe.get_doc('Relay Contact', message.relay_contact)
    contact.check_permission('read')
    if contact.automation_paused or int(contact.automation_generation or 0) != int(run.generation):
        raise ValueError('Conversation ownership changed')
    endpoint_key = hashlib.sha256((message.channel + ':' + (message.sender_endpoint or '')).encode()).hexdigest()
    endpoint = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': endpoint_key, 'verified': 1}, 'relay_contact')
    if endpoint != contact.name:
        raise ValueError('Endpoint verification is missing or revoked')
    business_contact,channel,doctype,name=business_scope(policy,contact,message)
    return message, contact, business_contact, channel, doctype, name


def replies(policy, channel):
    result = {}
    for name in (policy.reply_ids or '').splitlines():
        row = frappe.get_doc('Relay Canned Reply', name)
        if row.published and row.ai_enabled and row.channel == channel.channel:
            result[name] = {'body': row.body, 'language': row.language, 'version': str(row.modified)}
    if len(result) > 20:
        raise ValueError('Reply limit exceeded')
    return result


@frappe.whitelist(methods=['POST'])
def enqueue(message):
    require_access(manage=True)
    doc = frappe.get_doc('Relay Message', message)
    doc.check_permission('read')
    return create_run(doc)


def episode(run, message, skill=None):
    """Create the assigned episode before either flows or event tools execute."""
    from relay_core.tickets import ensure_episode, triage_owner
    actor = frappe.session.user
    try:
        frappe.set_user('Administrator')
        channel = frappe.get_doc('Relay Channel', message.channel)
        owner = triage_owner(channel, message)
        ticket = ensure_episode(message, owner=owner, skill=skill, run=run)
        return ticket
    finally:
        frappe.set_user(actor)


def triage(run, message, reason):
    run.reason = reason[:500]
    try:
        episode(run, message)
    except (ValueError, frappe.PermissionError, frappe.ValidationError):
        # The run is the durable intent when the configured owner loses access.
        run.stage, run.status = 'Triage', 'Pending'
        run.reason = 'Triage owner unavailable; review required'
    else:
        contact = lock_contact(message.relay_contact)
        if not contact.automation_paused:
            contact.automation_paused = 1
            contact.automation_generation = int(contact.automation_generation or 0) + 1
            contact.save(ignore_permissions=True)
        run.stage, run.status = 'Triage', 'Handoff'
    internal_save(run)


def configuration_failure(message, error):
    """Drain failures retain a ticket or a recoverable triage intent."""
    doc = frappe.get_doc('Relay Message', message, for_update=True)
    existing = frappe.db.get_value('Relay Automation Run', {'event_key': event_key(message)}, 'name', for_update=True)
    run = frappe.get_doc('Relay Automation Run', existing, for_update=True) if existing else frappe.get_doc({
        'doctype': 'Relay Automation Run', 'event_key': event_key(message),
        'message': message, 'execution_user': frappe.session.user, 'message_hash': message_hash(doc)})
    if existing and run.status not in ('Pending', 'Deciding'):
        return
    if not existing:
        internal_save(run, new=True)
    triage(run, doc, 'Automation configuration requires review')


def create_run(doc):
    """The sole admission transaction for automatic inbound handlers and APIs."""
    if doc.get('legacy_source') or doc.direction != 'Incoming':
        return {'status': 'Ignored'}
    from relay_core.flows.service import claims, create_event
    from relay_core.ai.matching import human_request
    from relay_core.email_preferences import automatic_allowed, automatic_reply_exists
    from relay_core.automation.provenance import context_of
    # A shared source lock serializes flow/API/drain replay and email rules.
    frappe.db.get_value('Relay Message', doc.name, 'name', for_update=True)
    existing = frappe.db.get_value('Relay Automation Run', {'event_key': event_key(doc.name)}, ['name', 'status'], as_dict=True, for_update=True)
    if existing:
        return dict(existing)
    provenance = context_of(doc)
    if not automatic_allowed(provenance) or provenance.get('provider') == 'Email' and automatic_reply_exists(doc):
        return {'status': 'Ignored'}
    flow = claims(doc) and not human_request(doc.content)
    if not flow and not frappe.conf.get('relay_automation_enabled'):
        return {'status': 'Disabled'}
    contact = lock_contact(doc.relay_contact)
    run = frappe.get_doc({'doctype': 'Relay Automation Run', 'event_key': event_key(doc.name),
        'message': doc.name, 'execution_user': frappe.session.user, 'message_hash': message_hash(doc),
        'status': 'Pending', 'stage': 'Matching', 'generation': int(contact.automation_generation or 0)})
    internal_save(run, new=True)
    try:
        ticket = episode(run, doc)
    except (ValueError, frappe.PermissionError, frappe.ValidationError):
        triage(run, doc, 'Episode admission requires review')
        return {'name': run.name, 'status': run.status}
    if flow and not contact.automation_paused and not ticket.ai_disabled and frappe.conf.get('relay_automation_enabled'):
        from relay_core.ai.service import continue_search
        try:
            flow = not continue_search(run, doc)
        except (ValueError, frappe.PermissionError, frappe.ValidationError):
            triage(run, doc, 'Search confirmation or authorization failed; review required')
            return {'name': run.name, 'status': run.status}
    if contact.automation_paused or ticket.ai_disabled:
        run.status, run.reason = 'Cancelled', 'Conversation is owned by staff'
    elif human_request(doc.content):
        triage(run, doc, 'Sender requested a person')
    elif flow:
        create_event(doc)
        run.stage, run.status = 'Flow', 'Completed'
    else:
        frappe.enqueue('relay_core.automation.service.process', name=run.name, queue=QUEUE,
                       timeout=90, enqueue_after_commit=True)
    internal_save(run)
    return {'name': run.name, 'status': run.status}


@after_message_commit
def on_message(doc, method=None):
    return create_run(doc)


def reserve_attempt(policy):
    key=frappe.cache().make_key(f'relay-ai-budget:{policy.name}:{now_datetime().date()}')
    count=frappe.cache().incr(key)
    if count==1:frappe.cache().expire(key,172800)
    if count>int(policy.daily_limit):raise ValueError('Daily AI limit reached')


def complete_with_fallback(policy, prompt, images=None):
    """Keep the legacy task entry point while routing through the shared AI Model."""
    from relay_core.ai.adapter import complete_json
    if images or not policy.get('ai_model'):
        raise ProviderError('Choose an AI Model; image tasks are not supported by this adapter')
    reserve_attempt(policy)
    return complete_json(policy.ai_model, prompt)


def _process(name):
    if not frappe.conf.get('relay_automation_enabled'):
        return
    run = lock_run(name)
    if run.status not in ('Pending', 'Deciding'):
        return
    if run.get('stage') == 'Triage':
        triage(run, frappe.get_doc('Relay Message', run.message), run.reason)
        frappe.db.commit()
        return
    if run.get('stage') == 'Matching':
        from relay_core.ai.service import admit
        return admit(run)
    if run.get('skill'):
        from relay_core.ai.service import process as process_skill
        return process_skill(name)
    # Existing provider-backed runs remain readable and receive a human owner.
    policy = frappe.get_doc('Relay Automation Policy', run.policy)
    if policy.mode == 'Shadow':
        run.status = 'Shadow'; run.reason = 'Configure a Relay AI Skill to replace the legacy policy'
        internal_save(run)
    else:
        from relay_core.ai.handoff import handoff
        handoff(run, policy, 'Configure a Relay AI Skill to replace the legacy policy')
    frappe.db.commit()


def dispatch(name):
    from relay_core.messaging import send
    original = frappe.session.user
    frappe.db.get_value('Relay Automation Outbox', name, 'name', for_update=True)
    out = frappe.get_doc('Relay Automation Outbox', name)
    if out.status != 'Pending':
        return
    run = frappe.get_doc('Relay Automation Run', out.run)
    try:
        policy = frappe.get_doc('Relay Automation Policy', run.policy)
        check_actor(policy); frappe.set_user(run.execution_user)
        message = frappe.get_doc('Relay Message', run.message)
        message.check_permission('read')
        if run.get('message_hash') and run.message_hash != message_hash(message):
            out.status = 'Cancelled'; internal_save(out); frappe.db.commit(); return
        contact = lock_contact(message.relay_contact)
        if not frappe.conf.get('relay_automation_enabled') or not policy.enabled or str(policy.modified) != run.policy_version or int(contact.automation_generation or 0) != int(run.generation):
            out.status = 'Cancelled'; internal_save(out); frappe.db.commit(); return
        contact.check_permission('read')
        endpoint_key = hashlib.sha256((message.channel + ':' + (message.sender_endpoint or '')).encode()).hexdigest()
        if frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': endpoint_key, 'verified': 1}, 'relay_contact') != contact.name:
            out.status = 'Cancelled'; internal_save(out); frappe.db.commit(); return
        if not latest_message(message):
            out.status = 'Cancelled'; internal_save(out); frappe.db.commit(); return
        if hashlib.sha256(out.payload.encode()).hexdigest() != out.payload_hash:
            out.status = 'Conflict'; internal_save(out); frappe.db.commit(); return
        submission = json.loads(out.payload)
        person, channel, doctype, business = business_scope(policy, contact, message)
        if (submission.get('contact') != person.name
                or submission.get('business_doctype') != doctype
                or submission.get('business_name') != business
                or message.channel != channel.name
                or submission.get('channel', 'WhatsApp') != channel.channel):
            out.status = 'Cancelled'; internal_save(out); frappe.db.commit(); return
        reply = frappe.get_doc('Relay Canned Reply', out.reply)
        if submission.get('operation')!='messages.send' or submission.get('arguments')!={'body':reply.body}:
            out.status = 'Cancelled'; internal_save(out); frappe.db.commit(); return
        out.result = canonical({'journal':'message_action'})
        out.status = 'Dispatching'; out.attempts = int(out.attempts or 0) + 1
        out.lease_until = add_to_date(now_datetime(), seconds=120)
        internal_save(out); frappe.db.commit()
        # Business linkage was rechecked in Core before starting network delivery.
        reply = frappe.get_doc('Relay Canned Reply', out.reply)
        if not reply.ai_enabled or not reply.published or str(reply.modified) != out.reply_version:
            out.reload(); out.status = 'Cancelled'; internal_save(out); frappe.db.commit(); return
        from relay_core.whatsapp import prepare
        resolved=prepare(**{k:v for k,v in submission.items() if k!='key'})
        if resolved.get('to')!=out.recipient:out.reload();out.status='Cancelled';internal_save(out);frappe.db.commit();return
        token = outgoing_run.set(run.name)
        try: result=send(message.name, 'text', {'text': reply.body}, submission['key'], quote=0)
        finally: outgoing_run.reset(token)
        out.reload(); out.status = 'Submitted' if result['status'] == 'Submitted' else 'Uncertain'; out.result = canonical(result)
        internal_save(out); frappe.db.commit()
    except Exception as exc:
        frappe.db.rollback(); out.reload()
        if out.status == 'Dispatching':
            out.status = 'Uncertain'; internal_save(out); frappe.db.commit()
        elif out.status == 'Pending' and isinstance(exc, (ValueError, frappe.PermissionError, frappe.DoesNotExistError)):
            out.status = 'Cancelled'; internal_save(out); frappe.db.commit()
    finally:
        frappe.set_user(original)


def recover():
    from relay_core.automation.queue import recover as recover_messages
    recover_messages()
    from relay_core.ai.service import recover_deliveries
    recover_deliveries()
    if not frappe.conf.get('relay_automation_enabled'):
        return
    # Core owns delivery recovery; the outbox follows its action without resending.
    for row in frappe.get_all('Relay Automation Outbox', filters={'status':['in',['Dispatching','Uncertain']]}, fields=['name'], limit_page_length=20, order_by='modified asc'):
        frappe.db.get_value('Relay Automation Outbox', row.name, 'name', for_update=True)
        out = frappe.get_doc('Relay Automation Outbox', row.name)
        if out.status == 'Dispatching' and out.lease_until >= now_datetime(): continue
        run = frappe.get_doc('Relay Automation Run', out.run)
        key = hashlib.sha256((run.execution_user + ':' + json.loads(out.payload)['key']).encode()).hexdigest()
        action = frappe.db.get_value('Relay Message Action', {'request_key':key}, ['name','status','outbound_message'], as_dict=True)
        if action:
            out.status = 'Submitted' if action.status == 'Submitted' else 'Uncertain'
            out.result = canonical({'action':action.name,'status':action.status,'message':action.outbound_message})
        elif json.loads(out.result or '{}').get('journal') == 'message_action':
            out.status = 'Pending'
        else:
            out.status = 'Uncertain'
        internal_save(out)
    for row in frappe.get_all('Relay Automation Run', filters={'status': ['in', ['Pending', 'Deciding']]}, fields=['name'], limit_page_length=20, order_by='creation asc'):
        frappe.enqueue('relay_core.automation.service.process', name=row.name, queue=QUEUE, timeout=180)
    for row in frappe.get_all('Relay Automation Outbox', filters={'status': 'Pending'}, fields=['name'], limit_page_length=20, order_by='creation asc'):
        frappe.enqueue('relay_core.automation.service.dispatch', name=row.name, queue=QUEUE, timeout=90)


@frappe.whitelist(methods=['POST'])
def takeover(contact, paused=1):
    require_access(manage=True)
    if str(paused) not in ('0', '1'):
        frappe.throw('Paused must be 0 or 1')
    from relay_core.permissions import readable_contact
    readable_contact(contact)
    doc = lock_contact(contact); doc.check_permission('read')
    doc.automation_generation = int(doc.automation_generation or 0) + 1
    doc.automation_paused = int(paused)
    doc.save(ignore_permissions=True)
    return {'paused': doc.automation_paused, 'generation': doc.automation_generation}


def process(name):
    # Two bounded model slots per site, one worker per run; database fencing
    # remains authoritative if a Redis lease expires.
    cache = frappe.cache()
    for slot in range(2):
        lease = cache.lock(cache.make_key(f'relay-ai-slot:{slot}'), timeout=240, blocking_timeout=0)
        if lease.acquire(blocking=False):
            try:
                run_lease = cache.lock(cache.make_key(f'relay-ai-run:{name}'), timeout=240, blocking_timeout=0)
                if not run_lease.acquire(blocking=False):
                    return
                try:
                    return _process(name)
                finally:
                    try:
                        run_lease.release()
                    except Exception:
                        pass
            finally:
                try:
                    lease.release()
                except Exception:
                    pass
    # Durable Pending run is recovered later; no busy waiting or dropped event.


@frappe.whitelist(methods=['GET'])
def runs(query='', before=None, after=None):
    require_access(manage=True)
    from relay_core.api import validate_reference
    if not isinstance(query, str) or len(query) > 80 or before and after:
        frappe.throw('Invalid run search')
    filters = {}
    for value in (before, after):
        if value is not None:
            validate_reference(value, 'AR')
    if before or after:
        filters['name'] = ['<' if before else '>', before or after]
    options = {}
    if query.strip():
        pattern = '%' + '%'.join('\\' + c if c in '%_\\' else c for c in query.strip()) + '%'
        options['or_filters'] = [[field, 'like', pattern] for field in ('name', 'status', 'message')]
    rows = frappe.get_all('Relay Automation Run', filters=filters,
        fields=['name', 'message', 'status', 'ticket', 'reason', 'creation'],
        order_by='name desc' if before else 'name asc', page_length=51, **options)
    more = len(rows) > 50; rows = rows[:50]
    if before: rows.reverse()
    delivery = {}
    if rows:
        delivery = {row.run: row.status for row in frappe.get_all('Relay Automation Outbox', filters={'run': ['in', [row.name for row in rows]]}, fields=['run', 'status'], page_length=50)}
    from relay_core.permissions import readable_contact
    items=[]
    for row in rows:
        try:
            message=frappe.get_doc('Relay Message',row.message);message.check_permission('read')
            readable_contact(message.relay_contact)
        except frappe.PermissionError:continue
        transcript=frappe.db.get_value('Relay Automation Run',row.name,'transcript')
        items.append(dict(row,id=row.name,delivery=delivery.get(row.name,'No reply'),transcript=transcript,has_report=bool(frappe.db.get_value('Relay Automation Run',row.name,'report_scope'))))
    return {'items': items,
        'previous': {'before': rows[0].name} if rows and (more if before else bool(after)) else None,
        'next': {'after': rows[-1].name} if rows and (bool(before) if before else more) else None}
