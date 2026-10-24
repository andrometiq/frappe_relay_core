"""Verified channel starts, explicit ownership and durable replay on yrp.site."""
import json
from unittest.mock import patch
import frappe
from channel_site_fixtures import init, check_business_lifecycle
from channel_identity_fixtures import scenario, configured, endpoint, fails
from relay_core import conversation_start, messaging, whatsapp, telegram_delivery

init()
try:
    fixture = scenario()
    with configured(fixture), patch.object(whatsapp, 'client') as client:
        for provider, address in [('Telegram', '9555000321'), ('Email', 'start-' + fixture.stamp + '@example.invalid')]:
            binding = endpoint(fixture, provider, address); frappe.db.commit()
            kind = 'text' if provider == 'Telegram' else 'email'
            data = {'text': 'Order quantity 25'} if provider == 'Telegram' else {'subject': 'Order 25', 'body': 'Quantity 25'}
            if provider == 'Email':
                client.reset_mock()
                fails(lambda: conversation_start.send(fixture.contact.name, binding.name, kind, data,
                    'Telegram-' + fixture.stamp, fixture.customer.doctype, fixture.customer.name))
                client.return_value.call_tool.assert_not_called()
            def send(key, business=None, values=None):
                business = business or fixture.customer
                return conversation_start.send(fixture.contact.name, binding.name, kind, values or data, key,
                                               business.doctype, business.name)
            fails(lambda: conversation_start.send(fixture.contact.name, binding.name, kind, data, 'ambiguous-' + fixture.stamp))
            client.return_value.call_tool.return_value = {'message_id': 321 if provider == 'Telegram' else '<start-' + fixture.stamp + '@example.invalid>'}
            key = provider + '-' + fixture.stamp
            result = send(key)
            assert result['status'] == 'Submitted'
            original_calls = client.return_value.call_tool.call_count
            assert send(key)['message'] == result['message']
            assert conversation_start.send_business(fixture.person.name, binding.channel, kind, data, key,
                fixture.customer.doctype, fixture.customer.name, endpoint=binding.name)['message'] == result['message']
            assert client.return_value.call_tool.call_count == original_calls
            doc = frappe.get_doc('Relay Message', result['message'])
            assert (doc.business_doctype, doc.business_name) == (fixture.customer.doctype, fixture.customer.name)
            assert doc.sender_endpoint == address
            fails(lambda: send(key, fixture.supplier))
            changed = dict(data)
            changed['text' if provider == 'Telegram' else 'body'] = 'Changed quantity 99'
            fails(lambda: send(key, values=changed))
            client.return_value.call_tool.side_effect = SystemExit('Local crash before Hub admission')
            crash_key = 'crash-' + key
            try: send(crash_key)
            except SystemExit: pass
            action = frappe.get_doc('Relay Message Action', {'start_contact': fixture.contact.name,
                'target_channel': binding.channel, 'status': 'Dispatching'})
            client.return_value.call_tool.side_effect = [ {'deliveries': []},
                {'message_id': 322 if provider == 'Telegram' else '<recovered-' + fixture.stamp + '@example.invalid>'}]
            assert messaging.reconcile(action.name)['status'] == 'Submitted'
            assert client.return_value.call_tool.call_args.args[1]['request_key'] == action.request_key
            client.return_value.call_tool.side_effect = None
            binding.verified = 0; binding.save(); frappe.db.commit(); client.reset_mock()
            fails(lambda: send(key))
            client.return_value.call_tool.assert_not_called()
            binding.verified = 1; binding.save(); frappe.db.commit()
            frappe.set_user(fixture.actor)
            conversation_start.target(fixture.contact.name, binding.name, fixture.customer.doctype, fixture.customer.name)
            fails(lambda: send('forbidden-' + key, fixture.supplier))
            client.return_value.call_tool.assert_not_called()
            frappe.set_user('Administrator')
        phone = '919555000321'
        fixture.person.append('phone_nos', {'phone': phone, 'is_primary_mobile_no': 1})
        fixture.person.save()
        wa = endpoint(fixture, 'WhatsApp', phone); frappe.db.commit()
        assert len(conversation_start.business_channels(fixture.person.name, 'Customer', fixture.customer.name)) == 3
        incoming = frappe.get_doc({'doctype': 'Relay Message', 'relay_contact': fixture.contact.name,
            'channel': wa.channel, 'sender_endpoint': phone, 'direction': 'Incoming', 'content': 'Quantity 25',
            'status': 'Sent', 'business_doctype': 'Customer', 'business_name': fixture.customer.name,
            'provider_context': json.dumps({'provider': 'WhatsApp'})}).insert()
        frappe.db.commit()
        client.return_value.call_tool.return_value = {'messages': [{'id': 'three-channel-' + fixture.stamp}]}
        request = dict(key='three-channel-' + fixture.stamp, operation='messages.send', arguments={'body': 'Quantity 25 confirmed'},
                       contact=fixture.person.name, business_doctype='Customer', business_name=fixture.customer.name)
        # Two verified WhatsApp numbers on one channel still select the Contact's prepared destination.
        second_phone = endpoint(fixture, 'WhatsApp', '919555000322'); frappe.db.commit()
        sent = whatsapp.send(request)
        assert client.return_value.call_tool.call_args.args[1]['to'] == phone
        assert json.loads(frappe.get_doc('Relay Message Action', sent['action']).payload)['start']['endpoint'] == wa.name
        assert sent['status'] == 'Submitted'
        assert frappe.get_doc('Relay Message', sent['message']).channel == wa.channel
        calls = client.return_value.call_tool.call_count
        assert whatsapp.send(request)['message'] == sent['message']
        assert client.return_value.call_tool.call_count == calls
        group = endpoint(fixture, 'Telegram', '-9555000321'); frappe.db.commit()
        fails(lambda: conversation_start.send(fixture.contact.name, group.name, 'text', {'text': 'Wrong route'}, 'group-' + fixture.stamp,
                                               fixture.customer.doctype, fixture.customer.name))
        fails(lambda: telegram_delivery.send_group(fixture.contact.name, group.channel, -9555000321, 'Quantity 25', 0, 7, 'ambiguous-group-' + fixture.stamp))
        client.return_value.call_tool.return_value = {'message_id': 401}
        result = telegram_delivery.send_group(fixture.contact.name, group.channel, -9555000321, 'Quantity 25', 0, 7,
            'group-send-' + fixture.stamp, fixture.customer.doctype, fixture.customer.name)
        assert result['status'] == 'Submitted'
        assert json.loads(frappe.get_doc('Relay Message', result['message']).provider_context)['message_thread_id'] == 7
        fails(lambda: telegram_delivery.send_group(fixture.contact.name, group.channel, -9555000321, 'Wrong topic', 401, 8,
            'wrong-topic-' + fixture.stamp, fixture.customer.doctype, fixture.customer.name))
        check_business_lifecycle(fixture.customer)
        print('PASS Telegram/email starts, explicit business, immutable replay, admission recovery, revoked/denied destinations and topic isolation')
finally:
    frappe.destroy()
