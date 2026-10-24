"""Business-choice prompts use the existing durable message-action journal."""
import hashlib
import json

import frappe
from relay_core.automation.service import internal_save
from relay_core.business_access import candidates
from relay_core.permissions import require_access
from relay_core.settings import value as connection_value


def create(state, choices, context=None):
    context = context or {'provider': 'WhatsApp'}
    body = 'Which business is this conversation about?'
    arguments = {'operation': 'messages.interactive', 'to': state.endpoint, 'interactive': {
        'type': 'list', 'body': {'text': body}, 'action': {'button': 'Choose business',
        'sections': [{'title': 'Your businesses', 'rows': [
            {key: item[key] for key in ('id', 'title', 'description')} for item in choices
        ]}]}}}
    tool = 'whatsapp.execute'
    if context['provider'] in ('Telegram', 'Email'):
        body += '\nReply with one exact choice below within 24 hours:\n' + '\n'.join(
            item['doctype'] + ': ' + item['name'] + '\n' + item['id'] for item in choices)
        if context['provider'] == 'Telegram':
            tool = 'telegram.message'
            arguments = {'operation': 'text', 'chat_id': context['chat_id'], 'text': body,
                         'reply_to': context['message_id']}
        else:
            tool = 'email.send'
            arguments = {'to': [state.endpoint], 'subject': 'Re: ' + context.get('subject', '')[:990],
                         'body': body, 'in_reply_to': context['message_id'], 'auto_submitted': True,
                         'references': list(dict.fromkeys([*context.get('references', []), context['message_id']]))[-20:]}
    payload = {'routing': state.conversation_key, 'tool': tool, 'context': context,
               'arguments': arguments, 'content': {'kind': 'text', 'text': body}}
    encoded = json.dumps(payload, sort_keys=True)
    action = frappe.get_doc({'doctype': 'Relay Message Action', 'owner': 'Administrator',
        'request_key': hashlib.sha256(('business-prompt:' + state.conversation_key).encode()).hexdigest(),
        'operation': 'business_prompt', 'payload': encoded,
        'payload_hash': hashlib.sha256(encoded.encode()).hexdigest(), 'status': 'Dispatching',
        'start_contact': state.relay_contact, 'target_channel': state.channel, 'preview': body})
    internal_save(action, new=True)
    frappe.enqueue('relay_core.business_routing_prompt.dispatch', action=action.name, queue='short', enqueue_after_commit=True)
    return action.name


def routing_state(action):
    payload = json.loads(action.payload)
    name = frappe.db.get_value('Relay Business Routing', {'conversation_key': payload['routing']}, 'name')
    return frappe.get_doc('Relay Business Routing', name)


def target(action):
    require_access(manage=True)
    state = routing_state(action)
    if state.prompt_action != action.name or state.relay_contact != action.start_contact:
        raise ValueError('Business prompt does not belong to this conversation')
    binding = frappe.db.get_value('Relay Contact Endpoint',
        {'channel': state.channel, 'endpoint': state.endpoint, 'verified': 1}, 'relay_contact')
    channel = frappe.get_doc('Relay Channel', state.channel)
    payload = json.loads(action.payload)
    context = payload.get('context') or {'provider': 'WhatsApp'}
    if (binding != state.relay_contact or not channel.enabled or channel.channel != context['provider']
            or channel.account != connection_value('relay_hub_account')):
        raise ValueError('Business prompt destination is unavailable')
    source = frappe._dict(relay_contact=state.relay_contact, channel=state.channel, sender_endpoint=state.endpoint)
    return source, channel, context


def prepared(action):
    payload = json.loads(action.payload)
    state = routing_state(action)
    links = candidates(state.relay_contact)
    choices = json.loads(state.choices)
    if (state.selected_at or frappe.utils.now_datetime() >= frappe.utils.get_datetime(state.prompt_expires_at)
            or any((item['doctype'], item['name']) not in links for item in choices)):
        raise ValueError('Business prompt is no longer current')
    return payload['tool'], payload['arguments']


def dispatch(action):
    doc = frappe.get_doc('Relay Message Action', action)
    if doc.operation != 'business_prompt' or doc.owner != 'Administrator':
        raise ValueError('Expected an internal business prompt')
    original = frappe.session.user
    try:
        frappe.set_user('Administrator')
        from relay_core.messaging import reconcile
        return reconcile(action)
    finally:
        frappe.set_user(original)
