"""Step 8: normal ERP drafts, shared agent, HTTP admission and journaled replies.

Run on yrp.site only. The shared fixture harness intercepts external effects and
deletes every inserted fixture, including Accounts, Companies and Payment Entries.
"""
import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import patch


def exercise(*, stack, raw, actor, company, supplier, contact, event, source, request, stamp):
    import frappe
    from PIL import Image, ImageDraw
    from frappe_tools.ai import client
    from relay_core.ai import adapter
    from relay_core.ai.actions import PAYMENT_SCHEMA
    from relay_core.automation import service, queue
    from relay_core.flows import actions

    vision_model = raw('AI Model', 'Draft Vision', model_label='Sim Draft Vision '+stamp,
        enabled=1, supports_vision=1, model_id='Sim')
    frappe.db.set_value('Relay AI Skill', event.name, 'ai_model', vision_model.name)
    bank = raw('Account', 'Draft Bank', account_name='Sim Draft Bank '+stamp, company=company.name,
        account_type='Bank', root_type='Asset', report_type='Balance Sheet', account_currency='INR', is_group=0)
    payable = raw('Account', 'Draft Payable', account_name='Sim Draft Payable '+stamp, company=company.name,
        account_type='Payable', root_type='Liability', report_type='Balance Sheet', account_currency='INR', is_group=0)
    frappe.db.set_value('Company', company.name, dict(default_payable_account=payable.name, default_bank_account=bank.name))
    declared = [dict(action='create_draft', doctype='Payment Entry', fields=list(PAYMENT_SCHEMA['properties'])),
                dict(action='reply')]
    frappe.db.set_value('Relay AI Skill', event.name, dict(allowed_actions=json.dumps(declared),
        instructions='Create a draft Payment Entry from the screenshot, then reply thanks. '
        'If the amount or currency is unclear, leave a ticket note for staff. '
        'For INR use bank '+bank.name+' and payable '+payable.name+'.', target='Payment screenshot'))
    event.reload()
    assert {'create_draft', 'reply'} <= actions.definitions().keys()
    from relay_core.ai.configuration import action_contracts
    assert action_contracts(event) == declared
    frappe.db.commit()

    raw_image = io.BytesIO()
    picture = Image.new('RGB', (400, 120), 'white')
    ImageDraw.Draw(picture).text((15, 40), 'Payment INR 1250.00', fill='black')
    picture.save(raw_image, format='PNG')
    image_bytes = raw_image.getvalue()
    sends, observations, turns = [], [], []
    fault = None
    def transport(tool, values):
        if tool == 'whatsapp.deliveries':
            return {'deliveries': [dict(key=values['request_key'], state='submitted',
                result={'messages': [{'id': 'sim-recovered-ack'}]})]}
        if tool == 'whatsapp.attachment':
            assert values == {'media_id': '1250'}
            if fault == 'attachment':
                raise frappe.PermissionError('Sim attachment denied')
            return dict(content_base64=base64.b64encode(image_bytes).decode(), content_type='image/png')
        assert tool == 'whatsapp.execute', tool
        assert values['operation'] == 'messages.send'
        sends.append(values)
        if fault == 'uncertain_reply_first':
            return {'delivery': {'state': 'uncertain'}}
        return {'messages': [{'id': 'sim-draft-ack-'+str(len(sends))}]}
    provider = SimpleNamespace(
        user_message=lambda text, images: {'text': text},
        continuation=lambda response, outputs: [{'outputs': outputs}],
        build_turn=lambda credentials, model, system, messages, schema, options, definitions, final:
            dict(system=system, messages=messages, definitions=definitions),
        build_request=lambda credentials, model, system, user, images, schema, options:
            dict(images=images, system=system))
    def model(account, model_id, build, options, context, deadline):
        payload = build(provider, {}, model_id)
        run = frappe.get_doc('Relay Automation Run', context['run_id'])
        assert run.ticket, 'Ticket must precede all model and action work'
        calls, data = [], None
        if 'images' in payload:
            assert payload['images'] == ['data:image/png;base64,'+base64.b64encode(image_bytes).decode()]
            observations.append(run.name)
            data = {'observation': 'Payment INR 1250.00' if fault != 'unclear' else 'Amount and currency are unreadable'}
        elif fault == 'undeclared_reply':
            data = dict(reply='This reply was never declared', handoff=False, reason='')
        elif fault == 'unclear':
            assert 'unreadable' in payload['messages'][0]['text']
            data = dict(reply='', handoff=True, reason='Payment amount and currency are unclear; staff must check the screenshot')
        elif len(payload['messages']) == 1:
            assert '1250' in payload['messages'][0]['text']
            turns.append(run.name)
            values = dict(payment_type='Pay', posting_date='2026-10-25', paid_amount=1250,
                received_amount=1250, paid_from=bank.name, paid_to=payable.name,
                source_exchange_rate=1, target_exchange_rate=1, reference_no='Sim Evidence '+stamp,
                reference_date='2026-10-25')
            if fault == 'zero': values['paid_amount'] = 0
            if fault == 'foreign': values['paid_from'] = foreign.name
            calls = [dict(id='draft', name='EXECUTE', arguments=dict(action='create_draft', parameters=values)),
                     dict(id='reply', name='EXECUTE', arguments=dict(action='reply', parameters={
                         'text': 'Thanks. We received your screenshot showing INR 1250. Our team will check the draft.'}))]
            if fault == 'uncertain_reply_first':
                calls.reverse()
        else:
            data = dict(reply='', handoff=False, reason='')
        return dict(ok=True, result=dict(data=data, tool_calls=calls, response={}))
    stack.enter_context(patch.object(adapter, 'route', return_value=(frappe._dict(provider='Sim'),
        frappe._dict(model_id='Sim', supports_vision=1), [], dict(timeout=20, max_tokens=1200, attempts=1))))
    stack.enter_context(patch.dict(client.PROVIDERS, Sim=provider))
    stack.enter_context(patch.object(client, 'try_model', side_effect=model))
    stack.enter_context(patch('relay_core.whatsapp.client', return_value=SimpleNamespace(call_tool=transport)))

    def run_message(label, *, image=True, policy='Execute'):
        text = 'Sim '+label+' screenshot' if image else 'Sim '+label+' payment INR 1250'
        frappe.db.set_value('Relay Contact', contact.name, {'automation_paused': 0})
        frappe.db.set_value('Relay AI Skill', event.name, dict(exact_trigger=text, execution_policy=policy))
        frappe.db.commit()
        doc = source(text)
        if image:
            frappe.db.set_value('Relay Message', doc.name, dict(message_type='photo', message_data=json.dumps({'media': {'id': '1250'}})))
            frappe.db.commit()
        denied = request('automation.service.enqueue', {'message': doc.name}, authenticated=False)
        assert denied.status_code in (401, 403) and denied.json['exc_type'] == 'PermissionError'
        response = request('automation.service.enqueue', {'message': doc.name})
        assert response.status_code == 200 and set(response.json['message']) == {'name', 'status'}
        name = response.json['message']['name']
        service.process(name)
        return doc, frappe.get_doc('Relay Automation Run', name)

    doc, run = run_message('Payment')
    assert run.status == 'Completed', (run.status, run.reason)
    journals = frappe.get_all('Relay Flow Action', filters={'automation_run': run.name},
        fields=['name', 'action', 'status', 'target_name', 'ticket'], order_by='step asc')
    assert [j.action for j in journals] == ['create_draft', 'reply'] and all(j.status == 'Completed' for j in journals)
    draft = frappe.get_doc('Payment Entry', journals[0].target_name)
    assert draft.docstatus == 0 and draft.paid_amount == draft.received_amount == 1250
    assert draft.owner == actor.name and draft.company == company.name and draft.party == supplier.name
    assert journals[0].ticket == run.ticket and len(sends) == 1 and sends[0]['body'].startswith('Thanks.')
    assert len(observations) == 1 and len(turns) == 1
    message_actions = frappe.get_all('Relay Message Action', filters={'source_message': doc.name}, fields=['status', 'outbound_message'])
    assert len(message_actions) == 1 and message_actions[0].status == 'Submitted' and message_actions[0].outbound_message
    assert frappe.db.count('GL Entry', {'voucher_type': 'Payment Entry', 'voucher_no': draft.name}) == 0
    detail = request('tickets.read', {'name': run.ticket}, verb='GET')
    assert detail.status_code == 200 and detail.json['message']['linked_drafts'] == [
        dict(doctype='Payment Entry', name=draft.name, docstatus=0)]
    assert request('tickets.read', {'name': run.ticket}, verb='GET', authenticated=False).status_code in (401, 403)
    replay = request('automation.service.enqueue', {'message': doc.name})
    assert replay.status_code == 200 and replay.json['message']['name'] == run.name
    queue._process(doc.name); frappe.db.commit(); service.process(run.name)
    assert frappe.db.count('Payment Entry', {'company': company.name}) == 1 and len(sends) == 1
    print('PASS screenshot -> shared image/agent path -> normal INR 1250 draft -> ticket HTTP link -> journaled thanks; duplicate replay; no submission or GL entries')

    _, ticket_only = run_message('Ticket only', policy='Ticket only')
    assert ticket_only.status == 'Completed' and ticket_only.ticket
    assert not frappe.db.exists('Relay Flow Action', {'automation_run': ticket_only.name})
    assert len(sends) == len(observations) == 1
    print('PASS Ticket only creates no draft, model call, attachment fetch or acknowledgement')

    for fault in ('unclear', 'attachment', 'zero'):
        _, failed = run_message(fault.title())
        assert failed.status == 'Handoff' and failed.ticket, (fault, failed.status, failed.reason)
        assert frappe.db.count('Payment Entry', {'company': company.name}) == 1 and len(sends) == 1
        note = frappe.db.get_value('Relay Ticket', failed.ticket, 'handoff_reason')
        assert note and ('unclear' in note if fault == 'unclear' else True)
    fault = None
    print('PASS unclear amount/currency leaves ticket note; inaccessible attachment and zero amount create no draft or reply')

    before_observations = len(observations)
    frappe.db.set_value('AI Model', vision_model.name, 'supports_vision', 0)
    with patch('relay_core.attachments.read', side_effect=AssertionError('Vision gate must precede fetch')) as fetch:
        _, no_vision = run_message('No vision')
        assert no_vision.status == 'Handoff' and not fetch.called
    assert len(observations) == before_observations and len(sends) == 1
    frappe.db.set_value('AI Model', vision_model.name, 'supports_vision', 1)
    print('PASS model without vision is denied before attachment fetch or provider call')

    # Flow HTTP catalog must not advertise handlers that require an AI execution context.
    catalog = request('flows.actions.catalog', verb='GET')
    assert catalog.status_code == 200 and isinstance(catalog.json['message'], list)
    assert not {'create_draft', 'reply'} & {row['key'] for row in catalog.json['message']}
    assert request('flows.actions.catalog', verb='GET', authenticated=False).status_code in (401, 403)
    from relay_core.flows import service as flows
    flow = raw('Relay Flow', 'Draft Invalid Flow', title='Sim Draft Invalid Flow '+stamp, command='/draft',
        nodes=json.dumps([dict(id='draft', kind='action', action='create_draft', arguments={}), dict(id='end', kind='end')]))
    try: flows.validate_flow(flow)
    except frappe.ValidationError: pass
    else: raise AssertionError('AI-only handler accepted by flow validation')
    actor.append('roles', {'role': 'System Manager'}); actor.save(); frappe.db.commit(); frappe.clear_cache(user=actor.name)
    runner = frappe.get_doc(dict(doctype='User', email='sim-flow-runner-'+stamp.lower()+'@example.invalid',
        first_name='Sim Flow Runner '+stamp, send_welcome_email=0,
        roles=[{'role':'Relay Communication Manager'}, {'role':'Relay Communication User'}])).insert()
    values = dict(title='Sim Draft Flow '+stamp, command='/draft', channel=event.channel,
        execution_user=runner.name, business_doctype='Supplier', enabled=0, nodes=flow.nodes)
    invalid = request('flows.service.validate_draft', {'values': json.dumps(values)})
    assert invalid.status_code == 417 and invalid.json['exc_type'] == 'ValidationError'
    values['nodes'] = json.dumps([dict(id='end', kind='end', text='Done')])
    valid = request('flows.service.validate_draft', {'values': json.dumps(values)})
    assert valid.status_code == 200 and valid.json['message']['valid'] is True
    assert set(valid.json['message']) == {'valid', 'name', 'title', 'command', 'channel', 'execution_user',
        'business_doctype', 'enabled', 'nodes', 'template_button'}
    assert request('flows.service.validate_draft', {'values': json.dumps(values)}, authenticated=False).status_code in (401, 403)
    actor.reload(); actor.roles = [r for r in actor.roles if r.role != 'System Manager']
    actor.save(); frappe.db.commit(); frappe.clear_cache(user=actor.name)
    print('PASS flow catalog and validation HTTP status/shape/guest denial; AI-only actions excluded')

    fault = 'undeclared_reply'
    for allowlist in ([], declared[:1]):
        frappe.db.set_value('Relay AI Skill', event.name, 'allowed_actions', json.dumps(allowlist))
        _, undeclared = run_message('Undeclared reply', image=False)
        assert undeclared.status == 'Handoff' and len(sends) == 1
        assert not frappe.db.exists('Relay Flow Action', {'automation_run': undeclared.name})
    fault = None
    frappe.db.set_value('Relay AI Skill', event.name, 'allowed_actions', json.dumps(declared))
    frappe.db.set_value('Relay AI Skill', event.name, 'mode', 'Shadow')
    _, shadow = run_message('Shadow action', image=False)
    assert shadow.status == 'Shadow' and shadow.ticket
    assert [row['action'] for row in json.loads(shadow.decision)['actions']] == ['create_draft', 'reply']
    assert not frappe.db.exists('Relay Flow Action', {'automation_run': shadow.name}) and len(sends) == 1
    frappe.db.set_value('Relay AI Skill', event.name, 'mode', 'Automatic')
    print('PASS undeclared final replies denied for empty/draft-only declarations; live Shadow persists proposals without writes or delivery')

    # Real create-permission denial: remove only this fixture user's accounting role.
    actor.reload()
    actor.roles = [row for row in actor.roles if row.role != 'Accounts Manager']
    actor.save(); frappe.db.commit(); frappe.clear_cache(user=actor.name)
    assert not frappe.has_permission('Payment Entry', 'create', user=actor.name)
    _, denied_run = run_message('Permission', image=False)
    assert denied_run.status == 'Handoff' and frappe.db.count('Payment Entry', {'company': company.name}) == 1
    assert len(sends) == 1
    print('PASS real effective-user create permission denial; no broader-user fallback')
    actor.append('roles', {'role': 'Accounts Manager'}); actor.save(); frappe.db.commit(); frappe.clear_cache(user=actor.name)

    other = raw('Company', 'Draft Other Company', company_name='Sim Draft Other Company '+stamp, abbr='SO', country='India', default_currency='INR')
    foreign = raw('Account', 'Draft Other Bank', account_name='Sim Draft Other Bank '+stamp, company=other.name,
        account_type='Bank', root_type='Asset', report_type='Balance Sheet', account_currency='INR', is_group=0)
    frappe.db.commit()
    fault = 'foreign'
    _, denied_run = run_message('Other company', image=False)
    assert denied_run.status == 'Handoff' and frappe.db.count('Payment Entry', {'company': company.name}) == 1
    assert len(sends) == 1
    print('PASS foreign-company account denied before insertion')

    fault = 'uncertain_reply_first'
    _, rejected = run_message('Reordered', image=False)
    assert rejected.status == 'Handoff' and len(sends) == 1
    assert frappe.db.count('Payment Entry', {'company': company.name}) == 1
    print('PASS model-reordered chain is rejected before any reply or draft')
    # An owner may explicitly declare reply before draft; uncertain delivery still fences the draft.
    frappe.db.set_value('Relay AI Skill', event.name, 'allowed_actions', json.dumps(list(reversed(declared))))
    doc, waiting = run_message('Reply first', image=False)
    assert waiting.status == 'Delivering'
    assert frappe.db.count('Payment Entry', {'company': company.name}) == 1, 'Uncertain reply must stop later steps'
    assert len(sends) == 2
    fault = None
    from relay_core import messaging
    from relay_core.ai import service as ai
    from relay_core.ai.tools import as_user
    reply_action = frappe.db.get_value('Relay Message Action', {'source_message': doc.name}, 'name')
    with as_user(actor.name):
        assert messaging.reconcile(reply_action)['status'] == 'Submitted'
    ai.complete_delivery(reply_action)
    service.process(waiting.name); waiting.reload()
    assert waiting.status == 'Completed' and frappe.db.count('Payment Entry', {'company': company.name}) == 2
    assert len(sends) == 2
    ai.complete_delivery(reply_action); waiting.reload()
    assert waiting.status == 'Completed'
    assert frappe.db.count('Payment Entry', {'company': company.name, 'docstatus': ['!=', 0]}) == 0
    print('PASS reply-first chain waits for uncertain receipt, resumes draft creation, and ignores late duplicate receipts')

    for method in ('ai.actions.create_draft', 'ai.actions.reply', 'ai.adapter.observe_image',
                   'ai.adapter.complete', 'ai.service.dispatch_reply', 'ai.service.context',
                   'ai.service.decide', 'ai.service.process', 'ai.service.complete_delivery',
                   'automation.contracts.action_key', 'ai.adapter.require_vision', 'flows.actions.validate_sequence'):
        response = request(method)
        assert response.status_code == 403 and response.json['exc_type'] == 'PermissionError'
    print('PASS action and image helpers are not HTTP-callable')


if __name__ == '__main__':
    from integration_ai_actions_site import main
    main(exercise=exercise)
