"""Permission-checked event configuration and non-sending previews."""
import json
from types import SimpleNamespace
import frappe
from relay_core import ai_features
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
    require_access('Relay AI Skill', 'write')
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
@ai_features.required
def directory(after=None):
    require_access('Relay AI Skill')
    rows = frappe.get_list('Relay AI Skill', filters={'name': ['>', after]} if after else {},
        fields=['name', *FIELDS], order_by='name asc', page_length=31)
    return {'items': rows[:30], 'next': rows[29].name if len(rows) > 30 else None}


@frappe.whitelist(methods=['POST'])
@ai_features.required
def save(values, name=None):
    require_access('Relay AI Skill', 'write')
    if isinstance(values, str): values = frappe.parse_json(values)
    if not isinstance(values, dict) or set(values) - set(FIELDS):
        raise ValueError('Invalid skill fields')
    doc = frappe.get_doc('Relay AI Skill', name) if name else frappe.new_doc('Relay AI Skill')
    doc.update(values); doc.save()
    return {'name': doc.name}


@frappe.whitelist(methods=['POST'])
@ai_features.required
def test_skill(name, message):
    require_access('Relay AI Skill', 'write')
    skill = frappe.get_doc('Relay AI Skill', name); skill.check_permission('read')
    source = frappe.get_doc('Relay Message', message); source.check_permission('read')
    import time
    from relay_core.ai.service import context, decide
    from relay_core.ai import matching
    from relay_core.automation.service import reserve_attempt
    # No run ID: the existing adapter can only declare searches and propose actions.
    try:
        user, business, scope = context(skill, source)
        candidates = matching.candidates(source)
        if not any(row.name == skill.name for row in candidates):
            candidates.append(skill)  # A disabled saved draft can be tested before activation.
        if len(candidates) > matching.MAX_CANDIDATES:
            raise ValueError('Too many events to preview')
        deadline = time.monotonic() + 20
        match = matching.select(source, candidates, None, deadline)
        result = dict(mode='Shadow', reply='', handoff=False, reason=match['reason'],
            identity_scope=dict(provider=scope['provider'], company=scope['company'], business_type=business[0],
                identity='Authenticated sender', execution_user=frappe.db.get_value('User', user, 'full_name') or 'Event operator'),
            match=dict(selected=next((row.title for row in candidates if row.name == match['selected']), None),
                method=match['method'], reason=match['reason']), reads=[], actions=[])
        if match['selected'] != skill.name:
            return dict(result, handoff=True)
        if skill.execution_policy == 'Ticket only':
            return dict(result, reason='Would raise the episode ticket only')
        reserve_attempt(skill)
        return dict(result, **{key: value for key, value in decide(skill, source, deadline=deadline).items()
                              if key in ('reply', 'handoff', 'reason', 'reads', 'search', 'actions')})
    except Exception:
        return {'mode': 'Shadow', 'reply': '', 'handoff': True, 'reason': 'Decision or authorization failed',
                'identity_scope': None, 'match': None, 'reads': [], 'actions': []}


