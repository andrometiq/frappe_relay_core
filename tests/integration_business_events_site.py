"""Local populated channel-event proof, with external sends intercepted."""
import json
from unittest.mock import patch

import frappe
from channel_site_fixtures import init, check_business_lifecycle
from channel_identity_fixtures import scenario, configured, endpoint, fails
from relay_core import business_events, channel_preferences, whatsapp, messaging
from relay_core.ai.tools import as_user


def main():
    init()
    fixture = scenario()
    rules = []
    try:
        with configured(fixture), patch.object(whatsapp, 'client') as client:
            tg = endpoint(fixture,'Telegram','9555000421')
            em = endpoint(fixture,'Email','events-' + fixture.stamp + '@example.invalid')
            prefs = []
            for binding, priority in ((tg,1),(em,2)):
                prefs.append(frappe.get_doc(dict(doctype='Relay Channel Preference', contact=fixture.person.name,
                    business_doctype='Customer', business_name=fixture.customer.name,
                    endpoint=binding.name, consent='Granted', priority=priority)).insert())
            frappe.db.commit()
            with as_user(fixture.actor):
                assert channel_preferences.resolve(fixture.person.name,'Customer',fixture.customer.name)['endpoint'] == tg.name
                fails(lambda: channel_preferences.resolve(fixture.person.name,'Supplier',fixture.supplier.name))
            # No consent carries from Customer to the same person's Supplier business.
            fails(lambda: channel_preferences.resolve(fixture.person.name,'Supplier',fixture.supplier.name))
            supplier_pref = frappe.get_doc(dict(doctype='Relay Channel Preference', contact=fixture.person.name,
                business_doctype='Supplier', business_name=fixture.supplier.name,
                endpoint=em.name, consent='Denied', priority=1)).insert()
            frappe.db.commit()
            with as_user(fixture.actor):
                assert not supplier_pref.has_permission('read')
                assert not frappe.get_list('Relay Channel Preference',filters={'name':supplier_pref.name})
            fiscal_year = frappe.db.get_value('Fiscal Year',{'disabled':0,
                'year_start_date':['<=',frappe.utils.nowdate()],'year_end_date':['>=',frappe.utils.nowdate()]},'name')
            company_name = frappe.db.get_value('Fiscal Year Company',{'parent':fiscal_year},'company')
            company = frappe.get_doc('Company',company_name or frappe.db.get_value('Company',{},'name'))
            item = frappe.get_doc(dict(doctype='Item',item_code='LOCAL-C3-' + fixture.stamp,
                item_name='Local C3 fabric',item_group=frappe.db.get_value('Item Group',{'is_group':0},'name'),
                stock_uom=frappe.db.get_value('UOM',{},'name'),is_stock_item=0,
                gst_hsn_code=frappe.db.get_value('GST HSN Code',{},'name'))).insert()
            frappe.db.commit()
            for provider,binding in (('Telegram',tg),('Email',em)):
                prefs[0].priority = 1 if provider == 'Telegram' else 20
                prefs[0].save(); frappe.db.commit()
                rule = frappe.get_doc(dict(doctype='Relay Business Event Rule', title='Local C3 ' + provider,
                    enabled=1, use_preferences=1, source_doctype='Sales Order', event='after_insert', recipient_field='customer',
                    business_doctype='Customer', contact=fixture.person.name, channel=binding.channel,
                    run_as_user=fixture.actor, parameter_mapping=json.dumps(['name','total_qty','grand_total']),
                    telegram_body='Order {name}: quantity {total_qty}, total {grand_total}',
                    email_subject='Order {name}', email_body='Quantity {total_qty}\nTotal {grand_total}',
                    email_signature='Local <Support> & team')).insert()
                rules.append(rule)
                frappe.db.commit()
                # Revoked execution-user access must not roll back the business insert.
                from channel_site_fixtures import business
                denied_customer=business('Event denied '+fixture.stamp+' '+provider)
                permission=frappe.get_doc('User Permission',{'user':fixture.actor,'allow':'Customer'})
                permission.for_value=denied_customer.name;permission.save();frappe.db.commit();frappe.clear_cache(user=fixture.actor)
                denied_order=frappe.get_doc(dict(doctype='Sales Order', customer=fixture.customer.name,
                    company=company.name,currency=company.default_currency,transaction_date=frappe.utils.nowdate(),
                    delivery_date=frappe.utils.add_days(frappe.utils.nowdate(),7),
                    items=[dict(item_code=item.name,qty=25,rate=50,delivery_date=frappe.utils.add_days(frappe.utils.nowdate(),7))])).insert()
                frappe.db.commit()
                assert frappe.db.exists('Sales Order',denied_order.name)
                assert not frappe.db.exists('Relay Business Event Delivery',{'rule':rule.name,'source_name':denied_order.name})
                permission.for_value=fixture.customer.name;permission.save();frappe.db.commit();frappe.clear_cache(user=fixture.actor)
                # Real source insertion invokes the transaction hook and captures after-commit work.
                order = frappe.get_doc(dict(doctype='Sales Order', customer=fixture.customer.name,
                    company=company.name,currency=company.default_currency,transaction_date=frappe.utils.nowdate(),
                    delivery_date=frappe.utils.add_days(frappe.utils.nowdate(),7),
                    items=[dict(item_code=item.name,qty=25,rate=50,delivery_date=frappe.utils.add_days(frappe.utils.nowdate(),7))])).insert()
                name = frappe.db.get_value('Relay Business Event Delivery',{'rule':rule.name,'source_name':order.name},'name')
                assert name, 'Business insertion must capture a real delivery intent'
                assert name=='RELAY-BED-'+frappe.db.get_value('Relay Business Event Delivery',name,'event_key')
                delivery = frappe.get_doc('Relay Business Event Delivery',name)
                original = delivery.payload
                assert '1250' in original and '25' in original
                assert json.loads(original)['selection']['endpoint'] == binding.name
                frappe.db.commit()
                calls = client.return_value.call_tool.call_count
                business_events.capture(rule,order,'after_insert')
                assert frappe.db.count('Relay Business Event Delivery',{'rule':rule.name,'source_name':order.name}) == 1
                assert client.return_value.call_tool.call_count == calls
                # Updates do not rewrite a pending content snapshot.
                order.items[0].qty = 30; order.save(); frappe.db.commit()
                assert frappe.db.get_value('Relay Business Event Delivery',name,'payload') == original
                client.return_value.call_tool.return_value = {'pending':True,'state':'queued','delivery_id':41}
                business_events.dispatch(name)
                delivery.reload()
                assert delivery.status == 'Queued', (delivery.status,delivery.action)
                args = client.return_value.call_tool.call_args.args[1]
                assert '25' in args.get('text',args.get('body',''))
                if provider == 'Email':
                    from html import escape
                    assert escape(rule.email_signature) in args['html'], repr(args['html'])
                    assert args['html'] == json.loads(original)['data']['html']
                    assert args['subject'] == 'Order ' + order.name
                action = frappe.get_doc('Relay Message Action',delivery.action)
                assert json.loads(action.payload)['business_event'] == delivery.name
                # Admission is pending: no preference reselection, no extra send.
                calls = client.return_value.call_tool.call_count
                prefs[0].priority = 20; prefs[0].save(); frappe.db.commit()
                business_events.dispatch(name)
                assert client.return_value.call_tool.call_count == calls
                fails(lambda: channel_preferences.resolve(fixture.person.name,'Customer',fixture.customer.name,previous_status='Uncertain'))
                from channel_site_fixtures import push_status
                receipt = {'message_id':921 if provider == 'Telegram' else '<event-' + fixture.stamp + '@example.invalid>'}
                push_status(fixture.account,[dict(id=421,delivery_id=41,operation='telegram.message' if provider=='Telegram' else 'email.send',
                    request_key=action.request_key,state='submitted',receipt=receipt,occurred_at='2026-10-24T00:00:00Z')])
                frappe.db.commit(); delivery.reload()
                assert delivery.status == 'Submitted', 'Callback must complete the event without polling'
                business_events.recover(); frappe.db.commit(); delivery.reload()
                assert delivery.status == 'Submitted'
                assert frappe.db.get_value('Relay Message Action',action.name,'status') == 'Submitted'
                assert client.return_value.call_tool.call_count == calls
                assert not frappe.get_all('Relay Message',filters={'business_name':fixture.supplier.name,'channel':binding.channel})
                check_business_lifecycle(fixture.customer)
                check_business_lifecycle(order)
                # Crash after the action journal commits but before Hub admission.
                # Restore this provider's priority before capturing another intent.
                prefs[0].priority = 1 if provider == 'Telegram' else 20
                prefs[0].save(); frappe.db.commit()
                def new_delivery():
                    new_order = frappe.copy_doc(order).insert()
                    frappe.db.commit()
                    return frappe.get_doc('Relay Business Event Delivery',{'rule':rule.name,'source_name':new_order.name})
                crashed = new_delivery()
                client.return_value.call_tool.side_effect = SystemExit('Local event pre-admission crash')
                try:
                    business_events.dispatch(crashed.name)
                except SystemExit:
                    pass
                original_action = frappe.get_doc('Relay Message Action',{'request_key':business_events.action_key(crashed,rule)})
                client.return_value.call_tool.side_effect = [{'deliveries':[]},
                    {'message_id':922 if provider == 'Telegram' else '<event-recovered-' + fixture.stamp + '@example.invalid>'}]
                business_events.dispatch(crashed.name)
                crashed.reload()
                assert crashed.status == 'Submitted' and crashed.action == original_action.name
                assert client.return_value.call_tool.call_args.args[1]['request_key'] == original_action.request_key
                client.return_value.call_tool.side_effect = None

                blocked = new_delivery()
                selected_pref = prefs[0] if provider == 'Telegram' else prefs[1]
                selected_pref.consent = 'Denied'; selected_pref.save(); frappe.db.commit()
                calls = client.return_value.call_tool.call_count
                business_events.dispatch(blocked.name); blocked.reload()
                assert blocked.status == 'Failed' and not blocked.action
                assert client.return_value.call_tool.call_count == calls
                selected_pref.consent = 'Granted'; selected_pref.save(); frappe.db.commit()

                uncertain = new_delivery()
                client.return_value.call_tool.side_effect = TimeoutError('Local ambiguous acceptance')
                business_events.dispatch(uncertain.name); uncertain.reload()
                assert uncertain.status == 'Uncertain' and uncertain.action
                calls = client.return_value.call_tool.call_count
                business_events.dispatch(uncertain.name)
                assert client.return_value.call_tool.call_count == calls
                client.return_value.call_tool.side_effect = None

                transient = new_delivery()
                with patch.object(business_events,'delivery_scope',side_effect=frappe.TimestampMismatchError('Local conflict')):
                    business_events.dispatch(transient.name)
                transient.reload()
                assert transient.status == 'Pending' and not transient.action
                client.return_value.call_tool.return_value = {'message_id':923 if provider=='Telegram' else '<conflict-' + fixture.stamp + '@example.invalid>'}
                business_events.dispatch(transient.name); transient.reload()
                assert transient.status == 'Submitted', (transient.name,transient.status,transient.action)

                # A burst of independent pending deliveries completes through signed receipts.
                burst = []
                client.return_value.call_tool.return_value = {'pending':True,'state':'queued','delivery_id':42}
                for index in range(12):
                    pending = new_delivery(); business_events.dispatch(pending.name); pending.reload()
                    if pending.status == 'Failed':
                        business_events.delivery_scope(pending)
                    assert pending.status == 'Queued', (pending.status,pending.action,pending.name)
                    burst.append(pending)
                calls = client.return_value.call_tool.call_count
                for index,pending in enumerate(burst):
                    queued = frappe.get_doc('Relay Message Action',pending.action)
                    identifier = 1000 + index if provider=='Telegram' else '<burst-' + str(index) + '-' + fixture.stamp + '@example.invalid>'
                    push_status(fixture.account,[dict(id=500+index,delivery_id=42,request_key=queued.request_key,
                        operation='telegram.message' if provider=='Telegram' else 'email.send',state='submitted',
                        receipt={'message_id':identifier},occurred_at='2026-10-24T00:00:00Z')])
                    pending.reload();assert pending.status == 'Submitted'
                assert client.return_value.call_tool.call_count == calls
                rejected = new_delivery(); business_events.dispatch(rejected.name); rejected.reload()
                rejected_action = frappe.get_doc('Relay Message Action',rejected.action)
                push_status(fixture.account,[dict(id=700,delivery_id=42,request_key=rejected_action.request_key,
                    operation='telegram.message' if provider=='Telegram' else 'email.send',state='rejected',
                    receipt={},occurred_at='2026-10-24T00:00:00Z')])
                selected_pref.consent = 'Denied'; selected_pref.save(); frappe.db.commit()
                calls = client.return_value.call_tool.call_count
                with as_user(fixture.actor):
                    fails(lambda: messaging.retry(rejected_action.name), exceptions=(frappe.PermissionError,))
                    history = messaging.actions(fixture.contact.name)['items']
                    assert next(row for row in history if row['name']==rejected_action.name)['can_retry'] is False
                assert client.return_value.call_tool.call_count == calls
                selected_pref.consent = 'Granted'; selected_pref.save(); frappe.db.commit()

                # Orphan rows must leave the oldest recovery page without link validation errors.
                missing = []
                for index in range(20):
                    orphan = frappe.copy_doc(rejected)
                    orphan.name = 'LOCAL-C3-ORPHAN-' + provider + '-' + fixture.stamp + '-' + str(index)
                    orphan.event_key = orphan.name
                    orphan.rule = 'LOCAL-C3-MISSING-' + fixture.stamp
                    orphan.status, orphan.action, orphan.docstatus = 'Pending', None, 0
                    orphan.creation = '2000-01-01 00:00:00'
                    orphan.db_insert(); missing.append(orphan.name)
                later = new_delivery()
                frappe.db.set_value('Relay Business Event Delivery',later.name,'creation','2000-01-02 00:00:00')
                frappe.db.commit(); frappe.enqueue.reset_mock()
                business_events.recover()
                jobs = [c.kwargs['name'] for c in frappe.enqueue.call_args_list
                        if c.args == ('relay_core.business_events.dispatch',)]
                assert set(jobs) == set(missing)
                for job in jobs: business_events.dispatch(job)
                assert frappe.db.count('Relay Business Event Delivery',{'name':['in',missing],'status':'Failed'}) == 20
                frappe.enqueue.reset_mock(); business_events.recover()
                assert any(c.kwargs.get('name') == later.name for c in frappe.enqueue.call_args_list)
                business_events.dispatch(later.name); later.reload()
                assert later.status == 'Queued'
                print('PASS',provider,'revoked-consent retries blocked and recovery advances beyond 20 missing rules')
                rule.enabled=0;rule.save();frappe.db.commit()
                print('PASS',provider,'real order insertion, consent, immutable quantity 25/1250 snapshot, callback completion, crash recovery, revoked consent, uncertainty, 12-receipt burst and lifecycle independence')
    finally:
        frappe.set_user('Administrator')
        for rule in rules:
            frappe.db.set_value('Relay Business Event Rule',rule.name,'enabled',0)
        business_events.clear_rule_cache(); frappe.db.commit()
        frappe.destroy()


if __name__ == '__main__':
    main()
