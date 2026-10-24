"""Email ownership and choice acceptance through authenticated local callbacks."""
import json
from datetime import timedelta
from unittest.mock import patch
import frappe
from channel_site_fixtures import push_status, check_business_lifecycle
from channel_identity_fixtures import scenario, configured, endpoint, incoming, email_raw, fails
from relay_core import email, messaging, business_routing_prompt, whatsapp
from relay_core.automation import projection
from relay_core.automation.provenance import context_of


def run():
    frappe.set_user('Administrator')
    fixture = scenario()
    address = 'threads-' + fixture.stamp + '@example.invalid'
    with configured(fixture), patch.object(whatsapp, 'client') as client:
        binding = endpoint(fixture, 'Email', address); frappe.db.commit()
        def receive(label, body, parent=None, refs=None, **kwargs):
            message_id = '<' + label + '-' + fixture.stamp + '@example.invalid>'
            return incoming(fixture, 'Email', address, body,
                raw=email_raw(message_id, parent=parent, refs=refs, **kwargs))[0], message_id
        roots = []
        for index, business in enumerate((fixture.customer, fixture.supplier, fixture.customer, fixture.supplier)):
            first, root = receive('root' + str(index), 'Quantity ' + str(25 * (index + 1)), cc=['copy@example.invalid'])
            assert first.projection_status == 'Uncategorized'
            state = frappe.get_doc('Relay Business Routing', {'channel': binding.channel, 'prompt_message_id': json.loads(first.payload)['provider_id']})
            token = next(row['id'] for row in json.loads(state.choices) if row['doctype'] == business.doctype)
            prompt_id = '<prompt-' + str(index) + '-' + fixture.stamp + '@example.invalid>'
            action = frappe.get_doc('Relay Message Action', state.prompt_action)
            client.return_value.call_tool.side_effect = [{'deliveries': []}, {'pending': True, 'state': 'queued'}]
            assert business_routing_prompt.dispatch(action.name)['status'] == 'Queued'
            args = client.return_value.call_tool.call_args.args[1]
            assert args['to'] == [address] and args['in_reply_to'] == root and args['references'] == [root]
            assert args['auto_submitted'] is True and token in args['body']
            push_status(fixture.account, [{'id': 801 + index, 'delivery_id': 801 + index, 'request_key': action.request_key,
                'operation': 'email.send', 'state': 'submitted', 'receipt': {'message_id': prompt_id},
                'occurred_at': '2026-10-24T10:00:00Z'}])
            action.reload(); assert action.status == 'Submitted' and not action.outbound_message
            chosen, selected_id = receive('choice' + str(index), token, prompt_id, [root, prompt_id] if index < 2 else None)
            assert chosen.projection_status == 'Projected'
            projection.project(first.name); frappe.db.commit(); first.reload()
            assert first.projection_status == 'Projected'
            source = frappe.get_doc('Relay Message', {'channel': binding.channel, 'provider_id': json.loads(first.payload)['provider_id']})
            assert source.business_name == business.name
            data = json.loads(source.message_data)['email']
            assert data['to'] == ['local-inbox@example.invalid'] and data['cc'] == ['copy@example.invalid']
            assert context_of(source)['authentication']['status'] == 'pass'
            roots.append((source, root, token, selected_id))
        assert roots[0][0].conversation_key != roots[1][0].conversation_key
        source, root, token, selected_id = roots[0]
        replay, _ = receive('replay', token, root, [root])
        # A known parent takes precedence; a bare reused selection cannot select again.
        assert 'reply_context' in replay.routing_decisions
        foreign, _ = receive('foreign-choice', token)
        assert 'triage_invalid_choice' in foreign.routing_decisions
        assert foreign.projection_status == 'Uncategorized'
        alias = 'alias-' + fixture.stamp + '@example.invalid'
        endpoint(fixture, 'Email', alias); frappe.db.commit()
        foreign_sender, _ = incoming(fixture, 'Email', alias, token,
            raw=email_raw('<foreign-sender-' + fixture.stamp + '@example.invalid>', parent=selected_id, refs=[root]))
        assert 'triage_invalid_choice' in foreign_sender.routing_decisions
        conflicting, _ = receive('conflicting', 'Mixed ancestry', selected_id, [root, roots[1][3]])
        assert 'triage_conflicting_references' in conflicting.routing_decisions
        assert conflicting.projection_status == 'Uncategorized'
        no_auth, _ = receive('unverified', 'Cannot ask sender', authenticated=False)
        assert 'triage_unverified_sender' in no_auth.routing_decisions
        expired, _ = receive('expired', 'Quantity 75')
        state = frappe.get_doc('Relay Business Routing', {'channel': binding.channel, 'prompt_message_id': json.loads(expired.payload)['provider_id']})
        expired_root = json.loads(expired.payload)['payload']['message_id']
        expired_token = json.loads(state.choices)[0]['id']
        frappe.db.set_value('Relay Business Routing', state.name, 'prompt_expires_at', frappe.utils.now_datetime() - timedelta(seconds=1))
        frappe.db.commit()
        rejected, _ = receive('expired-choice', expired_token, expired_root, [expired_root])
        assert 'triage_invalid_choice' in rejected.routing_decisions
        client.return_value.call_tool.side_effect = None
        client.return_value.call_tool.return_value = {'message_id': '<reply-' + fixture.stamp + '@example.invalid>'}
        sent = email.send([address], 'Re: Quantity 25', 'Confirmed quantity 25', message=source.name,
                          cc=[alias], bcc=[alias], request_key='thread-reply-' + fixture.stamp)
        assert sent['status'] == 'Submitted'
        outgoing = frappe.get_doc('Relay Message', sent['message'])
        assert outgoing.conversation_key == source.conversation_key and outgoing.business_name == fixture.customer.name
        assert 'bcc' not in json.loads(outgoing.message_data)['email']
        assert json.loads(outgoing.message_data)['email']['cc'] == [alias]
        assert json.loads(frappe.get_doc('Relay Message Action', sent['action']).payload)['email_values']['bcc'] == [alias]
        # Stored pre-thread messages resolve ancestry instead of inventing one root per message.
        for legacy_message in (source, outgoing):
            old_context = context_of(legacy_message); old_context.pop('email_thread_id', None)
            frappe.db.set_value('Relay Message', legacy_message.name, 'provider_context', json.dumps(old_context))
        frappe.db.commit()
        legacy_target = email.send_target({'message': outgoing.name})
        assert legacy_target[2]['email_thread_id'] == root
        old_reply = context_of(outgoing)['message_id']
        legacy_reply, _ = receive('legacy-thread-reply', 'Legacy thread quantity 25', old_reply, [root, old_reply])
        assert legacy_reply.projection_status == 'Projected'
        restored = frappe.get_doc('Relay Message', {'channel': binding.channel, 'provider_id': json.loads(legacy_reply.payload)['provider_id']})
        assert context_of(restored)['email_thread_id'] == root and restored.business_name == fixture.customer.name
        # Forwarding uses the destination's contact and an explicit destination business.
        person = frappe.get_doc({'doctype': 'Contact', 'first_name': 'Local C2 recipient ' + fixture.stamp,
            'links': [{'link_doctype': 'Supplier', 'link_name': fixture.supplier.name}]}).insert()
        other = frappe.get_doc({'doctype': 'Relay Contact', 'contact': person.name, 'display_name': 'Local C2 recipient'}).insert()
        other_address = 'recipient-' + fixture.stamp + '@example.invalid'
        endpoint(fixture, 'Email', other_address, other.name); frappe.db.commit()
        client.return_value.call_tool.return_value = {'message_id': '<forward-' + fixture.stamp + '@example.invalid>'}
        forwarded = email.send([other_address], 'Fwd: Quantity 25', 'Forwarded quantity 25', message=source.name, forward=1,
            business_doctype='Supplier', business_name=fixture.supplier.name, request_key='forward-' + fixture.stamp)
        assert forwarded['status'] == 'Submitted'
        forward = frappe.get_doc('Relay Message', forwarded['message'])
        assert forward.relay_contact == other.name and forward.sender_endpoint == other_address
        assert forward.business_name == fixture.supplier.name and forward.conversation_key != source.conversation_key
        assert email.send_status(source.name, 'forward-' + fixture.stamp)['message'] == forward.name
        assert 'in_reply_to' not in client.return_value.call_tool.call_args.args[1]
        assert email.send([other_address], 'Fwd: Quantity 25', 'Forwarded quantity 25', message=source.name, forward=1,
            business_doctype='Supplier', business_name=fixture.supplier.name, request_key='forward-' + fixture.stamp)['message'] == forward.name
        # Pre-v1.5 forward journals snapshot the readable source, even for a differently linked recipient.
        client.return_value.call_tool.side_effect = SystemExit('Local legacy forward admission crash')
        legacy_key = 'legacy-forward-' + fixture.stamp
        try:
            email.send([other_address], 'Legacy forward', 'Quantity 35', message=source.name, forward=1,
                business_doctype='Supplier', business_name=fixture.supplier.name, request_key=legacy_key)
        except SystemExit:
            pass
        legacy_action = frappe.get_doc('Relay Message Action', {'source_message': source.name, 'status': 'Dispatching'})
        legacy_payload = json.loads(legacy_action.payload)
        legacy_payload.pop('destination')
        legacy_payload['business'] = ['Customer', fixture.customer.name]
        legacy_values = legacy_payload['email_values']
        legacy_values.pop('business_doctype'); legacy_values.pop('business_name')
        import hashlib
        legacy_hash = hashlib.sha256(json.dumps(legacy_values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        frappe.db.set_value('Relay Message Action', legacy_action.name,
            {'payload': json.dumps(legacy_payload), 'payload_hash': legacy_hash}); frappe.db.commit()
        client.return_value.call_tool.side_effect = [{'deliveries': []}, {'message_id': '<legacy-forward-' + fixture.stamp + '@example.invalid>'}]
        recovered = email.send([other_address], 'Legacy forward', 'Quantity 35', message=source.name,
            forward=1, request_key=legacy_key)
        assert recovered['status'] == 'Submitted'
        assert client.return_value.call_tool.call_args.args[1]['request_key'] == legacy_action.request_key
        assert client.return_value.call_tool.call_args.args[1]['to'] == [other_address]
        assert frappe.get_doc('Relay Message', recovered['message']).business_name == fixture.customer.name
        client.return_value.call_tool.side_effect = None
        frappe.set_user(fixture.actor); client.reset_mock()
        frappe.get_doc('Relay Message', source.name).check_permission('read')
        assert email.recipient_options(source.name)
        for forbidden in (roots[1][0], forward):
            fails(lambda: frappe.get_doc('Relay Message', forbidden.name).check_permission('read'))
        fails(lambda: frappe.get_doc('Relay Message Action', sent['action']).check_permission('read'))
        assert not frappe.get_list('Relay Message Action', filters={'target_channel': binding.channel}, pluck='name')
        fails(lambda: frappe.get_doc('Relay Hub Event', first.name).check_permission('read'))
        fails(lambda: frappe.get_doc('Relay Business Routing', state.name).check_permission('read'))
        fails(lambda: email.send([other_address], 'Fwd: Forbidden', 'Quantity 50', message=source.name, forward=1,
                                 business_doctype='Supplier', business_name=fixture.supplier.name))
        fails(lambda: email.prepare([address], 'CC forbidden', 'Quantity 25', cc=[other_address], message=source.name))
        fails(lambda: email.prepare([address], 'BCC forbidden', 'Quantity 25', bcc=[other_address], message=source.name))
        client.return_value.call_tool.assert_not_called()
        visible = frappe.get_list('Relay Message', filters={'relay_contact': fixture.contact.name}, pluck='name')
        assert roots[1][0].name not in visible and source.name in visible
        frappe.set_user('Administrator')
        client.return_value.call_tool.side_effect = TimeoutError('Local lost SMTP response')
        pending = email.send([address], 'Immutable ownership', 'Quantity 25', message=source.name,
                             request_key='immutable-' + fixture.stamp)
        action = frappe.get_doc('Relay Message Action', pending['action'])
        frappe.db.set_value('Relay Message', source.name, {'business_doctype': 'Supplier', 'business_name': fixture.supplier.name})
        frappe.db.commit(); client.reset_mock()
        push_status(fixture.account, [{'id': 900, 'delivery_id': 900, 'request_key': action.request_key,
            'operation': 'email.send', 'state': 'submitted',
            'receipt': {'message_id': '<immutable-' + fixture.stamp + '@example.invalid>'},
            'occurred_at': '2026-10-24T10:00:00Z'}])
        action.reload()
        assert action.status == 'Submitted'
        assert frappe.get_doc('Relay Message', action.outbound_message).business_name == fixture.customer.name
        client.return_value.call_tool.assert_not_called()
        check_business_lifecycle(fixture.customer); check_business_lifecycle(fixture.supplier)
        print('PASS email two businesses/two threads, durable thread-bound choices, ancestry ambiguity, expiry, To/CC, forwarding and recipient/history permissions')