@frappe.whitelist(methods=['GET'])
@ai_features.required
def editor_options(kind, query='', doctype=None, business_doctype=None, action=None, selected=None, skill=None):
    """Bounded, permission-checked captions; identifiers are values, never labels."""
    require_access('Relay AI Skill', 'write')
    from frappe_tools.ai.tools import get_readable_meta, get_readable_columns, is_sensitive_field
    if not isinstance(query, str) or len(query) > 80:
        raise ValueError('Use at most 80 search characters')
    selected = frappe.parse_json(selected) if isinstance(selected, str) else selected
    if selected is not None and (not isinstance(selected, list) or len(selected) > 20
            or any(not isinstance(value, str) or len(value) > 140 for value in selected)):
        raise ValueError('Invalid selected options')
    items = []
    if kind in ('field', 'identity', 'company', 'scope', 'draft_field', 'draft_doctype', 'action'):
        if kind in ('action', 'draft_doctype', 'draft_field'):
            from relay_core.flows.actions import definitions
            from relay_core.flows.action_contracts import ai_contract
            registered = {}
            for key, definition in definitions().items():
                if definition.get('ai_safe') and 'ai' in definition.get('contexts', []):
                    ai_contract(definition)
                    registered[key] = definition
            if kind == 'action':
                items = [dict(value=key, label=row['label'], description='Staff review and submit drafts' if row['effect'] == 'create_draft'
                    else 'Core supplies the destination', approval=row['approval_policy']) for key, row in registered.items()]
            else:
                definition = registered.get(action)
                if not definition or definition['effect'] != 'create_draft':
                    raise ValueError('Choose a registered draft action')
                if kind == 'draft_doctype':
                    items = [dict(value=name, label=name) for name in definition['targets']
                             if frappe.has_permission(name, 'create')]
                elif doctype not in definition['targets']:
                    raise ValueError('Choose a permitted draft DocType')
        if kind in ('field', 'identity', 'company', 'scope', 'draft_field') and doctype:
            meta = get_readable_meta(doctype)
            if not frappe.has_permission(doctype, 'create' if kind == 'draft_field' else 'read'):
                raise frappe.PermissionError('DocType is not accessible')
            readable = get_readable_columns(meta)
            schema = definition['targets'][doctype] if kind == 'draft_field' else None
            levels = meta.get_permlevel_access('write') if schema else None
            if kind == 'field' or kind == 'scope' and doctype == business_doctype:
                items.append(dict(value='name', label='Record name'))
            for field in meta.fields:
                key = field.fieldname
                if not key or is_sensitive_field(key):
                    continue
                if schema:
                    allowed = key in schema['properties'] and (field.permlevel or 0) in levels and field.fieldtype != 'Password'
                else:
                    allowed = key in readable and field.fieldtype not in ('Table', 'Table MultiSelect', 'Password', 'Code', 'HTML',
                        'Section Break', 'Column Break', 'Tab Break', 'Button', 'Fold', 'Heading')
                if kind == 'identity': allowed = allowed and field.fieldtype == 'Data'
                if kind == 'company': allowed = allowed and field.fieldtype == 'Link' and field.options == 'Company'
                if kind == 'scope':
                    discriminator = meta.get_field(field.options) if field.fieldtype == 'Dynamic Link' else None
                    allowed = allowed and (field.fieldtype == 'Link' and field.options == business_doctype
                        or discriminator and discriminator.options == 'DocType')
                if allowed:
                    items.append(dict(value=key, label=field.label or key.replace('_', ' ').title(),
                        description=schema['properties'][key]['type'] if schema else field.fieldtype,
                        required=bool(schema and key in schema.get('required', []))))
    elif kind in ('doctype', 'user', 'model', 'message'):
        target, caption = {'doctype': ('DocType', 'name'), 'user': ('User', 'full_name'),
            'model': ('AI Model', 'model_label'), 'message': ('Relay Message', 'content')}[kind]
        filters = {}
        if kind == 'doctype': filters.update(issingle=0, istable=0, is_virtual=0)
        if kind in ('user', 'model'): filters['enabled'] = 1
        if kind == 'user': filters['name'] = ['not in', ['Guest', 'Administrator']]
        if kind == 'message':
            event = frappe.get_doc('Relay AI Skill', skill); event.check_permission('read')
            filters.update(channel=event.channel, business_doctype=event.business_doctype, direction='Incoming')
        filters['name' if selected is not None else caption] = ['in', selected] if selected is not None else ['like', '%' + query + '%']
        rows = frappe.get_list(target, filters=filters, fields=list(dict.fromkeys(['name', caption])),
            order_by='modified desc' if kind == 'message' else caption + ' asc', page_length=30)
        for row in rows:
            if kind == 'doctype':
                try:
                    get_readable_meta(row.name)
                except ValueError:
                    continue
                if not frappe.has_permission(row.name, 'read'): continue
            if kind == 'message':
                source = frappe.get_doc(target, row.name); source.check_permission('read')
                source.apply_fieldlevel_read_permissions()
                label = source.get('content')
            else:
                label = row.get(caption)
            items.append(dict(value=row.name, label=' '.join(str(label or kind.title()).split())[:120]))
    else:
        raise ValueError('Unknown event picker')
    if selected is not None:
        items = [row for row in items if row['value'] in selected]
    elif query:
        items = [row for row in items if query.casefold() in row['label'].casefold()]
    return {'items': items[:30]}
