"""Apply provider edits/reactions to an existing conversation message only."""
import hashlib
import json
import frappe
from relay_core.automation.provenance import integer, telegram_message
from relay_core.message_types import meta_error, normalize, preview, text
from relay_core.receipt_order import advances


def provider_key(channel, destination, message_id):
    return hashlib.sha256(json.dumps([channel, str(destination), str(message_id)], separators=(',', ':')).encode()).hexdigest()


def reactions(values):
    if not isinstance(values, list) or len(values) > 20:
        raise ValueError('Invalid reactions')
    result = []
    for value in values:
        if not isinstance(value, dict) or value.get('type') not in ('emoji', 'custom_emoji', 'paid'):
            raise ValueError('Invalid reaction type')
        row = {'type': value['type']}
        field = 'custom_emoji_id' if value['type'] == 'custom_emoji' else 'emoji'
        if value['type'] != 'paid':
            row[field] = text(value.get(field), 100, required=True)
        result.append(row)
    return result


def extract_updates(payload):
    if payload.get('channel') == 'Telegram':
        if 'payload' not in payload: return []
        raw = payload.get('payload') or {}
        if not isinstance(raw, dict): raise ValueError('Invalid Telegram update')
        event_id = str(raw.get('update_id', ''))
        if str(payload.get('provider_id')) != event_id: raise ValueError('Telegram update identity mismatch')
        edit = raw.get('edited_message')
        if edit:
            copied = dict(payload, payload={'update_id': raw['update_id'], 'message': edit})
            context = telegram_message(copied)
            if not context: return []
            kind = context['message_type']
            return [{'kind': 'edit', 'destination': str(context['chat_id']), 'target': context['message_id'],
                     'context': context, 'data': normalize(kind, edit.get(kind, {}), provider='Telegram', body=payload['body']),
                     'event_id': event_id, 'sequence': raw['update_id'], 'timestamp': edit.get('edit_date', edit.get('date', 0))}]
        value = raw.get('message_reaction') or raw.get('message_reaction_count')
        if not value: return []
        chat = value.get('chat') or {}; destination = str(integer(chat.get('id')))
        if destination != payload.get('sender'): raise ValueError('Reaction chat mismatch')
        target = integer(value.get('message_id'), positive=True)
        update = {'kind': 'reaction', 'destination': destination, 'target': target,
                  'event_id': event_id, 'sequence': raw['update_id'], 'timestamp': value.get('date', 0)}
        if 'message_reaction_count' in raw:
            counts = value.get('reactions')
            if not isinstance(counts, list) or len(counts) > 20: raise ValueError('Invalid reaction counts')
            result = []
            for count in counts:
                number = count.get('total_count')
                if type(number) is not int or not 0 <= number < 2**52: raise ValueError('Invalid reaction count')
                result.append({'type': reactions([count.get('type')])[0], 'count': number})
            update.update(actor='_counts', items=result)
        else:
            actor = value.get('user') or value.get('actor_chat') or {}
            update.update(actor=str(integer(actor.get('id'))), items=reactions(value.get('new_reaction')))
        return [update]
    if payload.get('channel', 'WhatsApp') != 'WhatsApp': return []
    result = []
    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            for status in change.get('value', {}).get('statuses', []):
                state = {'sent':'Sent','delivered':'Delivered','read':'Read','failed':'Failed'}.get(status.get('status'))
                if not state: continue
                target = text(status.get('id'),300,required=True)
                destination = text(status.get('recipient_id'),200,required=True)
                timestamp = int(status.get('timestamp',0))
                participant=status.get('recipient_participant_id')
                if participant is not None:
                    participant=text(participant,200,required=True)
                    if status.get('recipient_type')!='group':raise ValueError('Invalid group receipt')
                update={'participant':participant,'kind':'delivery','destination':destination,'target':target,'status':state,
                        'event_id':target+':'+state+':'+str(timestamp),'timestamp':timestamp}
                if state=='Failed' and status.get('errors'):
                    update['error']=delivery_error(status['errors'])
                result.append(update)
            for message in change.get('value', {}).get('messages', []):
                if message.get('type') in ('edit', 'revoke'):
                    result.append(whatsapp_change(message)); continue
                if message.get('type') != 'reaction': continue
                value = message.get('reaction', {}); emoji = text(value.get('emoji', ''), 100)
                result.append({'kind': 'reaction', 'destination': message.get('group_id') or message.get('from'),
                    'target': text(value.get('message_id'), 300, required=True), 'actor': text(message.get('from'), 200, required=True),
                    'event_id': text(message.get('id'), 300, required=True), 'timestamp': int(message.get('timestamp', 0)),
                    'items': [{'type': 'emoji', 'emoji': emoji}] if emoji else []})
    return result


def delivery_error(errors):
    """Meta's failure title, details and code as one readable line."""
    error = meta_error(errors)
    title = error.get('title') or 'Delivery failed'
    line = title + (': ' + error['details'] if error.get('details') and error['details'] != title else '')
    return (line + (' (code %d)' % error['code'] if 'code' in error else ''))[:1000]


