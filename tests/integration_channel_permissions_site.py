"""Shared-identity revocation and pre-snapshot action recovery on yrp.site."""
import json
from unittest.mock import patch
import frappe
from channel_site_fixtures import init
from channel_identity_fixtures import scenario, configured, endpoint, incoming, email_raw, fails
from relay_core import enrollment, telegram_delivery, messaging, whatsapp
from relay_core.business_access import action_permission

init()
try:
    fixture = scenario()
    with configured(fixture), patch.object(whatsapp, 'client') as client:
        # A Customer-only manager must never see unresolved Supplier/account content.
        event, _ = incoming(fixture, 'Email', 'unowned-' + fixture.stamp + '@example.invalid',
            'Supplier private quantity 75', raw=email_raw('<unowned-' + fixture.stamp + '@example.invalid>'))
        assert any(row['event'] == event.name for row in enrollment.pending()['items'])
        frappe.set_user(fixture.actor)
        fails(enrollment.pending)
        fails(lambda: enrollment.event_rows(event.name))
        frappe.set_user('Administrator')

        # Even an administrator with restricted business permissions cannot preview a shared owner's content.
        email_binding = endpoint(fixture, 'Email', 'shared-' + fixture.stamp + '@example.invalid')
        shared, _ = incoming(fixture, 'Email', email_binding.endpoint, 'Supplier private shared quantity 75',
            raw=email_raw('<shared-' + fixture.stamp + '@example.invalid>'))
        admin_reader = 'relay-c2-admin-reader-' + fixture.stamp + '@example.invalid'
        from channel_site_fixtures import user as fixture_user
        fixture_user(admin_reader, manager=True)
        frappe.get_doc('User', admin_reader).add_roles('System Manager')
        for doctype, value in [('Customer', fixture.customer.name), ('Supplier', frappe.db.get_value(
                'User Permission', {'user': fixture.actor, 'allow': 'Supplier'}, 'for_value'))]:
            frappe.get_doc({'doctype': 'User Permission', 'user': admin_reader, 'allow': doctype,
                'for_value': value, 'apply_to_all_doctypes': 1}).insert()
        frappe.db.commit(); frappe.set_user(admin_reader)
        assert not frappe.get_doc('Supplier', fixture.supplier.name).has_permission('read')
        for hidden in (event, shared):
            fails(lambda: frappe.get_doc('Relay Hub Event', hidden.name).check_permission('read'))
            assert not frappe.get_list('Relay Hub Event', filters={'name': hidden.name}, fields=['name', 'payload'])
            fails(lambda: enrollment.event_rows(hidden.name))
        assert shared.name not in {row['event'] for row in enrollment.pending()['items']}
        enrollment.revoke(email_binding.name); frappe.db.commit()
        assert shared.name not in {row['event'] for row in enrollment.pending()['items']}
        frappe.set_user('Administrator')
        user = frappe.get_doc('User', fixture.actor)
        user.add_roles('Purchase User')
        grant = frappe.get_doc('User Permission', {'user': fixture.actor, 'allow': 'Supplier'})
        unrelated = grant.for_value
        grant.for_value = fixture.supplier.name; grant.save(); frappe.db.commit()
        frappe.clear_cache(user=fixture.actor)
        group = endpoint(fixture, 'Telegram', '-9555000789')
        wa = endpoint(fixture, 'WhatsApp', '919555000789')
        fixture.person.append('phone_nos', {'phone': wa.endpoint, 'is_primary_mobile_no': 1}); fixture.person.save()
        frappe.db.commit()
        sources = []
        for business in (fixture.customer, fixture.supplier):
            sources.append(frappe.get_doc({'doctype': 'Relay Message', 'relay_contact': fixture.contact.name,
                'channel': wa.channel, 'sender_endpoint': wa.endpoint, 'direction': 'Incoming',
                'content': business.doctype + ' quantity 25', 'message_type': 'text', 'status': 'Sent',
                'business_doctype': business.doctype, 'business_name': business.name,
                'provider_context': json.dumps({'provider': 'WhatsApp', 'message_id': business.doctype + fixture.stamp})}).insert())
        frappe.db.commit()
        for reader in (fixture.actor, admin_reader):
            frappe.set_user(reader); client.reset_mock()
            history = whatsapp.conversation(fixture.person.name, 'Customer', fixture.customer.name, after='0')
            assert [row['text'] for row in history['messages']] == ['Customer quantity 25']
            assert 'Supplier' not in json.dumps(history, default=str)
            client.return_value.execute.assert_not_called()
        frappe.set_user(fixture.actor)
        frappe.get_doc('Supplier', fixture.supplier.name).check_permission('read')
        client.return_value.call_tool.side_effect = TimeoutError('Local unknown Telegram acceptance')
        pending = []
        for business in (fixture.customer, fixture.supplier):
            pending.append(telegram_delivery.send_group(fixture.contact.name, group.channel, int(group.endpoint),
                business.doctype + ' private quantity 25', 0, 0, business.doctype + fixture.stamp,
                business.doctype, business.name))
        assert {item['action'] for item in telegram_delivery.pending(group.name)['items']} == {row['action'] for row in pending}

        # Real journal entries from before business snapshots: only their readable source grants access.
        legacy = []
        client.return_value.call_tool.side_effect = SystemExit('Local pre-admission crash')
        for source in sources:
            try:
                messaging.send(source.name, 'text', {'text': 'Legacy quantity 25'}, 'legacy-' + source.name)
            except SystemExit:
                pass
            action = frappe.get_doc('Relay Message Action', {'source_message': source.name})
            payload = json.loads(action.payload); payload.pop('business')
            if source.business_doctype == 'Supplier':
                payload['business'] = [None, None]
            frappe.db.set_value('Relay Message Action', action.name, 'payload', json.dumps(payload))
            legacy.append(action.name)
        frappe.db.commit()
        for name in legacy:
            assert action_permission(frappe.get_doc('Relay Message Action', name))
        assert set(legacy) <= set(frappe.get_list('Relay Message Action', pluck='name'))
        assert set(legacy) <= {row['action'] for row in messaging.pending_messages(fixture.contact.name)['items']}

        client.return_value.call_tool.side_effect = [{'deliveries': []}, {'messages': [{'id': 'null-restored-' + fixture.stamp}]}]
        null_action = frappe.get_doc('Relay Message Action', legacy[1])
        assert messaging.reconcile(null_action.name)['status'] == 'Submitted'
        assert client.return_value.call_tool.call_args.args[1]['request_key'] == null_action.request_key
        null_action.reload()
        assert frappe.get_doc('Relay Message', null_action.outbound_message).business_name == fixture.supplier.name

        frappe.set_user('Administrator'); grant.reload(); grant.for_value = unrelated; grant.save(); frappe.db.commit()
        frappe.clear_cache(user=fixture.actor); frappe.set_user(fixture.actor)
        from relay_core.permissions import readable_contact
        readable_contact(fixture.contact.name)
        assert action_permission(frappe.get_doc('Relay Message Action', pending[0]['action']))
        assert not action_permission(frappe.get_doc('Relay Message Action', pending[1]['action']))
        visible = telegram_delivery.pending(group.name)['items']
        assert [row['action'] for row in visible] == [pending[0]['action']]
        assert 'Supplier private' not in json.dumps(visible, default=str)
        assert legacy[0] in frappe.get_list('Relay Message Action', pluck='name')
        assert legacy[1] not in frappe.get_list('Relay Message Action', pluck='name')
        assert legacy[0] in {row['action'] for row in messaging.pending_messages(fixture.contact.name)['items']}
        client.reset_mock(); client.return_value.call_tool.side_effect = None
        fails(lambda: messaging.reconcile(legacy[1]))
        client.return_value.call_tool.assert_not_called()
        client.return_value.call_tool.side_effect = [{'deliveries': []}, {'messages': [{'id': 'legacy-restored-' + fixture.stamp}]}]
        assert messaging.reconcile(legacy[0])['status'] == 'Submitted'
        assert client.return_value.call_tool.call_args.args[1]['request_key'] == frappe.db.get_value('Relay Message Action', legacy[0], 'request_key')
        frappe.set_user('Administrator')
        frappe.db.set_value('Relay Message', sources[0].name, {'business_doctype': None, 'business_name': None})
        frappe.db.commit(); frappe.set_user(fixture.actor)
        assert not action_permission(frappe.get_doc('Relay Message Action', legacy[0]))
        assert legacy[0] not in frappe.get_list('Relay Message Action', pluck='name')
        print('PASS admin-only unresolved previews; shared Customer/Supplier revocation filters pending payloads')
        print('PASS legacy WhatsApp actions restore/read/reconcile through source permissions and fail closed on ambiguity')
finally:
    from channel_identity_fixtures import cleanup
    if "fixture" in globals(): cleanup(fixture)
    frappe.destroy()
