"""One business decision per authenticated conversation, independent of channel."""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import frappe
from relay_core.automation.provenance import conversation_key
from relay_core.automation.service import internal_save
from relay_core.business_access import campaign_send, candidates, incoming_reference, primary


def resolve(contact, channel, endpoint, context, row, event, override=None, position=0):
    key = hashlib.sha256((channel + ':' + endpoint).encode()).hexdigest()
    binding = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': key, 'verified': 1},
                                  ['name', 'relay_contact'], as_dict=True, for_update=True)
    if not binding or binding.relay_contact != contact:
        return None, 'triage_unverified'
    # Contact before routing, as the drain and episode admission lock them; the reverse order deadlocks (1213).
    frappe.db.get_value('Relay Contact', contact, 'name', for_update=True)
    links = candidates(contact)
    if override is not None and tuple(override) not in links:
        raise ValueError('Choose a linked business record')
    if (override is None and context.get('provider') == 'Email'
            and context.get('authentication', {}).get('status') != 'pass'):
        return None, 'triage_unverified_sender'
    business = incoming_reference(contact, channel, endpoint, context, links=links)
    state_key = conversation_key(channel, endpoint, context)
    name = frappe.db.get_value('Relay Business Routing', {'conversation_key': state_key}, 'name', for_update=True)
    state = frappe.get_doc('Relay Business Routing', name, for_update=True) if name else frappe.get_doc({
        'doctype': 'Relay Business Routing', 'conversation_key': state_key, 'relay_contact': contact,
        'channel': channel, 'endpoint': endpoint,
    })
    if state.relay_contact != contact:
        return None, 'triage_binding_changed'
    rule = context.pop('business_rule', None)
    if override is not None:
        business, rule = tuple(override), 'manager'
    elif rule in ('triage_conflicting_references', 'triage_unlinked_reference'):
        business = None
    elif business:
        rule = rule or 'reply_context'
    else:
        choices = json.loads(state.choices or '[]')
        choice_id = (row.get('message_data') or {}).get('selection_id')
        if context.get('provider') in ('Telegram', 'Email'):
            body = (row.get('text') or {}).get('body', '').strip()
            if body.startswith('relay-business:'):
                choice_id = body
            elif not state.selected_at and body.isascii() and body.isdigit() and len(body) <= 2 and 1 <= int(body) <= len(choices):
                choice_id = choices[int(body) - 1]['id']
        selected = next((item for item in choices if item['id'] == choice_id), None)
        if choice_id and str(choice_id).startswith('relay-business:'):
            if (selected and (selected['doctype'], selected['name']) in links and not state.selected_at
                    and state.prompt_expires_at
                    and frappe.utils.now_datetime() < frappe.utils.get_datetime(state.prompt_expires_at)
                    and frappe.utils.get_datetime(event.creation) < frappe.utils.get_datetime(state.prompt_expires_at)
                    and choice_scope(context)):
                business, rule = (selected['doctype'], selected['name']), 'sender_choice'
                row['type'] = 'text'
                row['text'] = {'body': 'Chose: ' + selected['doctype'] + ' — ' + selected.get('title', selected['name'])}
                row['message_data'] = {'kind': 'text', 'text': row['text']['body']}
            else:
                rule = 'triage_invalid_choice'
        elif (context.get('reply_to_message_id') and links and rule != 'quoted_conversation'
                and not campaign_send(channel, endpoint, context['reply_to_message_id'])):
            rule = 'triage_unresolved_reference'
        elif len(links) == 1:
            business, rule = links[0], 'single_link'
        elif (state.business_doctype, state.business_name) in links and state.selected_at and (
                frappe.utils.get_datetime(event.creation) > frappe.utils.get_datetime(state.selected_at)
                or (event.get('name') and event.name == state.selected_event and position > state.selected_position)
                or row['id'] == state.prompt_message_id):
            business, rule = (state.business_doctype, state.business_name), 'conversation'
        elif marked := primary(contact, links):
            business, rule = marked, 'primary_link'
        elif state.prompt_action:
            status = frappe.db.get_value('Relay Message Action', state.prompt_action, 'status')
            rule = 'triage_prompt_rejected' if status == 'Rejected' else 'triage_prompt_pending'
        elif len(links) > 1:
            rule = prompt(state, links, context, row, event)
        else:
            rule = 'triage_no_business'
    if rule in ('manager', 'sender_choice'):
        state.business_doctype, state.business_name = business
        state.selected_at = frappe.utils.now_datetime() if rule == 'manager' else event.creation
        state.selected_event = event.get('name') if rule == 'sender_choice' else None
        state.selected_position = position
    state.rule = rule
    internal_save(state, new=not name)
    return business, rule


def prompt(state, links, context, row, event):
    provider = context.get('provider')
    if provider not in ('WhatsApp', 'Telegram', 'Email') or context.get('group_id') or not 2 <= len(links) <= 10:
        return 'triage_no_prompt'
    if provider == 'Telegram' and not choice_scope(context):
        return 'triage_no_prompt'
    if provider == 'Email' and (not context.get('message_id') or context.get('auto_submitted')
            or context.get('authentication', {}).get('status') != 'pass'):
        return 'triage_no_prompt'
    try:
        stamp = (datetime.fromtimestamp(int(row['timestamp']), timezone.utc).replace(tzinfo=None)
                 if provider == 'WhatsApp' else frappe.utils.get_datetime(event.creation))
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return 'triage_window_closed'
    now = frappe.utils.now_datetime()
    # Provider times are UTC; Frappe dates use the site's timezone.
    if provider == 'WhatsApp':
        stamp = frappe.utils.convert_utc_to_system_timezone(stamp).replace(tzinfo=None)
    stamp = min(stamp, frappe.utils.get_datetime(event.creation), now)
    expires = stamp + timedelta(hours=24)
    if now >= expires:
        return 'triage_window_closed'
    choices = []
    for dt, name in links:
        doc = frappe.get_doc(dt, name)
        from relay_core.business_groups import title_field
        label = str(doc.get(title_field(dt)) or name)
        choices.append({'id': 'relay-business:' + secrets.token_hex(16), 'doctype': dt, 'name': name,
                        'title': label[:24], 'description': (dt + ': ' + name)[:72]})
    state.choices = json.dumps(choices)
    state.prompt_message_id, state.prompt_expires_at = row['id'], expires
    from relay_core.business_routing_prompt import create
    state.prompt_action = create(state, choices, context)
    return 'triage_prompt_pending'


def choice_scope(context):
    if context.get('provider') == 'Email':
        return context.get('authentication', {}).get('status') == 'pass' and not context.get('auto_submitted')
    if context.get('provider') == 'Telegram':
        return context.get('chat_type') == 'private' and context.get('participant_id') == context.get('chat_id')
    return True
