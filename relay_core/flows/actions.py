"""Shared flow/AI journal. Local writes and results share the caller's transaction.

Installed hooks must be replay safe and must not commit independently. External
effects must use a durable transport and the supplied stable idempotency key.
AI handlers additionally require explicit Core registrations and scoped approval.
"""
import hashlib
import json
import re

import frappe
from relay_core.permissions import require_access, readable_contact
from relay_core.flows.action_contracts import inputs, resolve, check_schema, validate, ai_inputs


def _hook_value(value, key=None):
    # Frappe merges scalar hook leaves into lists; schema arrays remain arrays.
    if isinstance(value, dict):
        return {k:_hook_value(v,k) for k,v in value.items()}
    if isinstance(value,list) and key not in ('required','enum','contexts','channels'):
        return _hook_value(value[-1],key) if value else None
    return value


def definitions(hook="relay_flow_actions", *, context=None):
    hooks = frappe.get_hooks(hook) or {}
    if not isinstance(hooks, dict):
        return {}
    result = {}
    for key, raw in hooks.items():
        if isinstance(raw, list):
            raw = raw[-1] if raw else None
        if not isinstance(key,str) or not isinstance(raw, dict) or not re.fullmatch(r'[a-z][a-z0-9_.]{0,99}', key):
            continue
        raw=_hook_value(raw)
        contexts = raw.get('contexts', ['flow'])
        if (not isinstance(contexts, list) or not contexts or any(item not in ('flow', 'ai') for item in contexts)
                or context is not None and context not in contexts):
            continue
        if raw.get('replay_safe') is not True or not isinstance(raw.get('parameters'), dict):
            continue
        method = raw.get('method', '')
        if not isinstance(method, str) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+', method):
            continue
        try:
            check_schema(raw['parameters'])
            if raw['parameters']['type']!='object':continue
        except (ValueError,TypeError):
            continue
        result[key] = dict(raw, key=key)
    return result


@frappe.whitelist(methods=['GET'])
def catalog():
    require_access(manage=True)
    return [{'key': key, 'label': row.get('label') or key, 'description': row.get('description', ''),
             'parameters': row['parameters']} for key, row in sorted(definitions(context='flow').items())]


def _encoded(value):
    value = resolve(value, {}, references=False)
    encoded = json.dumps(value, sort_keys=True, allow_nan=False, default=str)
    if len(encoded) > 20000:
        raise ValueError('Business action snapshot exceeds 20,000 characters')
    return encoded


def _hash(value):
    return hashlib.sha256(_encoded(value).encode()).hexdigest()


def _perform(journal, definition, values, arguments, check_result=None):
    """The caller owns the transaction; a failed handler leaves no local write."""
    savepoint = 'relay_action_' + journal.action_key[:16]
    frappe.db.savepoint(savepoint)
    commit = frappe.db.commit
    def no_commit(*args, **kwargs):
        raise ValueError('Action handlers must not commit independently')
    frappe.db.commit = no_commit
    try:
        result = frappe.get_attr(definition['method'])(action_input=values,
            idempotency_key=journal.action_key, **arguments)
        result = resolve(result, {}, references=False)
        if definition.get('output'):
            validate(result, definition['output'])
        if check_result:
            check_result(result)
        journal.result, journal.status = _encoded(result), 'Completed'
        journal.save(ignore_permissions=True)
        return result
    except BaseException:
        frappe.db.rollback(save_point=savepoint)
        raise
    finally:
        frappe.db.commit = commit


def _journal(action_key, input_hash, **values):
    name = frappe.db.get_value('Relay Flow Action', {'action_key': action_key}, 'name', for_update=True)
    if name:
        doc = frappe.get_doc('Relay Flow Action', name)
        if doc.input_hash != input_hash:
            raise ValueError('Business action changed after journaling')
        return doc
    return frappe.get_doc(dict(doctype='Relay Flow Action', action_key=action_key,
        input_hash=input_hash, **values)).insert(ignore_permissions=True)


def execute(run, node, answers, key):
    require_access()
    readable_contact(run.relay_contact)
    definition = definitions(context='flow').get(node['action'])
    if not definition:
        raise ValueError('Business action is not registered or replay safe')
    values = inputs(node.get('arguments', {}), definition['parameters'], answers)
    # Preserve existing keys/hashes so already completed flow actions still replay.
    input_hash = hashlib.sha256(json.dumps([definition['method'], values], sort_keys=True).encode()).hexdigest()
    action_key = hashlib.sha256(key.encode()).hexdigest()
    # Unlike a cache lease, this lock lasts until the caller commits the result.
    frappe.db.get_value('Relay Flow Run', run.name, 'name', for_update=True)
    journal = _journal(action_key, input_hash, run=run.name, action=node['action'],
        input_snapshot=_encoded(values), status='Pending')
    if journal.result:
        return json.loads(journal.result)
    return _perform(journal, definition, values, dict(relay_contact=run.relay_contact,
        business_doctype=run.get('business_doctype'), business_name=run.get('business_name'), flow_run=run.name))


