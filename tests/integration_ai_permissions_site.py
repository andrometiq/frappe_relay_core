"""Local channel AI, permission and REST proof; provider calls stay intercepted."""
import json
import os
from pathlib import Path
import sys
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
        suffix = fixture_data.stamp
        user = fixture_data.actor
        def fixture(doctype, name, **values):
            doc = frappe.get_doc(dict(doctype=doctype, name=name, **values))
            doc.db_insert()
            return doc
        with patch.object(frappe, 'enqueue'), patch.object(frappe.db, 'commit', side_effect=AssertionError('Test must roll back')):
            own, other = fixture_data.customer, fixture_data.supplier
            source = fixture('Relay Message', f'Sim Permission Message {suffix}', content='Balance request',
                business_doctype=other.doctype, business_name=other.name, direction='Incoming')
            run = fixture('Relay Automation Run', f'Sim Permission Run {suffix}', event_key=f'ai-perm-run-{suffix}',
                message=source.name, execution_user=user, status='Completed',
                decision=json.dumps({'reply': 'Other business balance is 4500'}))
            event = fixture('Relay Business Event Delivery', f'Sim Permission Event {suffix}',
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
            sender_scope_cases(fixture_data)
            channel_ai_cases(fixture_data)
    finally:
        from channel_identity_fixtures import cleanup
        cleanup(fixture_data)
        frappe.destroy()


def sender_scope_cases(fixture):
    """Real company/identity reads through preview HTTP, with no provider network."""
    import secrets
    import frappe
    import frappe.app
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    from channel_identity_fixtures import endpoint
    from relay_core.ai import service, adapter
    from relay_core.ai.tools import Reader, recheck, fingerprint
    from relay_core.automation.provenance import conversation_key
    from frappe_tools.ai import tools as shared_tools

    created = []
    stamp = fixture.stamp
    sites = '/home/sakthi/development/pilot/benches/version_16/sites'
    os.environ['SITES_PATH'] = sites
    def connect():
        frappe.init(site='yrp.site', sites_path=sites)
        frappe.connect(); frappe.set_user('Administrator')
        frappe.flags.mute_emails = True
        frappe.conf.relay_automation_enabled = 0
    def insert(doctype, label, **values):
        # Isolated local records bypass unrelated ERP accounting lifecycle hooks.
        doc = frappe.get_doc(dict(doctype=doctype, name='Sim ' + label + ' ' + stamp, **values))
        doc.db_insert(); created.append((doctype, doc.name))
        return doc
    def denied(call):
        try: call()
        except (ValueError, frappe.PermissionError): return
        raise AssertionError('Out-of-scope read succeeded')
    try:
        frappe.set_user('Administrator')
        with patch('frappe.core.doctype.user.user.throttle_user_creation'):
            actor = frappe.get_doc(dict(doctype='User', email='sim-scope-reader-' + stamp.lower() + '@example.invalid',
                first_name='Sim Scope Reader ' + stamp, send_welcome_email=0,
                roles=[{'role': role} for role in ('System Manager', 'Accounts Manager', 'Purchase Manager', 'Sales Manager')])).insert()
        created.append(('User', actor.name))
        actor.api_key, actor.api_secret = secrets.token_hex(12), secrets.token_hex(24)
        authorization = 'token ' + actor.api_key + ':' + actor.api_secret
        actor.save()
        denied_actor = frappe.get_doc('User', fixture.actor)
        denied_actor.api_key, denied_actor.api_secret = secrets.token_hex(12), secrets.token_hex(24)
        denied_authorization = 'token ' + denied_actor.api_key + ':' + denied_actor.api_secret
        denied_actor.save()
        companies = [insert('Company', label, company_name='Sim ' + label + ' ' + stamp,
            abbr=abbr, default_currency='INR', country='India') for label, abbr in [('Scope North', 'SN'), ('Scope South', 'SS')]]
        address = 'sim-scope-sender-' + stamp.lower() + '@example.invalid'
        supplier = insert('Supplier', 'Shared Party', supplier_name='Sim Shared Party ' + stamp, alias=address, supplier_type='Company')
        customer = insert('Customer', 'Shared Party', customer_name='Sim Shared Party ' + stamp, alias=address, customer_type='Company')
        assert supplier.name == customer.name
        fixture.person.append('links', dict(link_doctype='Supplier', link_name=supplier.name))
        fixture.person.append('links', dict(link_doctype='Customer', link_name=customer.name))
        fixture.person.save()
        binding = endpoint(fixture, 'Email', address)
        created.append(('Relay Contact Endpoint', binding.name))
        frappe.db.set_value('Relay Channel', binding.channel, 'company', companies[0].name)
        contract = dict(name='ledger', method='get_list', doctype='GL Entry', scope_field='party',
            fields=['name', 'company', 'posting_date', 'debit', 'credit'], identity_anchor='Supplier',
            identity_fields={'Email': 'alias'}, company_field='company')
        rows = []
        for label, company, party_type, debit in [('Own Entry', companies[0], 'Supplier', 1250),
                ('Other Company Entry', companies[1], 'Supplier', 7500), ('Customer Collision', companies[0], 'Customer', 4500)]:
            rows.append(insert('GL Entry', label, company=company.name, party_type=party_type, party=supplier.name,
                posting_date='2026-10-01', debit=debit, credit=0, is_cancelled=0))
        skill = insert('Relay AI Skill', 'Scope Event', enabled=1, title='Sim Scope Event ' + stamp,
            channel=binding.channel, business_doctype='Supplier', run_as_user=actor.name, daily_limit=100,
            allowed_tools=json.dumps([contract]), mode='Shadow', instructions='Read only my confirmed ledger.')
        provenance = dict(provider='Email', message_id='<sim-scope-' + stamp.lower() + '@example.invalid>',
            authentication={'status': 'pass'}, email_thread_id='<sim-scope-thread@example.invalid>')
        message = insert('Relay Message', 'Scope Message', relay_contact=fixture.contact.name, channel=binding.channel,
            sender_endpoint=address, direction='Incoming', message_type='text', content='My confirmed ledger for October',
            business_doctype='Supplier', business_name=supplier.name, provider_context=json.dumps(provenance),
            conversation_key=conversation_key(binding.channel, address, provenance))
        user, business, scope = service.context(skill, message)
        fixture.person.user = fixture.actor; fixture.person.save()
        denied(lambda: service.context(skill, message))
        fixture.person.user = None; fixture.person.save()
        reader = Reader(skill, user, business, scope)
        result = reader.read(contract, limit=1)
        assert result['totals']['debit'] == '1250.0' or result['totals']['debit'] == '1250'
        assert [row['name'] for row in result['rows']] == [rows[0].name] and not result['truncated']
        assert set(result['rows'][0]) == set(contract['fields'])
        recheck(skill, user, business, reader.evidence, scope)
        one = contract | {'method': 'get_doc'}
        skill.allowed_tools = json.dumps([one])
        for row in rows[1:]: denied(lambda: Reader(skill, user, business, scope).read(one, name=row.name))
        assert Reader(skill, user, business, scope).read(one, name=rows[0].name)['debit'] == 1250
        skill.allowed_tools = json.dumps([contract])
        denied(lambda: reader.read(contract, filters={'company': companies[1].name}))
        for dt, name, field, value, original in [
                ('Relay Contact Endpoint', binding.name, 'verified', 0, 1),
                ('Supplier', supplier.name, 'alias', 'different@example.invalid', address),
                ('Relay Channel', binding.channel, 'company', companies[1].name, companies[0].name),
                ('User', actor.name, 'enabled', 0, 1)]:
            frappe.db.set_value(dt, name, field, value)
            denied(lambda: recheck(skill, user, business, reader.evidence, scope))
            frappe.db.set_value(dt, name, field, original)
        frappe.db.set_value('GL Entry', rows[0].name, 'debit', 2500)
        denied(lambda: recheck(skill, user, business, reader.evidence, scope))
        frappe.db.set_value('GL Entry', rows[0].name, 'debit', 1250)

        # Run real Frappe query permission processing with an installed-hook result.
        original_hooks, original_attr = frappe.get_hooks, frappe.get_attr
        hook_name = 'relay_core.tests.sim_scope_query'
        def hooks(name=None, *args, **kwargs):
            value = original_hooks(name, *args, **kwargs)
            if name == 'permission_query_conditions':
                value = dict(value); value['GL Entry'] = [hook_name]
            return value
        with patch.object(frappe, 'get_hooks', side_effect=hooks), patch.object(frappe, 'get_attr',
                side_effect=lambda name: (lambda *args, **kw: '1=0') if name == hook_name else original_attr(name)):
            denied(lambda: reader.read(contract))
            skill.allowed_tools = json.dumps([one])
            denied(lambda: Reader(skill, user, business, scope).read(one, name=rows[0].name))
        def company_hooks(name=None, *args, **kwargs):
            value = original_hooks(name, *args, **kwargs)
            if name == 'permission_query_conditions':
                value = dict(value); value['Company'] = [hook_name]
            return value
        with patch.object(frappe, 'get_hooks', side_effect=company_hooks), patch.object(frappe, 'get_attr',
                side_effect=lambda name: (lambda *args, **kw: '1=0') if name == hook_name else original_attr(name)):
            from relay_core.ai.tools import as_user
            with as_user(user):
                assert frappe.get_doc('Company', companies[0].name).has_permission('read')
            denied(lambda: service.context(skill, message))
        skill.allowed_tools = json.dumps([contract])
        original_columns = shared_tools.get_readable_columns
        with patch.object(shared_tools, 'get_readable_columns', side_effect=lambda meta: original_columns(meta) - {'debit'}):
            denied(lambda: reader.read(contract))
        # Private destination and participant must agree; typed text never repairs evidence.
        telegram = fixture.channels['Telegram']
        telegram.company = companies[0].name
        for chat_type, chat_id, participant in [('supergroup', -9555000418, 9555000418), ('private', 9555000418, 9555000419)]:
            from relay_core.identity import authenticated_sender
            forged = frappe._dict(sender_endpoint=str(chat_id), channel=telegram.name, relay_contact=fixture.contact.name,
                provider_context=dict(provider='Telegram', chat_type=chat_type, chat_id=chat_id,
                    participant_id=participant, message_id=1), content='I am ' + address)
            denied(lambda: authenticated_sender(forged, telegram))
        print('PASS site: two companies, Supplier/Customer name collision, fixed filters before pagination, guessed names, canonical identity, revocation, query hooks, field denial and private senders')
        for label, reads, company in [('Announcement', [], companies[0].name),
                ('Company', [], companies[1].name), ('Result', reader.evidence, companies[0].name)]:
            earlier = insert('Relay Message', 'Earlier ' + label, relay_contact=fixture.contact.name,
                channel=binding.channel, sender_endpoint=address, direction='Incoming', message_type='text',
                content='Search October', business_doctype='Supplier', business_name=supplier.name,
                provider_context=json.dumps(provenance), conversation_key=message.conversation_key)
            insert('Relay Automation Run', 'Earlier ' + label, message=earlier.name, skill=skill.name,
                skill_version=str(skill.modified), status='Completed', event_key='Sim Earlier ' + label + ' ' + stamp,
                decision=json.dumps(dict(user=user, reads=reads, handoff=False,
                    reply='May I search October?' if label == 'Announcement' else 'Inaccessible previous balance',
                    scope=fingerprint(dict(scope, message=earlier.name, company=company)))))
        frappe.db.commit()
        expected_history = [{'direction': 'Incoming', 'content': 'Search October'},
            {'direction': 'Outgoing', 'content': 'May I search October?'}]
        actual_history = service.conversation_history(skill, message, user, business, scope)
        assert actual_history == expected_history, actual_history

        def model(skill, user, business, prompt, run_id, *, scope):
            assert json.loads(prompt)['history'] == expected_history
            current = json.loads(skill.allowed_tools)[0]
            reader = Reader(skill, user, business, scope)
            result = reader.read(current, limit=1)
            return dict(reply='Debit ' + result['totals']['debit'], handoff=False, reason='', user=user, reads=reader.evidence)
        original_init = frappe.app.init_request
        def init_request(request):
            original_init(request)
            frappe.flags.mute_emails = True
            frappe.conf.relay_automation_enabled = 0
        def application(environ, start_response):
            environ['HTTP_X_FRAPPE_SITE_NAME'] = 'yrp.site'
            return frappe.app.application(environ, start_response)
        client = Client(application, Response)
        path = '/api/method/relay_core.ai.configuration.test_skill'
        def request(auth=True, method='POST'):
            response = client.open(path, method=method, headers={'Authorization': authorization if auth is True else auth} if auth else {},
                json={'name': skill.name, 'message': message.name})
            response.close()
            return response
        frappe.destroy()
        with patch.object(frappe.app, 'init_request', init_request), patch.object(adapter, 'complete', side_effect=model):
            response = request()
            assert response.status_code == 200, ('preview', response.status_code)
            result = response.json['message']
            assert result['mode'] == 'Shadow' and result['reply'] in ('Debit 1250', 'Debit 1250.0')
            assert set(result) == {'reply', 'handoff', 'reason', 'user', 'reads', 'scope', 'mode'}
            assert result['reads'][0]['scope'] == result['scope'] == fingerprint(scope)
            with patch.object(frappe, 'get_hooks', side_effect=company_hooks), patch.object(frappe, 'get_attr',
                    side_effect=lambda name: (lambda *args, **kw: '1=0') if name == hook_name else original_attr(name)):
                response = request()
                assert response.status_code == 200
                assert response.json['message'] == dict(mode='Shadow', reply='', handoff=True,
                    reason='Decision or authorization failed')
            connect(); frappe.db.set_value('Relay Contact Endpoint', binding.name, 'verified', 0); frappe.db.commit(); frappe.destroy()
            response = request()
            assert response.status_code == 200
            assert response.json['message'] == dict(mode='Shadow', reply='', handoff=True, reason='Decision or authorization failed')
            for auth in (False, denied_authorization):
                response = request(auth=auth)
                assert response.status_code in (401, 403) and response.json['exc_type'] == 'PermissionError'
            response = request(method='GET')
            assert response.status_code == 403
        connect()
        assert not frappe.db.exists('Relay Automation Run', {'message': message.name})
        assert not frappe.db.exists('Relay Message Action', {'source_message': message.name})
        print('PASS HTTP preview: status, exact shape, scoped non-zero result/history, revoked binding handoff, staff/guest and method denial, no operational writes')
    finally:
        if not getattr(frappe.local, 'db', None): connect()
        frappe.set_user('Administrator'); frappe.db.rollback()
        fixture.person.reload()
        fixture.person.links = [row for row in fixture.person.links if (row.link_doctype, row.link_name) not in created]
        fixture.person.save()
        for dt, name in reversed(created):
            if frappe.db.exists(dt, name):
                frappe.delete_doc(dt, name, force=True, ignore_permissions=True, delete_permanently=True)
        frappe.db.commit()
        print('CLEANED local Sim scope fixtures')


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
    company = 'Sim Channel Company ' + fixture.stamp
    frappe.get_doc(dict(doctype='Company', name=company, company_name=company,
        abbr='SC', default_currency='INR', country='India')).db_insert()
    fixture.customer.customer_details = 'Sim Order quantity 25, amount 1250'
    fixture.customer.save(); frappe.db.commit()
    contract = dict(name='customer', method='get_doc', doctype='Customer',
                    fields=['name', 'customer_details'], scope_field='name', identity_anchor='Customer',
                    identity_fields={'Telegram': 'alias', 'Email': 'alias'}, company_field='represents_company')
    partner = user('relay-c3-partner-' + fixture.stamp + '@example.invalid', manager=True)
    unrelated = business('C3 denied ' + fixture.stamp)
    restriction = frappe.get_doc(dict(doctype='User Permission', user=partner, allow='Customer',
        for_value=fixture.customer.name, apply_to_all_doctypes=1)).insert()
    frappe.db.commit()
    account=frappe.get_doc(dict(doctype='AI Provider Account',name='Sim Skill Account '+fixture.stamp,
        account_label='Sim Skill Account '+fixture.stamp,provider='OpenRouter',enabled=1));account.db_insert()
    model_record=frappe.get_doc(dict(doctype='AI Model',name='Sim Skill Model '+fixture.stamp,model_label='Sim Skill Model '+fixture.stamp,
        account=account.name,provider='OpenRouter',model_id='local-no-network',enabled=1));model_record.db_insert()
    provider_counter = 700
    context = {}
    def model(skill, user, business, prompt, run_id, *, scope):
        reader = Reader(skill, user, business, scope)
        rows = reader.read(contract, name=fixture.customer.name)
        assert '1250' in str(rows)
        return dict(reply='Order quantity 25, amount 1250', handoff=False, reason='', user=user, reads=reader.evidence)

    from site_labels import phone
    for provider, address in [('Telegram', phone(fixture.stamp)), ('Email', 'ai-' + fixture.stamp.lower() + '@example.invalid')]:
        binding = endpoint(fixture, provider, address)
        frappe.db.set_value('Relay Channel', binding.channel, 'company', company)
        fixture.customer.alias = address
        # This company boundary is explicit test configuration, not an inferred customer owner.
        frappe.db.set_value('Customer', fixture.customer.name, {'alias': address, 'represents_company': company})
        skill = frappe.get_doc(dict(doctype='Relay AI Skill', name='Sim ' + provider + ' Event ' + fixture.stamp,
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
                context.update(chat_id=int(address), chat_type='private', participant_id=int(address), message_id=provider_counter)
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
                assert args['chat_id'] == int(address) and 'message_thread_id' not in args
                assert '1250' in args['text']
            else:
                assert args['subject'] == 'Re: Sim Order 25'
                assert args['in_reply_to'] == context['message_id'] and args['references'][-1] == context['message_id']
                assert args['auto_submitted'] is True and args['cc'] == [] and args['bcc'] == []
                outgoing = frappe.get_doc('Relay Message',action.outbound_message)
                assert json.loads(outgoing.provider_context)['email_thread_id'] == context['email_thread_id']
                # An enabled fixed rule cannot compete with this business's skill.
                fixed = frappe.get_doc(dict(doctype='Relay Email Rule', name='Sim Fixed Reply ' + fixture.stamp,
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
            episode = None
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
                ticket = frappe.get_doc('Relay Ticket',pending.ticket)
                if episode:
                    assert ticket.name == episode
                else:
                    episode = ticket.name
                    assert ticket.source_run == pending.name
                assert frappe.db.count('Relay Ticket', {'active_scope_key':ticket.active_scope_key}) == 1
                assert frappe.db.get_value('Relay Message', message.name, 'ticket') == ticket.name
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
            def revoked(skill, user, business, prompt, run_id, *, scope):
                decision = model(skill,user,business,prompt,run_id,scope=scope)
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
            def taken_over(skill,user,business,prompt,run_id, *, scope):
                decision = model(skill,user,business,prompt,run_id,scope=scope)
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
