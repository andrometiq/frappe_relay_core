"""Verified Hub events -> bounded, deduplicated Core message projection."""
import hashlib
import json
import time
from datetime import timezone
import frappe
from relay_core.automation.provenance import conversation_key, telegram_message, email_context
from relay_core.message_types import normalize, preview, referral
from relay_core.message_updates import apply_updates, provider_key
from relay_core.inbound import retry_callback


def extract_messages(payload):
    if payload.get('channel') in ('Telegram', 'Email'):
        if payload.get('direction') != 'inbound':
            return []
        provider_id, sender, body = (payload.get(k) for k in ('provider_id', 'sender', 'body'))
        if not isinstance(provider_id, str) or not 1 <= len(provider_id) <= 300:
            raise ValueError('Invalid provider identity')
        if not isinstance(sender, str) or not 1 <= len(sender) <= 200:
            raise ValueError('Invalid sender identity')
        if not isinstance(body, str):
            raise ValueError('Invalid message body')
        row = {'id': provider_id, 'from': sender, 'type': 'text', 'text': {'body': body}}
        if payload['channel'] == 'Telegram':
            context = telegram_message(payload)
            if context == {}:
                return []
            if context is not None:
                row['provider_context'] = context
                row['type'] = context.get('message_type', 'text')
                raw = payload['payload']['message']
                row['message_data'] = normalize(row['type'], raw.get(row['type'], {}), provider='Telegram', body=body)
        if payload['channel']=='Email':
            from relay_core.email import recipients
            from relay_core.identity import normalize as normalize_identity
            raw=payload.get('payload') or {}
            row['from']=normalize_identity('Email', sender)
            row['provider_context']=email_context(raw, payload.get('subject',''), provider_id)
            row['message_data']={'kind':'text','text':body,'email':{'subject':payload.get('subject',''),'html':raw.get('html',''),'attachments':raw.get('attachments',[]),
                'to':recipients(raw.get('to')), 'cc':recipients(raw.get('cc'))}}
        return [row]
    result = []
    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value', {})
            for message in value.get('messages', []):
                if len(result) >= 50:
                    raise ValueError('Message projection batch exceeds limit')
                if not isinstance(message, dict) or not isinstance(message.get('id'), str):
                    raise ValueError('Invalid incoming message')
                row = dict(message, **{'from': whatsapp_sender(message)})
                if not 1 <= len(message['id']) <= 300 or not isinstance(row['from'], str) or not 1 <= len(row['from']) <= 200:
                    raise ValueError('Invalid incoming identity')
                if message.get('type') in ('reaction', 'edit', 'revoke'):
                    continue  # Applied to the original message, never inserted as a new turn.
                context = {'provider': 'WhatsApp', 'participant_id': row['from'], 'message_id': message['id'],
                           'reply_to_message_id': (message.get('context') or {}).get('id')}
                row['provider_context'] = context
                if message.get('group_id'):
                    group_id = message['group_id']
                    if not isinstance(group_id, str) or not 1 <= len(group_id) <= 200:
                        raise ValueError('Invalid WhatsApp group identity')
                    row['from'] = group_id
                    context['group_id'] = group_id
                kind = message.get('type', 'unsupported'); detail = message.get(kind, {})
                row['message_data'] = normalize(kind, detail, provider='WhatsApp', errors=message.get('errors'),
                    body=(detail.get('body') if kind == 'text' else detail.get('caption', '')) if isinstance(detail, dict) else '')
                if isinstance(message.get('referral'), dict):
                    row['message_data']['referral'] = referral(message['referral'])
                result.append(row)
    return result


def whatsapp_sender(message):
    """Phone first; a username user has only a business-scoped user ID."""
    system = message.get('system') if isinstance(message.get('system'), dict) else {}
    return message.get('from') or message.get('from_user_id') or system.get('previous_user_id') or system.get('user_id')


def set_status(name, status):
    frappe.db.set_value('Relay Hub Event', name, 'projection_status', status)
    from relay_core.realtime import incoming_changed
    incoming_changed()


