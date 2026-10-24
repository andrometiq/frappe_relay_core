"""Step 4: local signed ingress, triage recovery, enrollment and HTTP isolation.

Run with the worktree first on PYTHONPATH and the version_16 bench Python -B.
Only yrp.site is accepted. Provider delivery and background dispatch are blocked.
"""
import json
import os
from pathlib import Path
import secrets
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from urllib.parse import quote

from integration_ai_permissions_site import confine_writes

SITES = '/home/sakthi/development/pilot/benches/version_16/sites'
ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.addaudithook(confine_writes)
    os.environ.update(FRAPPE_STREAM_LOGGING='1', RELAY_AUTOMATION_TEST_SITES=SITES,
                      RELAY_TEST_SITE='yrp.site', SITES_PATH=SITES)
    import frappe
    import frappe.app
    import relay_core
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    from channel_site_fixtures import init, user
    from channel_identity_fixtures import scenario, cleanup, configured, incoming, email_raw, endpoint
    from relay_core.automation import projection
    from relay_core import tickets

    assert Path(relay_core.__file__).resolve().parents[1] == ROOT
    init()
    assert frappe.local.site == 'yrp.site'
    # The preceding steps' schemas are dependencies; all imports use this checkout.
    for name in ('relay_channel', 'relay_ticket', 'relay_message', 'relay_automation_run'):
        frappe.reload_doc('relay_core', 'doctype', name, force=True)
    frappe.db.commit()
    print('RELOADED Relay Channel, Relay Ticket, Relay Message, Relay Automation Run from worktree JSON')
    fixture = scenario()
    try:
        companies = []
        for title in ('Triage North', 'Triage South'):
            name = 'Sim ' + title + ' ' + fixture.stamp
            frappe.get_doc(dict(doctype='Company', name=name, company_name=name, abbr='ST',
                country='India', default_currency='INR')).db_insert()
            companies.append(name)
        channel = fixture.channels['Email']
        frappe.db.set_value('Relay Channel', channel.name, dict(company=companies[0], triage_owner=fixture.actor))
        denied = user('sim-triage-denied-' + fixture.stamp.lower() + '@example.invalid', manager=True)
        for actor, company in ((fixture.actor, companies[0]), (denied, companies[1])):
            frappe.get_doc(dict(doctype='User Permission', user=actor, allow='Company',
                for_value=company, apply_to_all_doctypes=1)).insert()
        auth = {}
        for actor in (fixture.actor, denied):
            doc = frappe.get_doc('User', actor)
            doc.api_key, doc.api_secret = secrets.token_hex(12), secrets.token_hex(24)
            auth[actor] = 'token ' + doc.api_key + ':' + doc.api_secret
            doc.save()
        frappe.db.commit()
        sender = 'sim-triage-' + fixture.stamp.lower() + '@example.invalid'
        with configured(fixture):
            def receive(title, sender=sender):
                identifier = '<sim-' + title + '-' + fixture.stamp.lower() + '@example.invalid>'
                return incoming(fixture, 'Email', sender, 'Private payment amount 1250 quantity 25',
                                identifier=identifier, raw=email_raw(identifier))

            event, provider = receive('unknown')
            ticket = frappe.get_doc('Relay Ticket', {'source_hub_event':event.name})
            assert ticket.company == companies[0] and ticket.assigned_to == fixture.actor
            assert not ticket.messages and not ticket.business_name
            assert '1250' not in ticket.as_json() and 'Private payment' not in ticket.as_json()
            assert event.projection_status == 'Uncategorized'
            assert not frappe.db.exists('Relay Message', {'provider_id':provider})
            # incoming() already repeats the signed callback. A different Hub ID with
            # the same provider identity must also reuse the original ticket.
            duplicate, _ = receive('unknown')
            assert duplicate.name != event.name
            assert frappe.db.count('Relay Ticket', {'source_action_key':ticket.source_action_key}) == 1
            assert frappe.db.count('Relay Ticket', {'source_provider_message_key':ticket.source_provider_message_key}) == 1
            print('PASS unknown sender and repeated signed callbacks: one assigned sanitized triage ticket')

            # Independent worker connections race on different Hub event IDs for
            # one provider message. No business record is used as a mutex.
            from relay_core.inbound import insert_event
            payload = json.loads(event.payload)
            race_provider = '<sim-race-' + fixture.stamp.lower() + '@example.invalid>'
            payload.update(provider_id=race_provider, payload=email_raw(race_provider))
            race_events = [insert_event(dict(account=fixture.account,
                event_key='Sim Triage Race '+word+' '+fixture.stamp,
                hub_event_id='Sim '+word+' '+fixture.stamp, payload=json.dumps(payload))).name
                for word in ('First', 'Second')]
            frappe.db.commit()
            barrier = Barrier(2)
            def project_worker(name):
                frappe.init(site='yrp.site', sites_path=SITES); frappe.connect()
                frappe.set_user('Administrator'); frappe.flags.mute_emails = True
                try:
                    barrier.wait(timeout=10)
                    projection.project_queued(name, submitted_ns=time.time_ns())
                    frappe.db.commit()
                finally:
                    frappe.destroy()
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(project_worker, name) for name in race_events]
                for future in futures: future.result(timeout=30)
            frappe.db.rollback()
            race_key, _ = tickets.source_episode(channel.name, projection.extract_messages(payload)[0])
            assert frappe.db.count('Relay Ticket', {'source_provider_message_key':race_key}) == 1
            print('PASS concurrent duplicate projection workers create one source ticket')

            ambiguous_sender = 'sim-ambiguous-' + fixture.stamp.lower() + '@example.invalid'
            endpoint(fixture, 'Email', ambiguous_sender)
            ambiguous_event, ambiguous_provider = receive('ambiguous', sender=ambiguous_sender)
            ambiguous_ticket = frappe.get_doc('Relay Ticket', {'source_hub_event':ambiguous_event.name})
            assert not ambiguous_ticket.business_name and not ambiguous_ticket.messages
            assert ambiguous_event.projection_status == 'Uncategorized'
            assert frappe.db.count('Relay Message', {'provider_id':ambiguous_provider}) == 0
            print('PASS verified sender with Customer/Supplier ambiguity stays in company triage')

            # No eligible owner: preserve the source, then recover after restoring one.
            missing_sender = 'sim-triage-recovery-' + fixture.stamp.lower() + '@example.invalid'
            frappe.db.set_value('Relay Channel', channel.name, 'triage_owner', denied)
            original_single = frappe.get_single
            def settings(doctype):
                return frappe._dict(ai_handoff_owner=denied) if doctype == 'Relay Settings' else original_single(doctype)
            with patch.object(frappe, 'get_single', side_effect=settings):
                missing, missing_provider = receive('recovery', sender=missing_sender)
                assert not frappe.db.exists('Relay Ticket', {'source_hub_event':missing.name})
                assert missing.projection_status == 'Uncategorized'
                # A newly bound sender still cannot bypass the missing ticket intent.
                endpoint(fixture, 'Email', missing_sender)
                projection.project(missing.name, business_overrides={missing_provider:(fixture.customer.doctype, fixture.customer.name)})
                assert not frappe.db.exists('Relay Message', {'provider_id':missing_provider})
                frappe.db.commit()
            frappe.db.set_value('Relay Channel', channel.name, 'triage_owner', fixture.actor)
            projection.project(missing.name)
            frappe.db.commit()
            recovered = frappe.get_doc('Relay Ticket', {'source_hub_event':missing.name})
            assert recovered.assigned_to == fixture.actor
            # Primary loses company access, eligible configured backup takes over admission.
            frappe.db.set_value('Relay Channel', channel.name, 'triage_owner', denied)
            def fallback(doctype):
                return frappe._dict(ai_handoff_owner=fixture.actor) if doctype == 'Relay Settings' else original_single(doctype)
            with patch.object(frappe, 'get_single', side_effect=fallback):
                backup_event, _ = receive('backup', sender='sim-backup-'+fixture.stamp.lower()+'@example.invalid')
            assert frappe.db.get_value('Relay Ticket', {'source_hub_event':backup_event.name}, 'assigned_to') == fixture.actor
            frappe.db.set_value('Relay Channel', channel.name, 'triage_owner', fixture.actor)
            frappe.db.commit()
            print('PASS owner/company denial preserves recoverable intent; recovery and eligible fallback succeed')

            ticket_name, event_name = ticket.name, event.name
            frappe.destroy()
            client = Client(frappe.app.application, Response)
            def request(path, *, actor=fixture.actor, method='GET', data=None):
                return client.open(path, method=method, data=data,
                    headers={'Authorization':auth[actor]} if actor else {}, base_url='http://yrp.site')
            prefix = '/api/method/relay_core.'
            for path in (prefix+'tickets.read?name='+ticket_name, '/api/resource/Relay Ticket/'+ticket_name):
                allowed = request(path)
                assert allowed.status_code == 200, ('read status', allowed.status_code)
                record = allowed.json.get('message', allowed.json.get('data'))
                assert record['company'] == companies[0] and record['messages'] == []
                assert '1250' not in allowed.get_data(as_text=True)
                for actor in (denied, None):
                    response = request(path, actor=actor)
                    assert response.status_code in (401, 403) and response.json['exc_type'] == 'PermissionError'
            resource = '/api/resource/Relay Ticket?filters='+quote(json.dumps({'name':ticket_name}))
            assert len(request(resource).json['data']) == 1
            result = request(resource, actor=denied)
            assert result.status_code == 200 and result.json['data'] == []
            raw = request('/api/resource/Relay Hub Event/'+event_name)
            assert raw.status_code == 403 and raw.json['exc_type'] == 'PermissionError'
            raw = request('/api/resource/Relay Hub Event?fields='+quote(json.dumps(['name','payload'])))
            assert raw.status_code == 403 or raw.status_code == 200 and raw.json['data'] == []
            pending = request(prefix+'enrollment.pending')
            assert pending.status_code == 200
            data = pending.json['message']
            assert set(data) == {'items', 'next'}
            item = next(row for row in data['items'] if row['event'] == event_name)
            assert item['ticket'] == ticket_name and item['contact'] is None
            assert item['preview'] == 'Incoming conversation needs triage'
            assert '1250' not in pending.get_data(as_text=True)
            assert request(prefix+'enrollment.pending', actor=denied).json['message']['items'] == []
            assert request(prefix+'enrollment.pending', actor=None).status_code in (401, 403)
            assert request(prefix+'enrollment.pending', method='POST').status_code == 403
            for method in ('automation.projection.project', 'enrollment.event_rows'):
                assert request(prefix+method, method='POST', data={'name':event_name}).status_code == 403
            transcript = request(prefix+'tickets.transcript?name='+ticket_name)
            assert transcript.status_code == 200 and transcript.json['message'] == {'items':[], 'next':None}
            for method in ('source_episode', 'triage_owner', 'ensure_episode', '_ensure_triage', '_save_episode'):
                assert request(prefix+'tickets.'+method, method='POST').status_code == 403
            assert request(prefix+'enrollment.source_ticket', method='POST').status_code == 403
            # Direct writes cannot forge a triage company's source boundary.
            forged = request('/api/resource/Relay Ticket/'+ticket_name, method='PUT',
                             data={'company':companies[1]})
            assert forged.status_code == 403
            print('PASS HTTP read/list/pending/transcript shape; cross-company/guest/raw-event/internal-method/write denial')

            bind = dict(event=event_name, provider_id=provider, contact=fixture.contact.name,
                        business_doctype=fixture.customer.doctype, business_name=fixture.customer.name)
            refused = request(prefix+'enrollment.bind', actor=denied, method='POST', data=bind)
            assert refused.status_code == 403 and refused.json['exc_type'] == 'PermissionError'
            wrong_business = request(prefix+'enrollment.bind', method='POST',
                data=dict(bind, business_doctype=fixture.supplier.doctype, business_name=fixture.supplier.name))
            assert wrong_business.status_code == 403
            result = request(prefix+'enrollment.bind', method='POST', data=bind)
            assert result.status_code == 200, ('bind status', result.status_code, result.json.get('exc_type'))
            assert result.json['message'] == {'contact':fixture.contact.name, 'event':event_name, 'status':'Projected'}
            result = request(prefix+'enrollment.bind', method='POST', data=bind)
            assert result.status_code == 200 and result.json['message']['status'] == 'Projected'
            read = request(prefix+'tickets.read?name='+ticket_name).json['message']
            assert read['business_name'] == fixture.customer.name and len(read['messages']) == 1
            transcript = request(prefix+'tickets.transcript?name='+ticket_name).json['message']
            assert len(transcript['items']) == 1 and '1250' in transcript['items'][0]['content']
            print('PASS HTTP enrollment and replay preserve original ticket, business scope and non-zero transcript')

            resolved = request(prefix+'enrollment.bind', method='POST', data=dict(bind,
                event=ambiguous_event.name, provider_id=ambiguous_provider))
            assert resolved.status_code == 200 and resolved.json['message']['status'] == 'Projected'
            frappe.init(site='yrp.site', sites_path=SITES); frappe.connect(); frappe.set_user('Administrator')
            # A second unresolved message in the same email thread must retain
            # its own ticket if enrollment collides with an active episode.
            conflict_provider = '<sim-conflict-' + fixture.stamp.lower() + '@example.invalid>'
            conflict_event, _ = incoming(fixture, 'Email', sender, 'Private amount 2500',
                identifier=conflict_provider, raw=email_raw(conflict_provider, refs=[provider], authenticated=False))
            conflict_ticket = frappe.get_doc('Relay Ticket', {'source_hub_event':conflict_event.name})
            projection.project(conflict_event.name,
                business_overrides={conflict_provider:(fixture.customer.doctype, fixture.customer.name)})
            assert not frappe.db.exists('Relay Message', {'provider_id':conflict_provider})
            assert frappe.db.get_value('Relay Hub Event', conflict_event.name, 'projection_status') == 'Uncategorized'
            assert not frappe.db.get_value('Relay Ticket', conflict_ticket.name, 'business_name')
            assert frappe.db.get_value('Relay Message', read['messages'][0]['message'], 'ticket') == ticket_name
            # A changed company cannot promote an existing source ticket.
            frappe.db.set_value('Relay Channel', channel.name, dict(company=companies[1], triage_owner=denied))
            projection.project(missing.name, business_overrides={missing_provider:(fixture.customer.doctype, fixture.customer.name)})
            assert frappe.db.get_value('Relay Hub Event', missing.name, 'projection_status') == 'Uncategorized'
            assert not frappe.db.exists('Relay Message', {'provider_id':missing_provider})
            assert frappe.db.get_value('Relay Ticket', recovered.name, 'company') == companies[0]
            frappe.db.commit(); frappe.destroy()
            response = request(prefix+'enrollment.pending', actor=denied)
            assert response.status_code == 200 and response.json['message'] == {'items': [], 'next': None}
            assert sender not in response.get_data(as_text=True)
            # This source has no binding, so denied enrollment must leave it that way.
            refused = request(prefix+'enrollment.bind', actor=denied, method='POST', data=dict(bind,
                event=backup_event.name, provider_id=projection.extract_messages(json.loads(backup_event.payload))[0]['id']))
            assert refused.status_code == 403 and refused.json['exc_type'] == 'PermissionError'
            frappe.init(site='yrp.site', sites_path=SITES); frappe.connect(); frappe.set_user('Administrator')
            assert not frappe.db.exists('Relay Contact Endpoint', {'channel':channel.name,
                'endpoint':'sim-backup-'+fixture.stamp.lower()+'@example.invalid'})
            frappe.db.set_value('Relay Channel', channel.name, dict(company=companies[0], triage_owner=fixture.actor))
            frappe.db.commit()
            print('PASS active-episode and company-scope conflicts retain triage tickets and withhold projection')
            print('PASS HTTP reassigned channel cannot list saved-company endpoints or bind them; no endpoint mutation')
    finally:
        if not getattr(frappe.local, 'db', None):
            frappe.init(site='yrp.site', sites_path=SITES); frappe.connect()
        cleanup(fixture)
        frappe.destroy()
        print('LOCAL fixtures retained with channels disabled; no external delivery')


if __name__ == '__main__':
    main()
