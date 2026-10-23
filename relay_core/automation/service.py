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
        'context': parsed(message.get('provider_context')), 'data': parsed(message.get('message_data'))}).encode()).hexdigest()


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
    rows = frappe.get_list('Relay Message', filters=filters, fields=['name'], order_by='name desc', page_length=1)
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


def create_run(doc):
    if doc.get('legacy_source') or doc.direction != 'Incoming' or not frappe.conf.get('relay_automation_enabled'):
        return {'status': 'Ignored'}
    try:
        if frappe.get_doc('Relay Channel',doc.channel).channel!='WhatsApp':return {'status':'Ignored'}
    except frappe.DoesNotExistError:return {'status':'Ignored'}
    # Lock the source message to serialize initial event replay.
    frappe.db.get_value('Relay Message', doc.name, 'name', for_update=True)
    existing = frappe.db.get_value('Relay Automation Run', {'event_key': event_key(doc.name)}, ['name', 'status'], as_dict=True)
    if existing:
        return dict(existing)
    from relay_core.ai.service import skill_for, create_run as create_skill_run
    skill = skill_for(doc)
    if skill:
        return create_skill_run(doc, skill)
    return {'status': 'Disabled'}


@after_message_commit
def on_message(doc, method=None):
    if frappe.conf.get('relay_automation_enabled'):
        from relay_core.flows.service import claims
        if claims(doc):
            return
        create_run(doc)


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
    rows = frappe.get_list('Relay Automation Run', filters=filters,
        fields=['name', 'message', 'status', 'ticket', 'reason', 'creation'],
        order_by='name desc' if before else 'name asc', page_length=51, **options)
    more = len(rows) > 50; rows = rows[:50]
    if before: rows.reverse()
    delivery = {}
    if rows:
        delivery = {row.run: row.status for row in frappe.get_list('Relay Automation Outbox', filters={'run': ['in', [row.name for row in rows]]}, fields=['run', 'status'], page_length=50)}
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