def project(name, business_overrides=None):
    frappe.db.get_value('Relay Hub Event', name, 'name', for_update=True)
    event = frappe.get_doc('Relay Hub Event', name)
    if event.projection_status not in ('Pending', 'Uncategorized', None, ''):
        return
    try:
        payload = json.loads(event.payload)
        if not isinstance(payload, dict):
            raise ValueError('Invalid payload')
        medium = payload.get('channel', 'WhatsApp')
        if medium not in ('WhatsApp', 'Telegram', 'Email'):
            raise ValueError('Unsupported channel')
    except (ValueError, TypeError):
        set_status(name, 'Failed'); return
    if 'channel_statuses' in payload:
        from relay_core.channel_statuses import project_batch
        project_batch(event, payload['channel_statuses'])
        return
    channels = frappe.get_all('Relay Channel', filters={'account': event.account, 'channel': medium, 'enabled': 1}, pluck='name', limit_page_length=2)
    if len(channels) != 1:
        set_status(name, 'Uncategorized'); return
    channel = channels[0]
    try:
        from relay_core.whatsapp_templates import project as project_templates
        template_update = project_templates(payload, event) if medium == 'WhatsApp' else False
        incoming = extract_messages(payload)
        update_status = apply_updates(payload, channel, event)
        from relay_core.call_records import ingest as ingest_calls
        if medium == "WhatsApp" and ingest_calls(payload,channel):update_status="Uncategorized"
    except (ValueError, TypeError, AttributeError):
        set_status(name, 'Failed'); return
    unresolved = update_status == 'Uncategorized'
    decisions = json.loads(event.get('routing_decisions') or '{}')
    from relay_core.tickets import ensure_episode, source_episode, triage_owner
    for position, row in enumerate(incoming):
        key = hashlib.sha256((event.account + ':' + channel + ':' + row['id']).encode()).hexdigest()
        context = row.get('provider_context', {})
        message_key = provider_key(channel, row['from'], context.get('message_id') or row['id'])
        if frappe.db.exists('Relay Message', {'source_key': key}) or frappe.db.exists('Relay Message', {'provider_message_key': message_key}):
            continue
        endpoint_key = hashlib.sha256((channel + ':' + row['from']).encode()).hexdigest()
        contact = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': endpoint_key, 'verified': 1}, 'relay_contact')
        if not contact:
            decisions[row['id']] = 'triage_unverified'
            ensure_episode(event=event, channel=channel, row=row)
            unresolved = True; continue
        from relay_core.business_routing import resolve
        was_triage = decisions.get(row['id'], '').startswith('triage_')
        business, rule = resolve(contact, channel, row['from'], context, row, event,
                                 (business_overrides or {}).get(row['id']), position=position)
        decisions[row['id']] = rule
        context['business_rule'] = rule
        if not business:
            ensure_episode(event=event, channel=channel, row=row)
            unresolved = True
            continue
        kind = row.get('type', 'unknown')
        detail = row.get(kind, {})
        text = detail.get('body', '') if kind == 'text' and isinstance(detail, dict) else '[Attachment or unsupported message type]'
        if not isinstance(text, str) or len(text) > 12000:
            text = '[Message exceeds automation input limit]'; kind = 'unsupported'
        data = row.get('message_data') or {'kind': kind, 'text': text}
        if kind != 'unsupported' or data.get('unsupported'):
            text = preview(data)
        if data.get('kind') in ('system', 'unsupported'):
            kind = data['kind']
        if kind in ('interactive','button') and data.get('kind')=='text' and rule != 'sender_choice':
            context['original_message_type']=kind;kind='text'
        from relay_core.timeline import provider_time
        _, source_action = source_episode(channel, row)
        ticket = frappe.db.get_value('Relay Ticket', {'source_action_key': source_action}, 'name')
        if was_triage and not ticket:
            intent = ensure_episode(event=event, channel=channel, row=row)
            if not intent:
                decisions[row['id']] = 'triage_owner_unavailable'
                unresolved = True
                continue
            ticket = intent.name
        message = frappe.get_doc({'doctype': 'Relay Message', 'relay_contact': contact, 'channel': channel,
            'business_doctype': business[0], 'business_name': business[1],
            'direction': 'Incoming', 'status': 'Delivered', 'sent_at': provider_time(payload, row), 'content': text, 'sender_endpoint': row['from'], 'source_key': key,
            'provider_id': row['id'], 'message_type': kind,
            'provider_context': json.dumps(context, sort_keys=True),
            'message_data': json.dumps(data, ensure_ascii=False), 'provider_message_key': message_key,
            'conversation_key': conversation_key(channel, row['from'], context), 'ticket': ticket})
        if ticket:
            frappe.db.savepoint('triage_projection')
            actor = frappe.session.user
            try:
                frappe.set_user('Administrator')
                owner = triage_owner(frappe.get_doc('Relay Channel', channel), message)
                if not owner:
                    raise ValueError('Triage owner unavailable')
                message.insert(ignore_permissions=True)
                ensure_episode(message, owner=owner)
            except (ValueError, frappe.PermissionError, frappe.ValidationError):
                frappe.db.rollback(save_point='triage_projection')
                decisions[row['id']] = 'triage_scope_or_owner_conflict'
                unresolved = True
                continue
            finally:
                frappe.set_user(actor)
        else:
            message.insert(ignore_permissions=True)
    frappe.db.set_value('Relay Hub Event', name, 'routing_decisions', json.dumps(decisions, sort_keys=True))
    frappe.db.set_value('Relay Hub Event', name, 'projection_status', 'Uncategorized' if unresolved else 'Projected' if incoming or template_update or update_status == 'Projected' else 'Ignored')
    from relay_core.realtime import changed
    changed(event)
    if medium == 'Telegram':
        from relay_core.telegram_topics import observe
        try:observe(payload, channel)
        except (ValueError, TypeError):pass  # Invalid topic metadata cannot alter message routing.