def proposal(skill, action, parameters):
    """Validate an ordered model proposal without writes (also used by preview)."""
    from relay_core.ai.configuration import action_contracts
    declared = next((row for row in action_contracts(skill) if row['action'] == action), None)
    if not declared:
        raise ValueError('Action is outside the event')
    definition = definitions().get(action)
    return dict(action=action, parameters=ai_inputs(parameters, definition, declared))


def validate_sequence(skill, steps):
    """The declaration is the owner-authorized chain, with each step used once."""
    from relay_core.ai.configuration import action_contracts
    declared = action_contracts(skill)
    if (not isinstance(steps, list) or len(steps) > 4
            or any(not isinstance(row, dict) or set(row) != {'action', 'parameters'} for row in steps)
            or steps and [row['action'] for row in steps] != [row['action'] for row in declared]):
        raise ValueError('Execute the complete declared action sequence in order')
    return declared


def _ai_context(run_name, step):
    from relay_core.ai.service import current, delivery_scope
    from relay_core.ai.configuration import action_contracts, read_contracts
    from relay_core.ai.tools import as_user
    from relay_core.business_access import scoped_document
    from relay_core.automation.service import lock_run
    run = lock_run(run_name)
    skill = frappe.get_doc('Relay AI Skill', run.skill)
    if (run.status not in ('Pending', 'Deciding') or skill.mode != 'Automatic'
            or skill.get('execution_policy') != 'Execute' or not run.ticket):
        raise ValueError('Run cannot execute actions')
    plan = json.loads(run.decision or '{}')
    steps = plan.get('actions', [])
    if (plan.get('handoff') or plan.get('search') or not isinstance(steps, list) or not 1 <= len(steps) <= 4
            or type(step) is not int or not 0 <= step < len(steps)):
        raise ValueError('A persisted ordered action plan is required')
    validate_sequence(skill, steps)
    if plan.get('reply', '').strip():
        raise ValueError('Business replies require a declared EXECUTE action')
    item = steps[step]
    if not isinstance(item, dict) or set(item) != {'action', 'parameters'}:
        raise ValueError('Invalid execution step')
    with as_user(run.execution_user):
        message = frappe.get_doc('Relay Message', run.message)
        message.check_permission('read')
        user, business, scope = current(run, skill, message)
        delivery_scope(run, skill, message, plan)
        if user != run.execution_user:
            raise ValueError('Execution identity changed')
        frappe.db.get_value('Relay Ticket', run.ticket, 'name', for_update=True)
        ticket = frappe.get_doc('Relay Ticket', run.ticket)
        if (ticket.ai_disabled or ticket.company != scope['company']
                or ticket.conversation_key != scope['conversation']
                or (ticket.business_doctype, ticket.business_name) != business):
            raise ValueError('Episode scope changed')
        declaration = next((row for row in action_contracts(skill) if row['action'] == item['action']), None)
        if not declaration:
            raise ValueError('Action is outside the event')
        definition = definitions().get(item['action'])
        values = ai_inputs(item['parameters'], definition, declaration)
        # Transport binding alone does not prove business-record identity.
        references = read_contracts(skill, scope['provider'])
        anchors = {row['identity_fields'][scope['provider']] for row in references
                   if row.get('identity_anchor') == business[0]}
        if not anchors:
            raise ValueError('An identity mapping is required for execution')
        for field in anchors:
            scoped_document(*business, {field: scope['endpoint']})
        for doctype, permission in definition['permissions'].items():
            if not frappe.has_permission(doctype, permission):
                raise frappe.PermissionError('Action permission denied')
        versions = {business[0] + ':' + business[1]: str(frappe.get_doc(*business).modified)}
        if definition['effect'] == 'create_draft':
            meta = frappe.get_meta(declaration['doctype'])
            for key, value in values.items():
                field = meta.get_field(key)
                target = field.options if field and field.fieldtype == 'Link' else (
                    values.get(field.options) if field and field.fieldtype == 'Dynamic Link' else None)
                if not target or not value:
                    continue
                linked = frappe.get_doc(target, value)
                linked.check_permission('read')
                if ((target == 'Company' and value != scope['company'])
                        or (target == business[0] and value != business[1])
                        or (linked.get('company') and linked.company != scope['company'])):
                    raise ValueError('Action target is outside the conversation')
                versions[target + ':' + value] = str(linked.modified)
        binding = dict(scope=scope, versions=versions, skill_version=str(skill.modified),
            ticket=run.ticket, generation=int(ticket.generation or 0),
            source_hash=run.message_hash, definition=definition, declaration=declaration, plan=steps)
    return run, definition, declaration, values, binding


