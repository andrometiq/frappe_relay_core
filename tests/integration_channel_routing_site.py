"""Telegram choices, reply ownership and topic isolation through signed ingress."""
import json
from datetime import timedelta
from unittest.mock import patch
import frappe
from channel_site_fixtures import init, push_status
from channel_identity_fixtures import scenario, configured, endpoint, incoming, telegram_raw, fails
from relay_core import business_routing_prompt, messaging, whatsapp
from relay_core.automation import projection

init()
try:
    fixture = scenario()
    with configured(fixture), patch.object(whatsapp, 'client') as client:
        binding = endpoint(fixture, 'Telegram', '9555000456'); frappe.db.commit()
        def receive(number, body, chat=9555000456, **kwargs):
            return incoming(fixture, 'Telegram', str(chat), body,
                raw=telegram_raw(chat, number, body, **kwargs), identifier=str(number))[0]
        first = receive(501, 'Order quantity 25')
        assert first.projection_status == 'Uncategorized'
        state = frappe.get_doc('Relay Business Routing', {'channel': binding.channel, 'endpoint': binding.endpoint})
        choices = json.loads(state.choices)
        choice = next(row for row in choices if row['doctype'] == 'Supplier')
        action = frappe.get_doc('Relay Message Action', state.prompt_action)
        assert action.status == 'Dispatching'
        client.return_value.call_tool.side_effect = [{'deliveries': []}, {'pending': True, 'state': 'queued'}]
        assert business_routing_prompt.dispatch(action.name)['status'] == 'Queued'
        args = client.return_value.call_tool.call_args.args[1]
        assert args['reply_to'] == 501 and 'Supplier' in args['text'] and 'relay-business:' not in args['text']
        for number in range(520, 532):
            burst = receive(number, 'Pending quantity ' + str(number))
            assert 'triage_prompt_pending' in burst.routing_decisions
        assert frappe.db.count('Relay Message Action', {'operation':'business_prompt', 'target_channel':binding.channel}) == 1
        push_status(fixture.account, [{'id': 501, 'delivery_id': 501, 'request_key': action.request_key,
            'operation': 'telegram.message', 'state': 'submitted', 'receipt': {'message_id': 502},
            'occurred_at': '2026-10-24T10:00:00Z'}])
        action.reload(); assert action.status == 'Submitted' and not action.outbound_message
        chosen = receive(503, choice['id'], reply=502)
        assert chosen.projection_status == 'Projected'
        message = frappe.get_doc('Relay Message', {'channel': binding.channel, 'provider_id': '503'})
        assert message.business_name == fixture.supplier.name
        assert message.content.startswith('Chose: Supplier')
        projection.project(first.name); frappe.db.commit(); first.reload()
        assert first.projection_status == 'Projected'
        stale = receive(504, choice['id'])
        assert stale.projection_status == 'Uncategorized'
        assert 'triage_invalid_choice' in stale.routing_decisions
        # A separate topic cannot consume a private-chat token.
        group = endpoint(fixture, 'Telegram', '-9555000456'); frappe.db.commit()
        crossed = receive(505, choice['id'], chat=-9555000456, topic=7)
        assert crossed.projection_status == 'Uncategorized'
        assert 'triage_invalid_choice' in crossed.routing_decisions
        unassigned = receive(506, 'Group quantity 50', chat=-9555000456, topic=7)
        assert 'triage_no_prompt' in unassigned.routing_decisions
        projection.project(unassigned.name, business_overrides={'506': ('Customer', fixture.customer.name)})
        frappe.db.commit()
        reply = receive(507, 'Reply quantity 75', chat=-9555000456, topic=7, reply=506)
        assert 'reply_context' in reply.routing_decisions
        wrong_topic = receive(508, 'Different topic', chat=-9555000456, topic=8, reply=506)
        assert wrong_topic.projection_status == 'Uncategorized'
        # Expiry is checked at consumption, even after a successful prompt send.
        endpoint(fixture, 'Telegram', '9555000789'); frappe.db.commit()
        expired_event = receive(509, 'Another quantity 25', chat=9555000789)
        expired = frappe.get_doc('Relay Business Routing', {'channel': binding.channel, 'endpoint': '9555000789'})
        token = json.loads(expired.choices)[0]['id']
        frappe.db.set_value('Relay Business Routing', expired.name, 'prompt_expires_at', frappe.utils.now_datetime() - timedelta(seconds=1))
        frappe.db.commit()
        expired_choice = receive(510, token, chat=9555000789)
        assert 'triage_invalid_choice' in expired_choice.routing_decisions
        frappe.set_user(fixture.actor)
        fails(lambda: frappe.get_doc('Relay Message', message.name).check_permission('read'))
        rows = frappe.get_list('Relay Message', filters={'relay_contact': fixture.contact.name}, pluck='name')
        assert message.name not in rows
        frappe.set_user('Administrator')
        print('PASS Telegram durable text choices, callback completion, replay/expiry, group triage, reply/topic isolation and restricted history')
finally:
    from channel_identity_fixtures import cleanup
    if "fixture" in globals(): cleanup(fixture)
    frappe.destroy()