def on_event(doc, method=None):
    if doc.flags.get('relay_inline_projection'):
        started = time.perf_counter_ns()
        project(doc.name)
        doc.flags.relay_projection_ms = (time.perf_counter_ns() - started) / 1e6
        return
    frappe.db.after_commit.add(lambda: enqueue_projection(doc.name, doc.payload, doc.flags.get('relay_received_ns')))


def enqueue_projection(name, payload, received_ns=None):
    frappe.enqueue('relay_core.automation.projection.project_queued', name=name, queue=projection_queue(payload),
        submitted_ns=time.time_ns(), received_ns=received_ns)


@retry_callback
def project_queued(name, submitted_ns, received_ns=None):
    from rq import get_current_job
    started = time.time_ns()
    monotonic = time.monotonic_ns()
    job = get_current_job()
    project(name)
    if job:
        def completed():
            finished = time.monotonic_ns()
            timing = {'projection_ms': (finished - monotonic) / 1e6,
                      'started_ns': monotonic, 'finished_ns': finished,
                      'receive_to_enqueue_ms': (submitted_ns - received_ns) / 1e6 if received_ns else None}
            enqueued = job.enqueued_at.replace(tzinfo=timezone.utc).timestamp() * 1e9
            picked_up = job.started_at.replace(tzinfo=timezone.utc).timestamp() * 1e9
            timing.update(enqueue_ms=(enqueued - submitted_ns) / 1e6,
                          queue_wait_ms=(picked_up - enqueued) / 1e6,
                          worker_setup_ms=(started - picked_up) / 1e6)
            job.meta['relay_timing'] = timing
            job.save_meta()
        frappe.db.after_commit.add(completed)


def recover():
    for row in frappe.get_all('Relay Hub Event', filters={'projection_status': ['in', ['Pending', 'Uncategorized']]}, fields=['name', 'payload'], order_by='modified asc', limit_page_length=20):
        enqueue_projection(row.name, row.payload)


def projection_queue(payload):
    try:
        payload = json.loads(payload) if isinstance(payload, str) else payload
        return 'short' if extract_messages(payload) else 'long'
    except (ValueError, TypeError, AttributeError):
        return 'long'
