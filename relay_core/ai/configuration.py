"""Permission-checked event configuration and non-sending previews."""
import json
from types import SimpleNamespace
import frappe
from relay_core.permissions import require_access
from relay_core.ai.tools import contracts, as_user

FIELDS = ('title', 'enabled', 'channel', 'business_doctype', 'ai_model', 'run_as_user',
          'handoff_owner', 'mode', 'daily_limit', 'target', 'instructions', 'reply_style',
          'search_confirmation', 'exact_trigger', 'execution_policy', 'allowed_tools', 'allowed_actions')
READ_FIELDS = {'name', 'method', 'doctype', 'fields', 'scope_field'}
SCOPE_FIELDS = {'identity_anchor', 'identity_fields', 'company_field'}


def _list(value, label):
    if not isinstance(value, str) or len(value) > 20000:
        raise ValueError(f'{label} must be bounded JSON')
    rows = json.loads(value)
    if not isinstance(rows, list) or len(rows) > 12:
        raise ValueError(f'Choose at most 12 {label}')
    return rows


def read_contracts(doc, provider=None):
    """Validate declarations only; tools.py owns runtime identity enforcement."""
    rows = _list(doc.allowed_tools or '[]', 'read references')
    for row in rows:
        if not isinstance(row, dict) or not READ_FIELDS <= row.keys() or row.keys() - READ_FIELDS - SCOPE_FIELDS:
            raise ValueError('Invalid read reference fields')
    # Reuse the existing scalar-field and direct business Link validation.
    contracts(SimpleNamespace(business_doctype=doc.business_doctype,
        allowed_tools=json.dumps([{key: row[key] for key in READ_FIELDS} for row in rows])))
    from frappe_tools.ai.tools import get_readable_meta, is_sensitive_field
    for row in rows:
        declared = SCOPE_FIELDS.intersection(row)
        if not declared and not doc.enabled:
            continue  # Legacy, disabled starter drafts can still be edited.
        if declared != SCOPE_FIELDS or row['identity_anchor'] != doc.business_doctype:
            raise ValueError('Identity must anchor to the selected business DocType')
        identities = row['identity_fields']
        if (not isinstance(identities, dict) or not identities
                or identities.keys() - {'WhatsApp', 'Telegram', 'Email'}
                or provider and provider not in identities):
            raise ValueError('Declare the authenticated provider identity field')
        anchor = get_readable_meta(row['identity_anchor'])
        for fieldname in identities.values():
            if not isinstance(fieldname, str):
                raise ValueError('Invalid provider identity field')
            field = anchor.get_field(fieldname)
            if not field or field.fieldtype != 'Data' or is_sensitive_field(fieldname):
                raise ValueError('Identity fields must be non-sensitive Data fields on the business record')
        if not isinstance(row['company_field'], str):
            raise ValueError('Invalid company field')
        field = get_readable_meta(row['doctype']).get_field(row['company_field'])
        if not field or field.fieldtype != 'Link' or field.options != 'Company':
            raise ValueError('Every read reference needs a direct Company link')
    return rows


def action_contracts(doc):
    """An event selects installed contracts, never arbitrary methods or schemas."""
    actions = _list(doc.get('allowed_actions') or '[]', 'allowed actions')
    if len(actions) > 4:
        raise ValueError('Declare at most four ordered actions')
    keys = []
    for row in actions:
        if not isinstance(row, dict) or not isinstance(row.get('action'), str):
            raise ValueError('Each allowed action needs a registered action ID')
        keys.append(row['action'])
    if len(set(keys)) != len(keys):
        raise ValueError('Allowed action IDs must be distinct')
    if doc.get('execution_policy') != 'Execute' and actions:
        raise ValueError('Ticket only events cannot declare actions')
    if not actions:
        return actions
    from relay_core.flows.actions import definitions
    from relay_core.flows.action_contracts import check_schema, ai_contract
    registered = definitions()
    for row in actions:
        action = registered.get(row['action'])
        ai_contract(action)
        if action['effect'] == 'reply':
            if set(row) != {'action'}:
                raise ValueError('Reply destinations are supplied by Core')
            continue
        if set(row) != {'action', 'doctype', 'fields'} or not isinstance(row['doctype'], str):
            raise ValueError('Draft actions need a declared DocType and fields')
        targets = action.get('targets')
        schema = targets.get(row['doctype']) if isinstance(targets, dict) else None
        check_schema(schema)
        if schema['type'] != 'object' or schema.get('additionalProperties', False) is not False:
            raise ValueError('Draft fields must use a closed object schema')
        fields = row['fields']
        if (not isinstance(fields, list) or not 1 <= len(fields) <= 20
                or any(not isinstance(field, str) for field in fields) or len(set(fields)) != len(fields)
                or not set(schema.get('required', [])).issubset(fields)
                or action['permissions'].get(row['doctype']) != 'create'):
            raise ValueError('Declare permitted draft fields and required create permission')
        meta = frappe.get_meta(row['doctype'])
        if meta.issingle or meta.istable or meta.is_virtual:
            raise ValueError('Draft targets must be ordinary documents')
        from frappe_tools.ai.tools import is_sensitive_field
        for fieldname in fields:
            field = meta.get_field(fieldname)
            if (fieldname not in schema.get('properties', {}) or not field
                    or fieldname in ('name', 'docstatus', 'owner', 'creation', 'modified', 'modified_by')
                    or field.fieldtype == 'Password' or is_sensitive_field(fieldname)):
                raise ValueError('Draft actions may only set declared business fields')
    return actions


