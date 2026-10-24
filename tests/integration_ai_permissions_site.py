"""Local channel AI, permission and REST proof; provider calls stay intercepted."""
import json
import os
from pathlib import Path
import sys
import uuid
from unittest.mock import patch


def confine_writes(event, args, root=Path(__file__).resolve().parents[1]):
    paths = []
    if event == 'open' and isinstance(args[0], (str, bytes)) and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
        paths = [args[0]]
    elif event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.rename'}:
        paths = args[:2] if event == 'os.rename' else args[:1]
    for path in paths:
        resolved = Path(os.fsdecode(path)).resolve()
        if not (resolved.is_relative_to(root) or resolved.is_relative_to('/tmp')):
            raise PermissionError('Test refuses filesystem writes outside this worktree and /tmp')


def main():
    sys.addaudithook(confine_writes)
    os.environ['FRAPPE_STREAM_LOGGING'] = '1'
    import frappe
    import relay_core
    from channel_site_fixtures import init
    from channel_identity_fixtures import scenario, configured
    assert Path(relay_core.__file__).resolve().parents[1] == Path(__file__).resolve().parents[1]
    init()
    fixture_data = scenario()
    from frappe.api.v1 import read_doc, document_list
    try:
        frappe.set_user('Administrator')
        frappe.flags.mute_emails = True
        for dt in ('Customer', 'Relay Business Event Delivery', 'Relay Automation Run'):
            assert frappe.db.exists('DocType', dt), f'Fixture needs orchestrator-installed {dt}'
        suffix = uuid.uuid4().hex[:12]
        user = fixture_data.actor
        def fixture(doctype, name, **values):
            doc = frappe.get_doc(dict(doctype=doctype, name=name, **values))
            doc.db_insert()
            return doc
        with patch.object(frappe, 'enqueue'), patch.object(frappe.db, 'commit', side_effect=AssertionError('Test must roll back')):
            own, other = fixture_data.customer, fixture_data.supplier
            source = fixture('Relay Message', f'RELAY-MSG-AIPERM-{suffix}', content='Balance request',
                business_doctype=other.doctype, business_name=other.name, direction='Incoming')
            run = fixture('Relay Automation Run', f'RELAY-AR-AIPERM-{suffix}', event_key=f'ai-perm-run-{suffix}',
                message=source.name, execution_user=user, status='Completed',
                decision=json.dumps({'reply': 'Other business balance is 4500'}))
            event = fixture('Relay Business Event Delivery', f'RELAY-BED-AIPERM-{suffix}',
                event_key=f'ai-perm-event-{suffix}', source_doctype=other.doctype, source_name=other.name,
                business_doctype=other.doctype, business_name=other.name,
                payload=json.dumps({'amount': 4500, 'business': other.name}))
            for actor in (user, 'Administrator'):
                frappe.set_user(actor)
                if actor == user:
                    assert own.has_permission('read'), 'Fixture manager must read their own business'
                    assert not other.has_permission('read'), 'Fixture manager must be denied the other business'
                for doc, field in ((run, 'decision'), (event, 'payload')):
                    frappe.local.form_dict = frappe._dict()
                    try:
                        result = read_doc(doc.doctype, doc.name)
                    except frappe.PermissionError:
                        assert actor == user
                    else:
                        assert actor == 'Administrator' and result.get(field) == doc.get(field)
                    frappe.local.form_dict = frappe._dict(fields=json.dumps(['name', field]),
                        filters=json.dumps({'name': doc.name}))
                    try:
                        rows = document_list(doc.doctype)
                    except frappe.PermissionError:
                        assert actor == user
                    else:
                        if actor == user:
                            assert rows == []
                        else:
                            assert len(rows) == 1 and rows[0][field] == doc.get(field)
            print('PASS direct REST GET/list deny the other-business manager; administrator reads non-zero fixtures')
        frappe.db.rollback()
        with configured(fixture_data):
            channel_ai_cases(fixture_data)
    finally:
        from channel_identity_fixtures import cleanup
        cleanup(fixture_data)
        frappe.destroy()