def _ai_key(run_name, step):
    return _hash(['ai', frappe.local.site, run_name, step])


def _draft_result(result, declaration, binding, journal):
    if not isinstance(result, dict) or result.get('doctype') != declaration['doctype'] or not result.get('name'):
        raise ValueError('Draft action must return its document reference')
    doc = frappe.get_doc(result['doctype'], result['name'])
    doc.check_permission('read')
    scope = binding['scope']
    company = [f for f in doc.meta.fields if f.fieldtype == 'Link' and f.options == 'Company']
    business = [f for f in doc.meta.fields if (f.fieldtype == 'Link' and f.options == scope['business'][0])
        or (f.fieldtype == 'Dynamic Link' and doc.get(f.options) == scope['business'][0])]
    if (doc.docstatus != 0 or not any(doc.get(f.fieldname) == scope['company'] for f in company)
            or not any(doc.get(f.fieldname) == scope['business'][1] for f in business)):
        raise ValueError('Only drafts in the authenticated business and company are allowed')
    # Data references intentionally do not prevent business document deletion.
    journal.target_doctype, journal.target_name = doc.doctype, doc.name


def execute_ai(run_name, step):
    """Consume one persisted step. Never commit, submit, or choose a destination."""
    from relay_core.ai.tools import as_user
    run, definition, declaration, values, binding = _ai_context(run_name, step)
    if step and not frappe.db.exists('Relay Flow Action',
            {'action_key': _ai_key(run_name, step - 1), 'status': 'Completed'}):
        raise ValueError('Execute event steps in order')
    journal = _journal(_ai_key(run_name, step), _hash([definition['method'], values]),
        automation_run=run.name, ticket=run.ticket, action=declaration['action'], step=step,
        input_snapshot=_encoded(values), scope_snapshot=_encoded(binding), scope_fingerprint=_hash(binding),
        status='Awaiting approval' if definition['approval_policy'] == 'Required' else 'Pending')
    if journal.scope_fingerprint != _hash(binding):
        raise ValueError('Action scope, version or ownership changed')
    if journal.status == 'Completed':
        result = json.loads(journal.result)
        with as_user(run.execution_user):
            if definition['effect'] == 'create_draft':
                _draft_result(result, declaration, binding, journal)
        return dict(name=journal.name, status='Completed', result=result)
    if definition['approval_policy'] == 'Required':
        evidence = json.loads(journal.approval_evidence or '{}')
        if journal.status != 'Approved':
            return dict(name=journal.name, status='Awaiting approval')
        if evidence.get('input_hash') != journal.input_hash or evidence.get('scope_fingerprint') != journal.scope_fingerprint:
            raise ValueError('Approval does not match this action')
    with as_user(run.execution_user):
        def checked(result):
            if definition['effect'] == 'create_draft':
                _draft_result(result, declaration, binding, journal)
            # Recheck after handler work, including target versions and takeover.
            if _hash(_ai_context(run_name, step)[-1]) != journal.scope_fingerprint:
                raise ValueError('Action scope changed during execution')
        result = _perform(journal, definition, values,
            dict(automation_run=run.name, ticket=run.ticket, execution_context=binding['scope'],
                 declaration=declaration), checked)
    return dict(name=journal.name, status='Completed', result=result)


@frappe.whitelist(methods=['POST'])
def approve(name, input_hash, scope_fingerprint):
    """Approve an exact proposal only. Execution still rechecks all permissions."""
    require_access(manage=True)
    try:
        journal = frappe.get_doc('Relay Flow Action', name)
        if not journal.automation_run or journal.status != 'Awaiting approval':
            raise ValueError('Action is not awaiting approval')
        actor = frappe.session.user
        frappe.get_doc('Relay Ticket', journal.ticket).check_permission('write')
        _, definition, _, values, binding = _ai_context(journal.automation_run, journal.step)
        journal.reload()  # Run lock serializes approval with execution and other approvers.
        if (journal.status != 'Awaiting approval' or definition['approval_policy'] != 'Required'
                or input_hash != journal.input_hash or input_hash != _hash([definition['method'], values])
                or scope_fingerprint != journal.scope_fingerprint or scope_fingerprint != _hash(binding)):
            raise ValueError('Approval is stale')
        journal.approval_evidence = _encoded(dict(actor=actor, at=str(frappe.utils.now_datetime()),
            input_hash=input_hash, scope_fingerprint=scope_fingerprint))
        journal.status = 'Approved'
        journal.save(ignore_permissions=True)
        return dict(name=journal.name, status=journal.status)
    except ValueError:
        frappe.throw('Action approval is stale or unavailable')
