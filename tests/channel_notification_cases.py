"""Shared-identity ticket notification admission, recovery and ownership checks."""
import json
from unittest.mock import patch
import frappe
from channel_identity_fixtures import scenario, configured, endpoint
from relay_core import ticket_notifications as notifications, tickets, whatsapp, messaging


def run(separate_contact=False):
    frappe.set_user('Administrator')
    fixture = scenario()
    recipient = fixture.contact
    person = fixture.person
    if separate_contact:
        from channel_site_fixtures import business
        personal_business = business('C2 staff personal ' + fixture.stamp)
        frappe.get_doc({'doctype': 'User Permission', 'user': fixture.actor, 'allow': 'Customer',
            'for_value': personal_business.name, 'apply_to_all_doctypes': 1}).insert()
        person = frappe.get_doc({'doctype': 'Contact', 'first_name': 'Local C2 staff ' + fixture.stamp,
            'links': [{'link_doctype': 'Customer', 'link_name': personal_business.name}]}).insert()
        recipient = frappe.get_doc({'doctype': 'Relay Contact', 'contact': person.name,
            'display_name': 'Local C2 staff'}).insert()
    person.append('email_ids', {'email_id': fixture.actor, 'is_primary': 1})
    person.save()
    if separate_contact:
        # Contact email sync assigns portal roles; this fixture is an authorized internal staff subscriber.
        frappe.get_doc('User', fixture.actor).remove_roles('YRP Customer', 'YRP Partner')
        frappe.clear_cache(user=fixture.actor)
    with configured(fixture), patch.object(whatsapp, 'client') as client:
        bindings = [endpoint(fixture, 'Email', fixture.actor, recipient.name),
                    endpoint(fixture, 'Telegram', '9555000678', recipient.name)]
        source_binding = endpoint(fixture, 'Email', 'ticket-source-' + fixture.stamp + '@example.invalid') if separate_contact else bindings[0]
        source = frappe.get_doc({'doctype': 'Relay Message', 'relay_contact': fixture.contact.name,
            'channel': source_binding.channel, 'sender_endpoint': source_binding.endpoint, 'direction': 'Incoming',
            'content': 'Customer order quantity 25', 'message_type': 'text', 'status': 'Sent',
            'business_doctype': 'Customer', 'business_name': fixture.customer.name}).insert()
        ticket = tickets.create('Local C2 shared notification ' + fixture.stamp, [source.name])['name']
        frappe.db.commit(); frappe.set_user(fixture.actor)
        state = 'Open'
        for index, binding in enumerate(bindings):
            notifications.subscribe(ticket, binding.name)
            for mode in ('success', 'crash', 'changed_business'):
                state = 'In progress' if state == 'Open' else 'Open'
                tickets.update_status(ticket, state); frappe.db.commit()
                notice = frappe.get_doc('Relay Ticket Notification', {'ticket': ticket, 'status': 'Pending'})
                receipt = {'message_id': '<notice-' + mode + fixture.stamp + '@example.invalid>'} if index == 0 else {'message_id': 601 + len(mode)}
                def hub(tool, args):
                    if tool == 'channels.deliveries': return {'deliveries': []}
                    if mode != 'success': raise SystemExit('Local admission crash')
                    return receipt
                client.return_value.call_tool.side_effect = hub
                try: notifications.dispatch(notice.name)
                except SystemExit: pass
                key = 'ticket-' + notice.event_key
                hashed = notifications.digest(*(['email', fixture.actor, key] if index == 0 else [fixture.actor, key]))
                action = frappe.get_doc('Relay Message Action', {'request_key': hashed})
                assert json.loads(action.payload)['business'] == ['Customer', fixture.customer.name]
                if mode == 'changed_business':
                    # The contact stays readable while the ticket's business changes.
                    frappe.set_user('Administrator')
                    user = frappe.get_doc('User', fixture.actor); user.add_roles('Purchase User')
                    grant = frappe.get_doc('User Permission', {'user': fixture.actor, 'allow': 'Supplier'})
                    grant.for_value = fixture.supplier.name; grant.save()
                    frappe.db.set_value('Relay Message', source.name, {'business_doctype': 'Supplier', 'business_name': fixture.supplier.name})
                    frappe.db.commit(); frappe.clear_cache(user=fixture.actor); frappe.set_user(fixture.actor)
                    tickets.read(ticket)
                    client.reset_mock(); client.return_value.call_tool.side_effect = None
                    client.return_value.call_tool.return_value = {'deliveries': []}
                    notifications.dispatch(notice.name)
                    assert frappe.db.get_value('Relay Ticket Notification', notice.name, 'status') == 'Rejected'
                    assert all(call.args[0] == 'channels.deliveries' for call in client.return_value.call_tool.call_args_list)
                    frappe.set_user('Administrator')
                    frappe.db.set_value('Relay Message', source.name, {'business_doctype': 'Customer', 'business_name': fixture.customer.name})
                    frappe.db.commit(); frappe.set_user(fixture.actor)
                    continue
                if mode == 'crash':
                    client.return_value.call_tool.side_effect = [{'deliveries': []}, receipt]
                    notifications.dispatch(notice.name)
                    assert client.return_value.call_tool.call_args.args[1]['request_key'] == action.request_key
                action.reload(); assert action.status == 'Submitted'
                assert frappe.db.get_value('Relay Ticket Notification', notice.name, 'status') == 'Submitted'
                message = frappe.get_doc('Relay Message', action.outbound_message)
                assert message.business_name == fixture.customer.name and message.relay_contact == recipient.name
                client.reset_mock(); notifications.dispatch(notice.name)
                client.return_value.call_tool.assert_not_called()
        if separate_contact:
            # Keeping access to the recipient's personal business cannot expose the ticket's content.
            frappe.set_user('Administrator')
            unrelated = business('C2 staff revocation ' + fixture.stamp)
            grant = frappe.get_doc('User Permission', {'user': fixture.actor, 'allow': 'Customer',
                'for_value': fixture.customer.name})
            grant.for_value = unrelated.name; grant.save(); frappe.db.commit()
            frappe.clear_cache(user=fixture.actor); frappe.set_user(fixture.actor)
            from relay_core.permissions import readable_contact
            readable_contact(recipient.name)
            assert not frappe.get_doc('Customer', fixture.customer.name).has_permission('read')
            assert not frappe.get_list('Relay Message', filters={'relay_contact': recipient.name}, pluck='name')
            assert not message.has_permission('read')
            assert not frappe.get_list('Relay Message Action', filters={'start_contact': recipient.name}, pluck='name')
            print('PASS separately linked staff destinations retain ticket ownership and hide content after business revocation')
        print('PASS shared Customer/Supplier email and Telegram ticket notifications, durable recovery and changed-business rejection')