def channel_ai_cases(fixture):
    import frappe
    from channel_identity_fixtures import endpoint
    from channel_site_fixtures import user, business, push_status
    from relay_core import whatsapp, messaging, email_preferences
    from relay_core.ai import service, adapter
    from relay_core.ai.tools import Reader
    from relay_core.automation import service as automation
    from relay_core.automation import queue
    from relay_core.automation.provenance import conversation_key
    from relay_core.message_updates import provider_key

    frappe.set_user('Administrator')
    fixture.customer.customer_details = 'Sim Order quantity 25, amount 1250'
    fixture.customer.save(); frappe.db.commit()
    contract = dict(name='customer', method='get_doc', doctype='Customer',
                    fields=['name', 'customer_details'], scope_field='name')
    partner = user('relay-c3-partner-' + fixture.stamp + '@example.invalid', manager=True)
    unrelated = business('C3 denied ' + fixture.stamp)
    restriction = frappe.get_doc(dict(doctype='User Permission', user=partner, allow='Customer',
        for_value=fixture.customer.name, apply_to_all_doctypes=1)).insert()
    frappe.db.commit()
    account=frappe.get_doc(dict(doctype='AI Provider Account',name='Local skill account '+fixture.stamp,
        account_label='Local skill account '+fixture.stamp,provider='OpenRouter',enabled=1));account.db_insert()
    model_record=frappe.get_doc(dict(doctype='AI Model',name='Local skill model '+fixture.stamp,model_label='Local skill model '+fixture.stamp,
        account=account.name,provider='OpenRouter',model_id='local-no-network',enabled=1));model_record.db_insert()
    provider_counter = 700
    context = {}
    def model(skill, user, business, prompt, run_id):
        reader = Reader(skill, user, business)
        rows = reader.read(contract, name=fixture.customer.name)
        assert '1250' in str(rows)
        return dict(reply='Order quantity 25, amount 1250', handoff=False, reason='', user=user, reads=reader.evidence)

    for provider, address in [('Telegram', '-9555000418'), ('Email', 'ai-' + fixture.stamp.lower() + '@example.invalid')]:
        binding = endpoint(fixture, provider, address)
        skill = frappe.get_doc(dict(doctype='Relay AI Skill', name='LOCAL-C3-AI-' + provider + '-' + fixture.stamp,
            title='Sim ' + provider + ' Skill ' + fixture.stamp, enabled=1, ai_model=model_record.name, channel=binding.channel, business_doctype='Customer',
            run_as_user=fixture.actor, handoff_owner=fixture.actor, mode='Automatic', daily_limit=100,
            instructions='Read this customer only. Hand off anything outside the skill.', allowed_tools=json.dumps([contract])))
        # No model account or credentials: the external AI boundary is replaced below.
        skill.db_insert(); frappe.db.commit()
        frappe.conf.relay_automation_enabled = 1
        def source(body='Please confirm quantity and amount', *, topic=7, automatic=False):
            nonlocal provider_counter, context
            provider_counter += 1
            identifier = str(provider_counter) if provider == 'Telegram' else '<ai-' + str(provider_counter) + '-' + fixture.stamp + '@example.invalid>'
            context = dict(provider=provider)
            if provider == 'Telegram':
                context.update(chat_id=int(address), chat_type='supergroup', message_id=provider_counter, message_thread_id=topic)
            else:
                context.update(message_id=identifier, email_thread_id='<thread-' + fixture.stamp + '@example.invalid>',
                    subject='Sim Order 25', references=['<thread-' + fixture.stamp + '@example.invalid>'],
                    authentication={'status':'pass'}, auto_submitted=automatic)
            doc = frappe.get_doc(dict(doctype='Relay Message', relay_contact=fixture.contact.name, channel=binding.channel,
                sender_endpoint=address, direction='Incoming', content=body, message_type='text', status='Sent',
                business_doctype='Customer', business_name=fixture.customer.name, provider_id=identifier,
                provider_message_key=provider_key(binding.channel,address,identifier), provider_context=json.dumps(context),
                conversation_key=conversation_key(binding.channel,address,context))).insert()
            frappe.db.commit()
            return doc

        def run(doc):
            queue._process(doc.name); frappe.db.commit()
            name = frappe.db.get_value('Relay Automation Run', {'message':doc.name}, 'name')
            assert name, 'The durable hook must admit this channel skill'
            automation.process(name)
            return frappe.get_doc('Relay Automation Run', name)

        with patch.object(adapter, 'complete', side_effect=model), patch.object(whatsapp, 'client') as client:
            client.return_value.call_tool.return_value = {'message_id':901 if provider == 'Telegram' else '<reply-' + fixture.stamp + '@example.invalid>'}
            message = source()
            result = run(message)
            assert result.status == 'Completed', (provider,result.status,result.reason)
            action = frappe.get_doc('Relay Message Action', {'source_message':message.name})
            assert action.status == 'Submitted'
            payload = json.loads(action.payload)
            assert payload['automation_run'] == result.name
            args = client.return_value.call_tool.call_args.args[1]
            if provider == 'Telegram':
                assert args['chat_id'] == int(address) and args['message_thread_id'] == 7
                assert '1250' in args['text']
            else:
                assert args['subject'] == 'Re: Sim Order 25'
                assert args['in_reply_to'] == context['message_id'] and args['references'][-1] == context['message_id']
                assert args['auto_submitted'] is True and args['cc'] == [] and args['bcc'] == []
                outgoing = frappe.get_doc('Relay Message',action.outbound_message)
                assert json.loads(outgoing.provider_context)['email_thread_id'] == context['email_thread_id']
                # An enabled fixed rule cannot compete with this business's skill.
                fixed = frappe.get_doc(dict(doctype='Relay Email Rule', name='LOCAL-C3-FIXED-' + fixture.stamp,
                    channel=binding.channel, enabled=1, execution_user=fixture.actor, subject='Fixed', body='Wrong competing reply'))
                fixed.db_insert(); frappe.db.commit()
                calls = client.return_value.call_tool.call_count
                email_preferences.auto_reply(message.name)
                assert client.return_value.call_tool.call_count == calls
                suppressed = source(automatic=True)
                queue._process(suppressed.name); frappe.db.commit()
                assert not frappe.db.exists('Relay Automation Run', {'message':suppressed.name})
                # A fixed reply admitted before a skill is enabled owns this source forever.
                frappe.db.set_value('Relay AI Skill',skill.name,'enabled',0); frappe.db.commit()
                fixed_source = source()
                queue._process(fixed_source.name); frappe.db.commit()
                client.return_value.call_tool.return_value = {'message_id':'<fixed-' + fixture.stamp + '@example.invalid>'}
                assert email_preferences.auto_reply(fixed_source.name)['status'] == 'Submitted'
                assert frappe.db.exists('Relay Message Action', {'source_message':fixed_source.name})
                frappe.db.set_value('Relay AI Skill',skill.name,'enabled',1); frappe.db.commit()
                queue._process(fixed_source.name); frappe.db.commit()
                assert not frappe.db.exists('Relay Automation Run', {'message':fixed_source.name})
                assert frappe.db.count('Relay Message Action', {'source_message':fixed_source.name}) == 1
                frappe.db.set_value('Relay Email Rule',fixed.name,'enabled',0); frappe.db.commit()
            calls = client.return_value.call_tool.call_count
            automation.process(result.name)
            assert client.return_value.call_tool.call_count == calls

            # The action callback and missed-callback recovery both hand off once.
            for recovery in (False, True):
                message = source()
                client.return_value.call_tool.return_value = {'pending':True, 'state':'queued'}
                pending = run(message)
                assert pending.status == 'Delivering' and not pending.ticket
                action = frappe.get_doc('Relay Message Action', {'source_message':message.name})
                calls = client.return_value.call_tool.call_count
                frappe.enqueue.reset_mock()
                push_status(fixture.account, [{'id':int(__import__('time').time_ns() // 1000),
                    'delivery_id':501, 'request_key':action.request_key,
                    'operation':'telegram.message' if provider == 'Telegram' else 'email.send',
                    'state':'rejected', 'receipt':{}, 'occurred_at':'2026-10-24T10:00:00Z'}])
                assert any(c.args == ('relay_core.ai.service.complete_delivery',) and
                    c.kwargs.get('action') == action.name and c.kwargs.get('enqueue_after_commit')
                    for c in frappe.enqueue.call_args_list)
                if recovery:
                    # Repair runs completed by the previous implementation too.
                    frappe.db.set_value('Relay Automation Run', pending.name, 'status', 'Completed')
                    frappe.db.commit(); frappe.enqueue.reset_mock()
                    with patch('relay_core.ai.handoff.eligible', return_value=False):
                        service.complete_delivery(action.name)
                    pending.reload()
                    assert not pending.ticket and 'owner unavailable' in pending.reason
                    assert frappe.db.get_value('Relay Contact',fixture.contact.name,'automation_paused')
                    service.recover_deliveries()
                    assert any(c.kwargs.get('action') == action.name for c in frappe.enqueue.call_args_list)
                for _ in range(2):
                    service.complete_delivery(action.name)
                pending.reload()
                assert pending.status == 'Handoff' and pending.ticket
                assert frappe.db.count('Relay Ticket', {'source_run':pending.name}) == 1
                ticket = frappe.get_doc('Relay Ticket',pending.ticket)
                assert ticket.assigned_to == fixture.actor and ticket.business_name == fixture.customer.name
                with service.as_user(fixture.actor):
                    try: messaging.retry(action.name)
                    except frappe.PermissionError: frappe.db.rollback()
                    else: raise AssertionError('Automated retry lost provenance')
                assert client.return_value.call_tool.call_count == calls
                automation.takeover(fixture.contact.name, paused=0); frappe.db.commit()
            print('PASS',provider,'queued rejection callback/recovery creates exactly one assigned handoff')

            message = source()
            pending = run(message)
            action = frappe.get_doc('Relay Message Action', {'source_message':message.name})
            assert pending.status == 'Delivering'
            push_status(fixture.account, [{'id':int(__import__('time').time_ns() // 1000),
                'delivery_id':502, 'request_key':action.request_key,
                'operation':'telegram.message' if provider == 'Telegram' else 'email.send',
                'state':'submitted', 'receipt':{'message_id':905 if provider == 'Telegram' else '<accepted-' + fixture.stamp + '@example.invalid>'},
                'occurred_at':'2026-10-24T10:00:00Z'}])
            service.complete_delivery(action.name)
            pending.reload()
            assert pending.status == 'Completed' and not pending.ticket

            # A death after journaling recovers the same intent and provider key.
            message = source()
            client.return_value.call_tool.side_effect = SystemExit('Local pre-admission crash')
            try:
                run(message)
            except SystemExit:
                pass
            crashed = frappe.get_doc('Relay Automation Run', {'message':message.name})
            action = frappe.get_doc('Relay Message Action', {'source_message':message.name})
            assert action.status == 'Dispatching'
            client.return_value.call_tool.side_effect = [{'deliveries':[]}, {'message_id':902 if provider == 'Telegram' else '<recovery-' + fixture.stamp + '@example.invalid>'}]
            automation.process(crashed.name)
            assert frappe.db.get_value('Relay Automation Run',crashed.name,'status') == 'Completed'
            assert client.return_value.call_tool.call_args.args[1]['request_key'] == action.request_key
            client.return_value.call_tool.side_effect = None
            calls = client.return_value.call_tool.call_count

            # Revoke the linked user's actual business permission after inference.
            fixture.person.user = partner; fixture.person.save(); frappe.db.commit()
            message = source()
            def revoked(skill, user, business, prompt, run_id):
                decision = model(skill,user,business,prompt,run_id)
                actor = frappe.session.user
                try:
                    frappe.set_user('Administrator')
                    restriction.for_value = unrelated.name; restriction.save(); frappe.db.commit()
                    frappe.clear_cache(user=partner)
                finally:
                    frappe.set_user(actor)
                assert not fixture.customer.has_permission('read',user=partner)
                return decision
            with patch.object(adapter,'complete',side_effect=revoked):
                failed = run(message)
            assert failed.status == 'Handoff' and failed.ticket
            ticket = frappe.get_doc('Relay Ticket',failed.ticket)
            assert ticket.assigned_to == fixture.actor and ticket.business_name == fixture.customer.name
            automation.process(failed.name)
            assert frappe.db.count('Relay Ticket', {'source_action_key':ticket.source_action_key}) == 1
            assert client.return_value.call_tool.call_count == calls
            automation.takeover(fixture.contact.name, paused=0); frappe.db.commit()
            fixture.person.user = None; fixture.person.save()
            restriction.for_value = fixture.customer.name; restriction.save(); frappe.db.commit()
            frappe.clear_cache(user=partner)

            message = source()
            queue._process(message.name); frappe.db.commit()
            pending = frappe.db.get_value('Relay Automation Run', {'message':message.name},'name')
            automation.takeover(fixture.contact.name, paused=1); frappe.db.commit()
            automation.process(pending)
            assert frappe.db.get_value('Relay Automation Run',pending,'status') == 'Cancelled'
            assert client.return_value.call_tool.call_count == calls
            automation.takeover(fixture.contact.name, paused=0); frappe.db.commit()

            message = source()
            def taken_over(skill,user,business,prompt,run_id):
                decision = model(skill,user,business,prompt,run_id)
                automation.takeover(fixture.contact.name,paused=1); frappe.db.commit()
                return decision
            with patch.object(adapter,'complete',side_effect=taken_over):
                cancelled = run(message)
            assert cancelled.status == 'Cancelled'
            assert client.return_value.call_tool.call_count == calls
            automation.takeover(fixture.contact.name,paused=0); frappe.db.commit()

            # Explicit human requests bypass the model and create one assigned ticket.
            fixture.person.user = fixture.actor; fixture.person.save(); frappe.db.commit()
            with patch.object(adapter, 'complete', side_effect=AssertionError('Human request must bypass the model')):
                message = source('Talk to a human')
                human = run(message)
            assert human.status == 'Handoff'
            assert frappe.db.get_value('Relay Ticket',human.ticket,'business_name') == fixture.customer.name
            assert client.return_value.call_tool.call_count == calls
            automation.takeover(fixture.contact.name, paused=0); frappe.db.commit()
            fixture.person.user = None; fixture.person.save(); frappe.db.commit()
        frappe.db.set_value('Relay AI Skill',skill.name,'enabled',0); frappe.db.commit()
        print('PASS',provider,'AI scoped reads, durable reply, replay, one assigned handoff and takeover')
    frappe.conf.relay_automation_enabled = 0


if __name__ == '__main__':
    main()