def whatsapp_change(message):
    """A Coexistence edit replaces the target's content; a revoke clears it."""
    kind = message['type']; value = message.get(kind)
    if not isinstance(value, dict): raise ValueError('Invalid message change')
    if kind == 'edit':
        edited = value.get('message')
        if not isinstance(edited, dict): raise ValueError('Invalid edited message')
        inner = edited.get('type'); detail = edited.get(inner, {})
        body = (detail.get('body') if inner == 'text' else detail.get('caption', '')) if isinstance(detail, dict) else ''
        data = normalize(inner, detail, provider='WhatsApp', body=body or '')
    else:
        data = {'kind': 'revoked'}
    return {'kind': 'edit', 'destination': text(message.get('group_id') or message.get('from'), 200, required=True),
            'target': text(value.get('original_message_id'), 300, required=True), 'data': data,
            'event_id': text(message.get('id'), 300, required=True), 'timestamp': int(message.get('timestamp', 0))}


def apply_updates(payload, channel, event):
    updates = extract_updates(payload)
    if not updates: return 'Ignored'
    if any(type(item['timestamp']) is not int or item['timestamp'] < 0 or type(item.get('sequence', 0)) is not int for item in updates):
        raise ValueError('Invalid update timestamp')
    deliveries = [row for row in updates if row['kind'] == 'delivery' and not row.get('participant')]
    unresolved = False
    if deliveries:
        from relay_core.whatsapp_receipts import apply_batch
        unresolved = apply_batch(deliveries, channel) == 'Uncategorized'
    updates = [row for row in updates if row['kind'] != 'delivery' or row.get('participant')]
    delivery_contacts = {}
    for update in updates:
        if type(update['timestamp']) is not int or update['timestamp'] < 0: raise ValueError('Invalid update timestamp')
        destination = update['destination']
        endpoint_key = hashlib.sha256((channel + ':' + destination).encode()).hexdigest()
        contact = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': endpoint_key, 'verified': 1}, 'relay_contact')
        name = frappe.db.get_value('Relay Message', {'provider_message_key': provider_key(channel, destination, update['target'])}, 'name')
        if not contact or not name:
            unresolved = True; continue
        frappe.db.get_value('Relay Message', name, 'name', for_update=True)
        doc = frappe.get_doc('Relay Message', name)
        if doc.relay_contact != contact or doc.sender_endpoint != destination:
            unresolved = True; continue
        if update['kind']=='delivery' and update.get('participant'):
            context=doc.provider_context or {}
            if isinstance(context,str):context=json.loads(context)
            if doc.direction!='Outgoing' or context.get('group_id')!=destination:
                unresolved=True;continue
            from relay_core.delivery_receipts import record
            if record(doc,update):delivery_contacts[doc.relay_contact]=doc
        history = doc.get('message_updates') or {}
        if isinstance(history, str): history = json.loads(history)
        key = update['kind'] if update['kind'] in ('edit','delivery') else 'reaction:' + update['actor']
        previous = history.get(key, {})
        if previous.get('event_id') == update['event_id'] or (update['kind']!='delivery' and int(previous.get('timestamp', 0)) > update['timestamp']):
            continue
        if 'sequence' in update and previous.get('timestamp') == update['timestamp'] and int(previous.get('sequence', -1)) >= update['sequence']:
            continue
        values = {}
        if update['kind'] == 'delivery':
            if doc.direction != 'Outgoing': continue
            from relay_core.whatsapp_receipts import with_time
            times=with_time(previous.get('times'),update['status'],update['timestamp'])
            if advances(doc.status,update['status'],int(previous.get('timestamp',0)),update['timestamp']):
                values={'status':update['status']}
            elif times==previous.get('times',{}):
                continue
        elif update['kind'] == 'edit':
            values = {'message_data': json.dumps(update['data'], ensure_ascii=False), 'content': preview(update['data']),
                      'message_type': update['data']['kind'], 'edited_at': frappe.utils.now_datetime(),
                      'transcript': '', 'transcript_status': '', 'transcript_details': None}
        else:
            state = doc.get('reactions') or {}
            if isinstance(state, str): state = json.loads(state)
            # Bounded actor history avoids unbounded JSON growth in busy groups.
            if update['actor'] not in state and len(state) >= 200:
                state.pop(next(iter(state)))
            state[update['actor']] = update['items']
            values['reactions'] = json.dumps(state, ensure_ascii=False)
        if key not in history and len(history) >= 201:
            history.pop(next(iter(history)))
        history[key] = {'event_id': update['event_id'], 'timestamp': update['timestamp'], 'sequence': update.get('sequence', 0)}
        if update['kind'] == 'delivery':
            # A receipt that does not advance the status records only its time.
            history[key] = dict(history[key] if 'status' in values else previous, times=times)
        values['message_updates'] = json.dumps(history)
        # Delivery receipts do not edit message content. Keep their provenance
        # in message_updates without invalidating an editor's modified token.
        frappe.db.set_value('Relay Message', name, values,
                            update_modified=update['kind'] != 'delivery')
        from relay_core.realtime import changed
        if update['kind'] == 'delivery':
            delivery_contacts[doc.relay_contact] = doc
        else:
            changed(frappe.get_doc('Relay Message', name))
        if update['kind'] == 'edit':
            from relay_core import translations, voice_transcripts
            edited = frappe.get_doc('Relay Message', name)
            translations.on_message(edited)
            voice_transcripts.on_message(edited)
    if delivery_contacts:
        from relay_core.realtime import changed, contact_changed
        first, *remaining = delivery_contacts.values()
        changed(first)
        for doc in remaining:
            contact_changed(doc.relay_contact)
    return 'Uncategorized' if unresolved else 'Projected'