def validate_skill(doc):
    require_access(configure=True)
    for field, limit, required in (('instructions', 8000, True), ('target', 2000, bool(doc.enabled)),
            ('reply_style', 2000, False), ('exact_trigger', 140, False)):
        value = doc.get(field) or ''
        if not isinstance(value, str) or len(value) > limit or required and not value.strip():
            raise ValueError(f'Use {1 if required else 0}–{limit} {field} characters')
    if not 1 <= int(doc.daily_limit or 0) <= 1000:
        raise ValueError('Use a daily limit of 1–1000')
    if doc.mode not in ('Shadow', 'Automatic'):
        raise ValueError('Choose Shadow or Automatic mode')
    doc.search_confirmation = doc.get('search_confirmation') or 'Always'
    doc.execution_policy = doc.get('execution_policy') or 'Ticket only'
    if doc.search_confirmation not in ('Always', 'When required'):
        raise ValueError('Choose Always or When required search confirmation')
    if doc.execution_policy not in ('Ticket only', 'Execute'):
        raise ValueError('Choose Ticket only or Execute')
    if doc.enabled or doc.run_as_user:
        with as_user(doc.run_as_user):
            require_access(manage=True)
    if doc.enabled or doc.handoff_owner:
        with as_user(doc.handoff_owner):
            require_access()
    # Retain the legacy column for recovery; never reserve a channel/business scope.
    doc.active_key = None
    channel = None
    if doc.enabled:
        if not doc.channel or not doc.ai_model:
            raise ValueError('Choose a channel and AI Model before enabling the event')
        channel = frappe.get_doc('Relay Channel', doc.channel)
        if not channel.enabled or channel.channel not in ('WhatsApp', 'Telegram', 'Email'):
            raise ValueError('Choose an enabled WhatsApp, Telegram or email channel')
        if not channel.get('company') or not frappe.db.exists('Company', channel.company):
            raise ValueError('Choose one company on the channel before enabling events')
        with as_user(channel.get('triage_owner')):
            require_access()
            frappe.get_doc('Company', channel.company).check_permission('read')
        model = frappe.get_doc('AI Model', doc.ai_model)
        if not model.enabled or not frappe.get_doc('AI Provider Account', model.account).enabled:
            raise ValueError('Choose an enabled AI Model and provider account')
    read_contracts(doc, channel.channel if channel else None)
    action_contracts(doc)


@frappe.whitelist(methods=['GET'])
def directory(after=None):
    require_access(configure=True)
    rows = frappe.get_list('Relay AI Skill', filters={'name': ['>', after]} if after else {},
        fields=['name', *FIELDS], order_by='name asc', page_length=31)
    return {'items': rows[:30], 'next': rows[29].name if len(rows) > 30 else None}


@frappe.whitelist(methods=['POST'])
def save(values, name=None):
    require_access(configure=True)
    if isinstance(values, str): values = frappe.parse_json(values)
    if not isinstance(values, dict) or set(values) - set(FIELDS):
        raise ValueError('Invalid skill fields')
    doc = frappe.get_doc('Relay AI Skill', name) if name else frappe.new_doc('Relay AI Skill')
    doc.update(values); doc.save()
    return {'name': doc.name}


@frappe.whitelist(methods=['POST'])
def test_skill(name, message):
    require_access(configure=True)
    skill = frappe.get_doc('Relay AI Skill', name); skill.check_permission('read')
    source = frappe.get_doc('Relay Message', message); source.check_permission('read')
    from relay_core.ai.service import decide
    from relay_core.automation.service import reserve_attempt
    reserve_attempt(skill)
    # Preview is structurally read-only: no run, ticket, pause or send is created.
    with as_user(skill.run_as_user):
        source.check_permission('read')
        try:
            return dict(decide(skill, source), mode='Shadow')
        except Exception:
            return {'mode': 'Shadow', 'reply': '', 'handoff': True, 'reason': 'Decision or authorization failed'}
