"""Local callback identity, sender authentication and real projection contention."""
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from integration_ai_permissions_site import confine_writes
sys.addaudithook(confine_writes)
os.environ['FRAPPE_STREAM_LOGGING'] = '1'

import frappe
from channel_site_fixtures import init, user
from channel_identity_fixtures import scenario, configured, endpoint, incoming, telegram_raw, email_raw
from relay_core import business_routing_prompt, whatsapp
from relay_core.automation import projection


def main():
    init()
    fixture = scenario()
    service = user('local-c3-callback-' + fixture.stamp + '@example.invalid')
    actor = frappe.get_doc('User', service)
    actor.append('roles', {'role':'Relay Hub Service'})
    actor.save(); frappe.db.commit()
    try:
        with configured(fixture), patch.object(whatsapp, 'client') as client:
            for provider, address in (('Telegram', '9555000991'), ('Email', 'prompt-' + fixture.stamp + '@example.invalid')):
                endpoint(fixture, provider, address); frappe.db.commit()
                identifier = '901' if provider == 'Telegram' else '<prompt-' + fixture.stamp + '@example.invalid>'
                raw = telegram_raw(int(address), 901, 'Order quantity 25') if provider == 'Telegram' else email_raw(identifier)
                frappe.set_user(service)
                event, _ = incoming(fixture, provider, address, 'Order quantity 25', raw=raw, identifier=identifier)
                assert event.projection_status == 'Uncategorized'
                state = frappe.get_doc('Relay Business Routing', {'channel':fixture.channels[provider].name, 'endpoint':address})
                action = frappe.get_doc('Relay Message Action', state.prompt_action)
                assert action.owner == 'Administrator' and frappe.session.user == service
                client.return_value.call_tool.side_effect = [{'deliveries':[]},
                    {'message_id':902 if provider == 'Telegram' else '<prompt-reply-' + fixture.stamp + '@example.invalid>'}]
                assert business_routing_prompt.dispatch(action.name)['status'] == 'Submitted'
                assert frappe.session.user == service
                choice = next(row for row in json.loads(state.choices) if row['doctype'] == 'Customer')
                identifier = '903' if provider == 'Telegram' else '<choice-' + fixture.stamp + '@example.invalid>'
                raw = telegram_raw(int(address),903,choice['id'],reply=902) if provider == 'Telegram' else email_raw(identifier,parent='<prompt-reply-' + fixture.stamp + '@example.invalid>')
                selected, _ = incoming(fixture, provider, address, choice['id'], raw=raw, identifier=identifier)
                assert selected.projection_status == 'Projected', selected.routing_decisions
                frappe.set_user('Administrator')
                print('PASS',provider,'service-user prompt ownership, dispatch and sender choice')

            # A separate single-Customer identity must obey the same authentication boundary.
            person = frappe.get_doc(dict(doctype='Contact',first_name='Local C3 single ' + fixture.stamp,
                links=[dict(link_doctype='Customer',link_name=fixture.customer.name)])).insert()
            contact = frappe.get_doc(dict(doctype='Relay Contact',contact=person.name,
                display_name='Local C3 single ' + fixture.stamp)).insert()
            address = 'single-' + fixture.stamp + '@example.invalid'
            endpoint(fixture,'Email',address,contact.name); frappe.db.commit()
            for status in ('fail','unverified'):
                identifier = '<' + status + '-' + fixture.stamp + '@example.invalid>'
                raw = email_raw(identifier); raw['authentication']['status'] = status
                frappe.set_user(service)
                event, _ = incoming(fixture,'Email',address,'Forged order quantity 99',raw=raw,identifier=identifier)
                assert event.projection_status == 'Uncategorized' and 'triage_unverified_sender' in event.routing_decisions
                assert not frappe.db.exists('Relay Message',{'source_key':hashlib.sha256((fixture.account + ':' + fixture.channels['Email'].name + ':' + identifier).encode()).hexdigest()})
            frappe.set_user('Administrator')
            identifier = '<valid-' + fixture.stamp + '@example.invalid>'
            event, _ = incoming(fixture,'Email',address,'Valid quantity 25',raw=email_raw(identifier),identifier=identifier)
            assert event.projection_status == 'Projected'
            print('PASS failed-auth single-Customer email triage and authenticated happy path')
            verify_projection_conflict(fixture, address)
    finally:
        frappe.db.rollback(); frappe.destroy()


def verify_projection_conflict(fixture, address):
    from frappe.model import naming
    identifier = '<contention-' + fixture.stamp + '@example.invalid>'
    with patch.object(projection, 'project'):
        event, _ = incoming(fixture,'Email',address,'Contention quantity 37',raw=email_raw(identifier),identifier=identifier)
    assert event.projection_status == 'Pending'
    sites = frappe.local.sites_path
    original = naming.getseries
    attempts, conflicts = [], []

    def advance_series(key, digits):
        frappe.init(site='yrp.site', sites_path=sites); frappe.connect()
        frappe.flags.mute_emails = True
        try:
            original(key, digits); frappe.db.commit()
        finally:
            frappe.destroy()

    def competing_name(key, digits):
        if key != 'RELAY-MSG-':
            return original(key, digits)
        attempts.append(True)
        if len(attempts) == 1:
            frappe.db.sql('select current from tabSeries where name=%s', (key,))
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(advance_series, key, digits).result(timeout=10)
        try:
            return original(key, digits)
        except frappe.QueryDeadlockError as exc:
            conflicts.append(str(exc))
            raise

    with patch.object(naming, 'getseries', side_effect=competing_name):
        projection.project_queued(event.name, submitted_ns=time.time_ns())
        frappe.db.commit()
    assert len(attempts) == 2 and len(conflicts) == 1, (len(attempts),len(conflicts))
    assert '1020' in conflicts[0] and 'tabSeries' in conflicts[0]
    projection.project_queued(event.name, submitted_ns=time.time_ns()); frappe.db.commit()
    event.reload()
    assert event.projection_status == 'Projected'
    assert frappe.db.count('Relay Message', {'source_key':hashlib.sha256((fixture.account + ':' + fixture.channels['Email'].name + ':' + identifier).encode()).hexdigest()}) == 1
    print('PASS real tabSeries 1020 retries the whole projection transaction; one message after replay')


if __name__ == '__main__':
    main()
