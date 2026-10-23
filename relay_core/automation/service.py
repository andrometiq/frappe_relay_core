"""Durable first automation slice: text -> ticket/approved reply/handoff.

Only background workers commit explicitly. Public enqueue methods rely on the
normal Frappe request transaction. Runtime writes use a private service flag;
all business reads and ticket writes still check the execution user's access.
"""
import hashlib
import json
from contextvars import ContextVar
import frappe
from frappe.utils import now_datetime, add_to_date
from relay_core.permissions import require_access
from relay_core.automation.contracts import action_key, canonical, event_key, validate_decision
from relay_core.automation.providers import complete, ProviderError


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
    policy_name = frappe.db.get_value('Relay Automation Policy', {'channel': doc.channel, 'enabled': 1}, 'name')
    if not policy_name:
        return {'status': 'Disabled'}
    policy = frappe.get_doc('Relay Automation Policy', policy_name)
    check_actor(policy)
    contact = frappe.get_doc('Relay Contact', doc.relay_contact)
    run = frappe.get_doc({'doctype': 'Relay Automation Run', 'event_key': event_key(doc.name),
        'message': doc.name, 'policy': policy.name, 'policy_version': str(policy.modified),
        'execution_user': policy.execution_user, 'status': 'Pending',
        'message_hash': message_hash(doc),
        'generation': int(contact.automation_generation or 0)})
    internal_save(run, new=True)
    frappe.enqueue('relay_core.automation.service.process', name=run.name, queue='long', timeout=180, enqueue_after_commit=True)
    return {'name': run.name, 'status': run.status}


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
    names=[policy.provider]
    fallback=policy.get('fallback_provider')
    if fallback and fallback!=policy.provider: names.append(fallback)
    for index,name in enumerate(names):
        provider=frappe.get_doc('Relay AI Provider',name)
        if not provider.enabled:
            if index+1<len(names):continue
            raise ProviderError('Provider disabled')
        reserve_attempt(policy)
        try:
            return complete(provider.provider,provider.model,provider.get_password('api_key'),prompt,**({'images':images} if images else {}))
        except ProviderError:
            if index+1==len(names):raise
    raise ProviderError('No enabled provider')


def _process(name):
    if not frappe.conf.get('relay_automation_enabled'):
        return
    original = frappe.session.user
    run = lock_run(name)
    if run.status not in ('Pending', 'Deciding') or (run.status == 'Deciding' and run.lease_until and run.lease_until > now_datetime()):
        return
    policy = frappe.get_doc('Relay Automation Policy', run.policy)
    if int(run.attempts or 0) >= 2:
        run.status = 'Handoff'; run.reason = 'AI attempt limit reached'
        internal_save(run); frappe.db.commit(); return
    run.status = 'Deciding'; run.fence = int(run.fence or 0) + 1
    run.attempts = int(run.attempts or 0) + 1
    run.lease_until = add_to_date(now_datetime(), seconds=240)
    fence = run.fence
    internal_save(run); frappe.db.commit()
    try:
        check_actor(policy)
        frappe.set_user(run.execution_user)
        message, contact, person, channel, doctype, business = scope(run, policy)
        allowed = replies(policy, channel) if policy.allow_reply else {}
        from relay_core.automation.multimodal import context as media_context
        input_text, images = media_context(policy,message,run)
        from relay_core.learning.service import prompt as learning_prompt, published_instructions
        prompt = learning_prompt(policy, allowed, input_text, published_instructions(policy))
        decision = validate_decision(complete_with_fallback(policy, prompt, **({'images':images} if images else {})), allowed, allow_ticket=bool(policy.allow_ticket), allow_report=bool(policy.get("allow_report")))
        if not decision['reply'] and policy.allow_reply and policy.fallback_reply in allowed:
            decision['reply'] = policy.fallback_reply; decision['handoff'] = True
        # End the read snapshot before rechecking policy/permissions after inference.
        frappe.db.commit()
        apply(name, fence, decision, allowed)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        current = lock_run(name)
        if current.status == 'Deciding' and current.fence == fence:
            current.status = 'Handoff'; current.reason = 'Decision or authorization failed; review required'
            internal_save(current); frappe.db.commit()
    finally:
        frappe.set_user(original)


def apply(name, fence, decision, previous_replies):
    run = lock_run(name)
    if run.status != 'Deciding' or run.fence != fence or run.lease_until <= now_datetime():
        raise ValueError('Stale worker')
    policy = frappe.get_doc('Relay Automation Policy', run.policy)
    message = frappe.get_doc('Relay Message', run.message)
    lock_contact(message.relay_contact)
    message, contact, person, channel, doctype, business = scope(run, policy)
    allowed = replies(policy, channel) if policy.allow_reply else {}
    decision = validate_decision(decision, allowed, allow_ticket=bool(policy.allow_ticket), allow_report=bool(policy.get("allow_report")))
    if decision['reply'] and allowed[decision['reply']] != previous_replies.get(decision['reply']):
        raise ValueError('Reply changed during decision')
    run.decision = canonical(decision)
    if policy.mode == 'Shadow':
        run.status = 'Shadow'; internal_save(run); return
    if decision.get('create_report'):
        from relay_core.reports import preview
        report = preview(doctype,business)
        run.report_scope = canonical({'doctype':doctype,'name':business,'count':report['count']})
    if decision['create_ticket']:
        ticket = frappe.get_doc({'doctype': 'Relay Ticket', 'subject': decision['brief'][:140],
            'brief': decision['brief'], 'category': decision['category'], 'status': 'Open',
            'source_action_key': action_key(run.message, 'ticket'), 'messages': [{'message': run.message}]})
        ticket.insert()
        run.ticket = ticket.name
    if decision['reply'] and (channel.channel!='WhatsApp' or not message.sender_endpoint):
        decision['reply'] = None; decision['handoff'] = True
        run.reason = 'Automatic channel reply is unavailable'
    if decision['reply']:
        body = allowed[decision['reply']]['body']
        from relay_core.whatsapp import prepare
        arguments={'body':body};payload=prepare('messages.send',arguments,person.name,doctype,business)
        if not message.sender_endpoint or payload['to']!=message.sender_endpoint:raise ValueError('Sender endpoint does not match the resolved recipient')
        submission={'key':action_key(run.message,'reply'),'operation':'messages.send','arguments':arguments,
            'contact':person.name,'business_doctype':doctype,'business_name':business}
        encoded = canonical(submission)
        internal_save(frappe.get_doc({'doctype': 'Relay Automation Outbox', 'run': run.name,
            'action_key': submission['key'], 'payload': encoded, 'payload_hash': hashlib.sha256(encoded.encode()).hexdigest(),
            'recipient': message.sender_endpoint, 'reply': decision['reply'], 'reply_version': allowed[decision['reply']]['version'],
            'status': 'Pending'}), new=True)
        frappe.enqueue('relay_core.automation.service.recover', queue='long', enqueue_after_commit=True)
    run.decision = canonical(decision)
    run.status = 'Handoff' if decision['handoff'] else 'Completed'
    internal_save(run)
    if decision['handoff']:
        contact.automation_paused = 1
        # The current acknowledgement may dispatch; takeover endpoint cancels older intents separately.
        contact.save(ignore_permissions=True)


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
        frappe.enqueue('relay_core.automation.service.process', name=row.name, queue='long', timeout=180)
    for row in frappe.get_all('Relay Automation Outbox', filters={'status': 'Pending'}, fields=['name'], limit_page_length=20, order_by='creation asc'):
        frappe.enqueue('relay_core.automation.service.dispatch', name=row.name, queue='long', timeout=90)


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
