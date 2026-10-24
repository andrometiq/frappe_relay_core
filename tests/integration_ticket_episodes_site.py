"""Local episode concurrency, recovery and real HTTP permission checks on yrp.site."""
import json
import os
from pathlib import Path
import secrets
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from urllib.parse import quote

from integration_ai_permissions_site import confine_writes

SITES = '/home/sakthi/development/pilot/benches/version_16/sites'
ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.addaudithook(confine_writes)
    os.environ['FRAPPE_STREAM_LOGGING'] = '1'
    os.environ['RELAY_AUTOMATION_TEST_SITES'] = SITES
    os.environ['RELAY_TEST_SITE'] = 'yrp.site'
    os.environ['SITES_PATH'] = SITES
    import frappe
    import frappe.app
    import relay_core
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    from channel_site_fixtures import init, user
    from channel_identity_fixtures import scenario, cleanup
    from relay_core import tickets
    from relay_core.automation.provenance import conversation_key

    assert Path(relay_core.__file__).resolve().parents[1] == ROOT
    init()
    assert frappe.local.site == 'yrp.site'
    for name in ('relay_ticket', 'relay_message', 'relay_automation_run'):
        frappe.reload_doc('relay_core', 'doctype', name, force=True)
    frappe.db.commit()
    print('RELOADED Relay Ticket, Relay Message, Relay Automation Run from worktree JSON')
    fixture = scenario()
    try:
        company_names = []
        for title in ('Episode North', 'Episode South'):
            name = 'Sim ' + title + ' ' + fixture.stamp
            frappe.get_doc(dict(doctype='Company', name=name, company_name=name, abbr='SE',
                country='India', default_currency='INR')).db_insert()
            company_names.append(name)
        channel = fixture.channels['Email']
        frappe.db.set_value('Relay Channel', channel.name, 'company', company_names[0])
        frappe.get_doc(dict(doctype='User Permission', user=fixture.actor, allow='Company',
            for_value=company_names[0], apply_to_all_doctypes=1)).insert()
        denied_user = user('sim-episode-denied-' + fixture.stamp.lower() + '@example.invalid', manager=True)
        frappe.get_doc(dict(doctype='User Permission', user=denied_user, allow='Company',
            for_value=company_names[1], apply_to_all_doctypes=1)).insert()
        disabled_user = user('sim-episode-disabled-' + fixture.stamp.lower() + '@example.invalid', manager=True)
        frappe.db.set_value('User', disabled_user, 'enabled', 0)
        auth = {}
        for actor in (fixture.actor, denied_user):
            doc = frappe.get_doc('User', actor)
            doc.api_key, doc.api_secret = secrets.token_hex(12), secrets.token_hex(24)
            auth[actor] = 'token ' + doc.api_key + ':' + doc.api_secret
            doc.save()
        endpoint = 'sim-episode-' + fixture.stamp.lower() + '@example.invalid'
        frappe.get_doc(dict(doctype='Relay Contact Endpoint', channel=channel.name,
            relay_contact=fixture.contact.name, endpoint=endpoint, verified=1)).insert()
        context = dict(provider='Email', email_thread_id='<sim-episode@example.invalid>', authentication={'status':'pass'})
        conversation = conversation_key(channel.name, endpoint, context)
        def message(title, *, thread=conversation, business=None):
            doc = frappe.get_doc(dict(doctype='Relay Message', relay_contact=fixture.contact.name,
                channel=channel.name, direction='Incoming', status='Sent', content='Sim '+title+' quantity 25, amount 1250',
                sender_endpoint=endpoint, conversation_key=thread, provider_context=context,
                business_doctype=(business or fixture.customer).doctype, business_name=(business or fixture.customer).name,
                source_key='Sim '+title+' '+fixture.stamp)).insert()
            return doc
        sources = [message('Episode first'), message('Episode second')]
        frappe.db.commit()
        barrier = Barrier(2)
        def admit(name):
            frappe.init(site='yrp.site', sites_path=SITES)
            frappe.connect(); frappe.set_user('Administrator'); frappe.flags.mute_emails = True
            try:
                doc = frappe.get_doc('Relay Message', name)
                barrier.wait(timeout=10)
                for attempt in range(3):
                    try:
                        result = tickets.ensure_episode(doc, owner=fixture.actor)
                        frappe.db.commit()
                        return result.name
                    except frappe.QueryDeadlockError:
                        frappe.db.rollback()
                        if attempt == 2: raise
                        doc = frappe.get_doc('Relay Message', name)
            finally:
                frappe.destroy()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(admit, source.name) for source in sources]
            names = [future.result(timeout=30) for future in futures]
        assert names[0] == names[1]
        frappe.db.rollback()
        ticket = frappe.get_doc('Relay Ticket', names[0])
        assert ticket.assigned_to == fixture.actor and len(ticket.messages) == 1
        assert frappe.db.count('Relay Ticket', {'active_scope_key':ticket.active_scope_key}) == 1
        assert frappe.db.count('Relay Message', {'ticket':ticket.name}) == 2
        print('PASS concurrent first admission: one assigned episode, two source links, one evidence row')

        # Failed assignment leaves neither an episode nor a message link; retry succeeds.
        failed = message('Unavailable owner', thread='Sim unavailable '+fixture.stamp)
        frappe.db.commit()
        for owner in (disabled_user, denied_user):
            try: tickets.ensure_episode(failed, owner=owner)
            except ValueError: pass
            else: raise AssertionError('Ineligible owner accepted')
            assert not frappe.db.get_value('Relay Message', failed.name, 'ticket')
            assert not frappe.db.exists('Relay Ticket', {'conversation_key':failed.conversation_key})
        recovered = tickets.ensure_episode(failed, owner=fixture.actor)
        assert recovered.assigned_to == fixture.actor
        print('PASS disabled and wrong-company assignment fail atomically; same source remains recoverable')

        # Every message belongs to the transcript; selected evidence remains bounded.
        for index in range(59):
            doc = message('Transcript '+str(index+1))
            assert tickets.ensure_episode(doc, owner=fixture.actor).name == ticket.name
        assert frappe.db.count('Relay Message', {'ticket':ticket.name}) == 61
        ticket.reload()
        assert len(ticket.messages) == 1
        key = ticket.source_action_key
        # Step 9 owns the takeover API; model its persisted transition directly.
        frappe.db.set_value('Relay Ticket', ticket.name, dict(status='Closed', ai_disabled=1, generation=7))
        replay = tickets.ensure_episode(sources[0], owner=fixture.actor)
        assert (replay.name, replay.status, replay.source_action_key) == (ticket.name, 'Closed', key)
        new = message('Reopen held episode')
        reopened = tickets.ensure_episode(new, owner=fixture.actor)
        assert (reopened.name, reopened.status, reopened.ai_disabled, reopened.generation) == (ticket.name, 'Open', 1, 7)
        # Step 9 owns the release API. Model that stored transition here to prove replay.
        frappe.db.set_value('Relay Ticket', ticket.name, {'status':'Closed', 'active_scope_key':None})
        released_source = message('After release')
        fresh = tickets.ensure_episode(released_source, owner=fixture.actor)
        assert fresh.name != ticket.name and fresh.source_action_key != key
        assert tickets.ensure_episode(sources[0], owner=fixture.actor).name == ticket.name
        assert frappe.db.get_value('Relay Ticket', ticket.name, 'status') == 'Closed'
        frappe.db.commit()
        print('PASS 61-message transcript, closure replay, new inbound reopens human hold, release creates a fresh episode')

        # Exercise handoff through the same service, with no model/provider calls.
        from relay_core.ai.handoff import handoff
        from relay_core.automation.service import internal_save
        source = message('Handoff source', thread='Sim handoff '+fixture.stamp)
        run = frappe.get_doc(dict(doctype='Relay Automation Run', event_key='Sim episode run '+fixture.stamp,
            message=source.name, execution_user=fixture.actor, status='Pending'))
        internal_save(run, new=True)
        skill = frappe._dict(name=None, modified='Sim version', handoff_owner=fixture.actor)
        existing = tickets.ensure_episode(source, owner=fixture.actor, run=run)
        assert handoff(run, skill, 'Sim staff review of amount 1250') == existing.name
        assert handoff(run, skill, 'Sim staff review retry') == existing.name
        assert frappe.db.count('Relay Ticket', {'conversation_key':source.conversation_key}) == 1
        frappe.db.commit()
        # An existing handoff from before this schema retains its original key.
        legacy_source = message('Legacy handoff', thread='Sim legacy '+fixture.stamp)
        legacy = frappe.get_doc(dict(doctype='Relay Ticket', subject='Sim Legacy episode '+fixture.stamp,
            category='Support', status='Closed', assigned_to=fixture.actor,
            business_doctype='Customer', business_name=fixture.customer.name,
            source_action_key='Sim Legacy key '+fixture.stamp, messages=[{'message':legacy_source.name}])).insert()
        legacy_run = frappe.get_doc(dict(doctype='Relay Automation Run', event_key='Sim legacy run '+fixture.stamp,
            message=legacy_source.name, execution_user=fixture.actor, status='Handoff', ticket=legacy.name))
        internal_save(legacy_run, new=True)
        recovered_legacy = tickets.ensure_episode(legacy_source, owner=fixture.actor, run=legacy_run)
        assert (recovered_legacy.name, recovered_legacy.status, recovered_legacy.source_action_key) == (
            legacy.name, 'Closed', legacy.source_action_key)
        assert recovered_legacy.company == company_names[0] and recovered_legacy.active_scope_key
        from channel_site_fixtures import check_business_lifecycle
        check_business_lifecycle(fixture.customer)
        frappe.db.commit()
        print('PASS AI handoff shares episodes, legacy recovery retains keys, business lifecycle has no Relay blockers')

        # Real Frappe HTTP dispatch/auth, query hooks and resource permissions.
        ticket_name, other_message = ticket.name, released_source.name
        frappe.destroy()
        client = Client(frappe.app.application, Response)
        def request(path, *, actor=fixture.actor, method='GET', data=None):
            headers = {'Authorization': auth[actor]} if actor else {}
            return client.open(path, method=method, data=data, headers=headers, base_url='http://yrp.site')
        prefix = '/api/method/relay_core.tickets.'
        with patch.object(frappe, 'enqueue'):
            response = request(prefix+'transcript?name='+ticket_name)
            assert response.status_code == 200, ('transcript status', response.status_code)
            result = response.json['message']
            assert set(result) == {'items', 'next'} and len(result['items']) == 50
            assert set(result['items'][0]) == {'name','content','direction','status','creation','sent_at','message_type','channel'}
            assert '1250' in result['items'][0]['content']
            response = request(prefix+'transcript?name='+ticket_name+'&after='+result['next']['after'])
            assert response.status_code == 200 and len(response.json['message']['items']) == 12
            assert response.json['message']['next'] is None
            for path in (prefix+'read?name='+ticket_name, '/api/resource/Relay Ticket/'+ticket_name):
                allowed = request(path)
                assert allowed.status_code == 200
                for actor in (denied_user, None):
                    denied = request(path, actor=actor)
                    assert denied.status_code in (401, 403), ('ticket deny', denied.status_code)
            for actor in (denied_user, None):
                denied = request(prefix+'transcript?name='+ticket_name, actor=actor)
                assert denied.status_code in (401, 403) and denied.json['exc_type'] == 'PermissionError'
            denied = request(prefix+'transcript', method='POST', data={'name':ticket_name})
            assert denied.status_code == 403
            denied = request(prefix+'ensure_episode', method='POST', data={})
            assert denied.status_code == 403
            denied = request(prefix+'transcript?name='+ticket_name+'&after='+other_message)
            assert denied.status_code == 403
            invalid = request(prefix+'transcript?name='+ticket_name+'&limit=101')
            assert invalid.status_code == 417
            # Permission query conditions must agree with direct document checks.
            path = '/api/resource/Relay Ticket?filters='+quote(json.dumps({'name':ticket_name}))
            assert len(request(path).json['data']) == 1
            denied = request(path, actor=denied_user)
            assert denied.status_code == 200 and denied.json['data'] == []
            result = request(prefix+'update_status', method='POST', data={'name':ticket_name,'status':'Open'})
            assert result.status_code == 200 and result.json['message'] == {'name':ticket_name,'status':'Open'}
            denied = request(prefix+'update_status', method='POST', actor=denied_user,
                data={'name':ticket_name,'status':'Closed'})
            assert denied.status_code == 403
            assigned = request(prefix+'assign', method='POST', data={'name':ticket_name,'user':fixture.actor})
            assert assigned.status_code == 200 and assigned.json['message']['assigned_to'] == fixture.actor
            denied = request(prefix+'assign', method='POST', data={'name':ticket_name,'user':denied_user})
            assert denied.status_code == 403
            assert request(prefix+'read?name='+ticket_name).json['message']['assigned_to'] == fixture.actor
            resource = '/api/resource/Relay Ticket/' + fresh.name
            baseline = request(resource).json['data']
            for changes in ({'company': ''}, {'conversation_key': ''}, {'active_scope_key': ''},
                    {'company': '', 'conversation_key': '', 'active_scope_key': ''},
                    {'source_action_key': ''}, {'source_provider_message_key': 'Forged source'},
                    {'business_name': ''}, {'skill_version': 'Forged version'},
                    {'generation': 10}, {'ai_disabled': 1}, {'pending_run': run.name},
                    {'source_run': run.name}, {'source_hub_event': ''}):
                if all(baseline.get(key) in ('', None) and value == '' for key, value in changes.items()):
                    continue
                denied = request(resource, method='PUT', data=changes)
                assert denied.status_code == 403 and denied.json['exc_type'] == 'PermissionError', (changes, denied.status_code)
            current = request(resource).json['data']
            assert all(current.get(key) == baseline.get(key) for key in baseline if key != 'modified')
            edited = request(resource, method='PUT', data={'brief': 'Sim staff review of amount 1250'})
            assert edited.status_code == 200 and edited.json['data']['brief'] == 'Sim staff review of amount 1250'

            # An explicit staff assignment survives closed-source replay with the old auto-owner.
            frappe.init(site='yrp.site', sites_path=SITES); frappe.connect(); frappe.set_user('Administrator')
            staff = user('sim-episode-assignee-' + fixture.stamp.lower() + '@example.invalid', manager=True)
            frappe.db.commit(); frappe.destroy()
            assigned = request(prefix+'assign', method='POST', data={'name':fresh.name, 'user':staff})
            assert assigned.status_code == 200 and assigned.json['message']['assigned_to'] == staff
            closed = request(prefix+'update_status', method='POST', data={'name':fresh.name, 'status':'Closed'})
            assert closed.status_code == 200 and closed.json['message']['status'] == 'Closed'
            frappe.init(site='yrp.site', sites_path=SITES); frappe.connect(); frappe.set_user('Administrator')
            replay = tickets.ensure_episode(released_source, owner=fixture.actor)
            assert (replay.assigned_to, replay.status) == (staff, 'Closed')
            frappe.db.commit(); frappe.destroy()
            result = request(prefix+'read?name='+fresh.name)
            assert result.status_code == 200 and result.json['message']['assigned_to'] == staff
        print('PASS HTTP episode scope/coordination mutation denial, ordinary edits, authorized assignment and closed replay preservation')
        print('PASS HTTP transcript/read/status and direct REST: status, shape, pagination, company/guest denial, method/cursor/limit rejection')
    finally:
        if not getattr(frappe.local, 'db', None):
            frappe.init(site='yrp.site', sites_path=SITES); frappe.connect()
        cleanup(fixture)
        frappe.destroy()
        print('LOCAL fixtures retained with their channels disabled; no external delivery')


if __name__ == '__main__':
    main()
