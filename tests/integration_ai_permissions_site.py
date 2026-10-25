"""Local channel AI, permission and REST proof; provider calls stay intercepted."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from contextlib import contextmanager, ExitStack


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


SITES = '/home/sakthi/development/pilot/benches/version_16/sites'


@contextmanager
def local_fixtures():
    """Delete only rows inserted by this process, including children and auth rows."""
    import frappe
    from frappe.model.base_document import BaseDocument
    created = []
    original = BaseDocument.db_insert
    def tracked(doc, *args, **kwargs):
        assert frappe.local.site == 'yrp.site'
        result = original(doc, *args, **kwargs)
        created.append((doc.doctype, doc.name))
        return result
    with ExitStack() as stack:
        stack.enter_context(patch.object(BaseDocument, 'db_insert', tracked))
        stack.enter_context(patch.object(frappe, 'sendmail'))
        stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('External HTTP forbidden')))
        try:
            yield created
        finally:
            if not getattr(frappe.local, 'db', None):
                frappe.init(site='yrp.site', sites_path=SITES); frappe.connect()
            assert frappe.local.site == 'yrp.site'
            frappe.set_user('Administrator'); frappe.db.rollback()
            for doctype, name in reversed(created):
                frappe.db.delete('__Auth', {'doctype': doctype, 'name': name})
                frappe.db.delete(doctype, {'name': name})
            frappe.db.commit()
            assert all(not frappe.db.exists(dt, name) for dt, name in created)
            print('CLEANUP all inserted fixtures deleted, including Companies, Accounts and child rows')


def main():
    sys.addaudithook(confine_writes)
    os.environ.update(FRAPPE_STREAM_LOGGING='1', SITES_PATH=SITES, RELAY_AUTOMATION_TEST_SITES=SITES, RELAY_TEST_SITE='yrp.site')
    import frappe
    import relay_core
    from channel_site_fixtures import init
    from channel_identity_fixtures import scenario, configured
    assert Path(relay_core.__file__).resolve().parents[1] == Path(__file__).resolve().parents[1]
    init()
    with local_fixtures():
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
                channel_ai_cases(fixture_data)
                sender_scope_cases(fixture_data)
        finally:
            frappe.db.rollback()
    frappe.destroy()


def channel_ai_cases(fixture):
    """Both channel transports must announce before real, identity-scoped reads."""
    import frappe
    from channel_identity_fixtures import endpoint
    from channel_site_fixtures import user, business
    from site_labels import phone
    from relay_core import whatsapp
    from relay_core.ai import service, adapter
    from relay_core.ai.tools import Reader, as_user
    from relay_core.automation import service as automation, queue
    from relay_core.automation.provenance import conversation_key
    from relay_core.tickets import resume_ai
    from relay_core.flows.actions import proposal

    frappe.set_user('Administrator')
    company = 'Sim Channel Company ' + fixture.stamp
    frappe.get_doc(dict(doctype='Company', name=company, company_name=company,
        abbr='SC', default_currency='INR', country='India')).db_insert()
    other_company = company + ' Other'
    frappe.get_doc(dict(doctype='Company', name=other_company, company_name=other_company,
        abbr='SO', default_currency='INR', country='India')).db_insert()
    fixture.customer.customer_details = 'Sim Order quantity 25, amount 1250'
    fixture.customer.save()
    partner = user('sim-channel-partner-' + fixture.stamp + '@example.invalid', manager=True)
    unrelated = business('Channel denied ' + fixture.stamp)
    restriction = frappe.get_doc(dict(doctype='User Permission', user=partner, allow='Customer',
        for_value=fixture.customer.name, apply_to_all_doctypes=1)).insert()
    contract = dict(name='customer', method='get_doc', doctype='Customer',
        fields=['name', 'customer_details'], scope_field='name', identity_anchor='Customer',
        identity_fields={'Telegram':'alias', 'Email':'alias'}, company_field='represents_company')
    counter = 0
    for provider, address in [('Telegram', phone(fixture.stamp)), ('Email', 'sim-ai-'+fixture.stamp.lower()+'@example.invalid')]:
        binding = endpoint(fixture, provider, address)
        frappe.db.set_value('Relay Channel', binding.channel, dict(company=company, triage_owner=fixture.actor))
        frappe.db.set_value('Customer', fixture.customer.name, dict(alias=address, represents_company=company))
        skill = frappe.get_doc(dict(doctype='Relay AI Skill', name='Sim '+provider+' Read '+fixture.stamp,
            title='Sim '+provider+' Read', enabled=1, channel=binding.channel, business_doctype='Customer',
            run_as_user=fixture.actor, handoff_owner=fixture.actor, mode='Automatic', daily_limit=100,
            target='Confirm my order quantity and amount', exact_trigger='/order', execution_policy='Execute',
            search_confirmation='Always', instructions='Read only the authenticated sender in this company.',
            allowed_tools=json.dumps([contract]), allowed_actions='[{"action":"reply"}]'))
        skill.db_insert(); frappe.db.commit()
        frappe.conf.relay_automation_enabled = 1
        plan = dict(reference='customer', purpose='confirm your quantity and amount', fields=contract['fields'],
            arguments={'name':fixture.customer.name})
        reads, outbound = [], []
        revoke = False
        def source(body='/order', automatic=False):
            nonlocal counter
            counter += 1
            context = dict(provider=provider, message_id=counter)
            if provider == 'Telegram':
                context.update(chat_id=int(address), chat_type='private', participant_id=int(address))
            else:
                context.update(message_id=f'<sim-ai-{counter}-{fixture.stamp}@example.invalid>',
                    email_thread_id='<sim-thread-'+fixture.stamp+'@example.invalid>', subject='Sim Order 25',
                    authentication={'status':'pass'}, auto_submitted=automatic)
            doc = frappe.get_doc(dict(doctype='Relay Message', relay_contact=fixture.contact.name,
                channel=binding.channel, sender_endpoint=address, direction='Incoming', message_type='text',
                content=body, status='Sent', business_doctype='Customer', business_name=fixture.customer.name,
                provider_context=json.dumps(context), conversation_key=conversation_key(binding.channel,address,context))).insert()
            frappe.db.commit()
            return doc
        def run(message):
            queue._process(message.name); frappe.db.commit()
            name=frappe.db.get_value('Relay Automation Run', {'message':message.name}, 'name')
            assert name, provider+' event was not admitted'
            automation.process(name)
            return frappe.get_doc('Relay Automation Run',name)
        def deny(call):
            try: call()
            except (ValueError,frappe.PermissionError): return
            raise AssertionError('Out-of-scope channel read succeeded')
        def reader(event, actor, business, scope, run_id):
            return Reader(event,actor,business,scope,
                authorize=lambda ref,args:service.authorize_search(run_id,event,ref,args))
        def model(event, actor, business, prompt, run_id, *, scope, search=None, **kwargs):
            if search is None:
                deny(lambda:reader(event,actor,business,scope,run_id).read(contract,**plan['arguments']))
                return dict(reply='',handoff=False,reason='',user=actor,reads=[],search=plan)
            assert search==plan
            assert outbound and 'I will search customer' in outbound[-1]['text' if provider=='Telegram' else 'body']
            # The declaration journal is real; it cannot authorize another name.
            deny(lambda:reader(event,actor,business,scope,run_id).read(contract,name=unrelated.name))
            # Probe actual identity/company checks with the same authorized plan.
            for field, wrong, original in [('alias','wrong@example.invalid',address),
                    ('represents_company',other_company,company)]:
                frappe.db.set_value('Customer',fixture.customer.name,field,wrong)
                deny(lambda:reader(event,actor,business,scope,run_id).read(contract,**plan['arguments']))
                frappe.db.set_value('Customer',fixture.customer.name,field,original)
            current=reader(event,actor,business,scope,run_id)
            result=current.read(contract,**plan['arguments'])
            assert result=={'name':fixture.customer.name,'customer_details':'Sim Order quantity 25, amount 1250'}
            reads.append(result)
            if revoke:
                previous=frappe.session.user
                frappe.set_user('Administrator')
                restriction.for_value=unrelated.name; restriction.save(); frappe.db.commit()
                frappe.clear_cache(user=partner);frappe.set_user(previous)
            return dict(reply='',handoff=False,reason='',user=actor,reads=current.evidence,
                actions=[proposal(event,'reply',{'text':'Order quantity 25, amount 1250'})])
        def transport(tool, arguments):
            outbound.append(arguments)
            return {'message_id':901+len(outbound) if provider=='Telegram' else f'<sim-reply-{len(outbound)}-{fixture.stamp}@example.invalid>'}
        def reset_hold():
            frappe.set_user('Administrator')
            for name in frappe.get_all('Relay Ticket', filters={'company':company,'ai_disabled':1,'active_scope_key':['is','set']},pluck='name'):
                resume_ai(name)
            frappe.db.commit()
        with patch.object(adapter,'complete',side_effect=model), patch.object(whatsapp,'client') as client:
            client.return_value.call_tool.side_effect=transport
            first=source(); offer=run(first)
            assert offer.status=='Completed' and offer.stage=='Search' and not reads and len(outbound)==1, (provider,offer.status,offer.reason)
            assert json.loads(offer.decision)['reads']==[]
            with as_user(fixture.actor):
                actor,business_ref,scope=service.context(skill,first)
                deny(lambda:reader(skill,actor,business_ref,scope,offer.name).read(contract,**plan['arguments']))
            confirmed=source('yes'); result=run(confirmed)
            assert result.status=='Completed' and result.ticket and len(reads)==1 and len(outbound)==2, (provider,result.status,result.reason)
            assert json.loads(result.decision)['reads'][0]['tool']=='customer'
            args=outbound[-1]
            if provider=='Telegram':
                assert args['chat_id']==int(address) and 'message_thread_id' not in args and '1250' in args['text']
            else:
                context=json.loads(confirmed.provider_context)
                assert args['subject']=='Re: Sim Order 25' and args['in_reply_to']==context['message_id']
                assert args['auto_submitted'] is True and args['cc']==[] and args['bcc']==[]
                suppressed=source(automatic=True);queue._process(suppressed.name);frappe.db.commit()
                assert not frappe.db.exists('Relay Automation Run',{'message':suppressed.name})
            automation.process(result.name)
            assert len(outbound)==2 and len(reads)==1
            # Revoke the real linked user's permission after reading; the worker
            # must hand off rather than dispatch a now-unauthorized result.
            fixture.person.user=partner;fixture.person.save();frappe.db.commit()
            run(source()); calls=len(outbound);revoke=True
            failed=run(source('yes'))
            assert failed.status=='Handoff' and failed.ticket and len(outbound)==calls, (provider,failed.status,failed.reason)
            automation.process(failed.name);assert len(outbound)==calls
            fixture.person.user=None;fixture.person.save()
            restriction.for_value=fixture.customer.name;restriction.save();frappe.clear_cache(user=partner)
            frappe.db.commit();reset_hold();revoke=False
            with patch.object(adapter,'complete',side_effect=AssertionError('Human request must bypass model')):
                human=run(source('Talk to a human'))
            assert human.status=='Handoff' and human.ticket and len(outbound)==calls
            reset_hold()
        frappe.db.set_value('Relay AI Skill',skill.name,'enabled',0);frappe.db.commit()
        print('PASS',provider,'declared search and confirmation, identity/company/business read scope, non-zero reply, transport shape, replay, revoked-user and human handoff')
    frappe.conf.relay_automation_enabled=0


def sender_scope_cases(fixture):
    """Real company/identity permission probes and read-free preview HTTP."""
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

    # Probe the real permission layer independently of search delivery. The event
    # suite exercises the real declaration/confirmation journal before SEARCH.
    def authorized(reference, arguments):
        assert reference['name'] == 'ledger'
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
            target='Read my ledger', exact_trigger='My confirmed ledger for October', execution_policy='Execute',
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
        reader = Reader(skill, user, business, scope, authorize=authorized)
        result = reader.read(contract, limit=1)
        assert result['totals']['debit'] == '1250.0' or result['totals']['debit'] == '1250'
        assert [row['name'] for row in result['rows']] == [rows[0].name] and not result['truncated']
        assert set(result['rows'][0]) == set(contract['fields'])
        recheck(skill, user, business, reader.evidence, scope, authorize=authorized)
        one = contract | {'method': 'get_doc'}
        skill.allowed_tools = json.dumps([one])
        for row in rows[1:]: denied(lambda: Reader(skill, user, business, scope, authorize=authorized).read(one, name=row.name))
        assert Reader(skill, user, business, scope, authorize=authorized).read(one, name=rows[0].name)['debit'] == 1250
        skill.allowed_tools = json.dumps([contract])
        denied(lambda: reader.read(contract, filters={'company': companies[1].name}))
        for dt, name, field, value, original in [
                ('Relay Contact Endpoint', binding.name, 'verified', 0, 1),
                ('Supplier', supplier.name, 'alias', 'different@example.invalid', address),
                ('Relay Channel', binding.channel, 'company', companies[1].name, companies[0].name),
                ('User', actor.name, 'enabled', 0, 1)]:
            frappe.db.set_value(dt, name, field, value)
            denied(lambda: recheck(skill, user, business, reader.evidence, scope, authorize=authorized))
            frappe.db.set_value(dt, name, field, original)
        frappe.db.set_value('GL Entry', rows[0].name, 'debit', 2500)
        denied(lambda: recheck(skill, user, business, reader.evidence, scope, authorize=authorized))
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
            denied(lambda: Reader(skill, user, business, scope, authorize=authorized).read(one, name=rows[0].name))
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

        def model(skill, user, business, prompt, run_id, *, scope, **kwargs):
            assert json.loads(prompt)['history'] == expected_history
            return dict(reply='Confirm October before reading', handoff=False, reason='', user=user, reads=[],
                search=dict(purpose='Read my October ledger', reference='ledger', fields=contract['fields'],
                    arguments={'filters': {'posting_date': ['between', ['2026-10-01', '2026-10-31']]}}))
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
            assert result['mode'] == 'Shadow' and result['reply'] == 'Confirm October before reading'
            assert set(result) == {'reply', 'handoff', 'reason', 'identity_scope', 'match', 'reads', 'actions', 'mode', 'search'}
            assert result['identity_scope']['company'] == companies[0].name
            assert result['reads'] == [] and result['search']['reference'] == 'ledger'
            with patch.object(frappe, 'get_hooks', side_effect=company_hooks), patch.object(frappe, 'get_attr',
                    side_effect=lambda name: (lambda *args, **kw: '1=0') if name == hook_name else original_attr(name)):
                response = request()
                assert response.status_code == 200
                assert response.json['message'] == dict(mode='Shadow', reply='', handoff=True,
                    reason='Decision or authorization failed', identity_scope=None, match=None, reads=[], actions=[])
            connect(); frappe.db.set_value('Relay Contact Endpoint', binding.name, 'verified', 0); frappe.db.commit(); frappe.destroy()
            response = request()
            assert response.status_code == 200
            assert response.json['message'] == dict(mode='Shadow', reply='', handoff=True, reason='Decision or authorization failed', identity_scope=None, match=None, reads=[], actions=[])
            for auth in (False, denied_authorization):
                response = request(auth=auth)
                assert response.status_code in (401, 403) and response.json['exc_type'] == 'PermissionError'
            response = request(method='GET')
            assert response.status_code == 403
        connect()
        assert not frappe.db.exists('Relay Automation Run', {'message': message.name})
        assert not frappe.db.exists('Relay Message Action', {'source_message': message.name})
        print('PASS HTTP preview: status, exact shape, scoped proposed search/history, revoked binding handoff, staff/guest and method denial, no operational writes')
    finally:
        if not getattr(frappe.local, 'db', None): connect()
        frappe.set_user('Administrator'); frappe.db.rollback()
        fixture.person.reload()
        fixture.person.links = [row for row in fixture.person.links if (row.link_doctype, row.link_name) not in created]
        fixture.person.save()
        frappe.db.commit()



if __name__ == '__main__':
    main()
