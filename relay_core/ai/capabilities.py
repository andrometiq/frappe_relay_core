"""App-declared AI capability packs. The AI uses a pack only after an owner approves its exact hash."""
import hashlib
import json
import re
import frappe
from relay_core import ai_features
from relay_core.business_access import document_name
from relay_core.permissions import require_access

DOCTYPE = 'Relay AI Capability'
KEY = r'[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*'
LOADER_FIELDS = ('capability_key', 'app', 'kind', 'business_doctype', 'label', 'status', 'approved_version',
                 'approved_hash', 'current_hash', 'approved_by', 'approved_on', 'manifest')
UNREADABLE = ('Table', 'Table MultiSelect', 'Password', 'Code', 'HTML')
TEXT = ('Text', 'Small Text', 'Long Text', 'Text Editor')
OPERATORS = ('=', '>=', '<=', 'between')
READ = {'kind', 'version', 'label', 'business_doctype', 'doctype', 'operation', 'scope', 'fields', 'filters',
        'limit', 'empty_result', 'confirmation', 'render'}
READ_OPTIONAL = {'identity', 'order_by', 'data_notes'}
ACTION = {'kind', 'version', 'label', 'effect', 'approval_policy', 'permissions', 'parameters', 'output', 'method'}
ACTION_OPTIONAL = {'business_doctype', 'targets', 'scope_fields', 'link_checks'}


def manifests() -> dict[str, dict]:
    """Every installed app's validated packs; a key declared twice fails the whole load."""
    loaded = {}
    for app in frappe.get_installed_apps():
        for path in frappe.get_hooks('relay_ai_capabilities', app_name=app):
            if not path.startswith(app + '.'):
                raise ValueError(f'{app} must declare capabilities from its own module')
            for key, manifest in frappe.get_attr(path).items():
                if key in loaded:
                    raise ValueError(f'Capability {key} is declared by {loaded[key]["app"]} and {app}')
                if has_doctypes(manifest):
                    loaded[key] = validate_manifest(app, key, manifest)
    return loaded


def has_doctypes(manifest: dict) -> bool:
    """A pack over DocTypes this site does not have (ERPNext packs on a site without ERPNext) is not loaded."""
    doctypes = [manifest.get('doctype')] if manifest.get('kind') == 'read' else list(manifest.get('targets') or {})
    return all(isinstance(name, str) and frappe.db.exists('DocType', name) for name in doctypes)


def validate_manifest(app: str, key: str, manifest: dict) -> dict:
    """Apply the loader rules and return the manifest with its key, app and field flags filled in."""
    prefix = (frappe.get_hooks('relay_ai_capability_prefix', app_name=app) or [app])[-1]
    if not isinstance(key, str) or not re.fullmatch(KEY, key) or key.split('.')[0] != prefix:
        raise ValueError(f'Capability {key} must be named {prefix}.<name>')
    if not isinstance(manifest, dict) or manifest.get('kind') not in ('read', 'action'):
        raise ValueError(f'Capability {key} must be a read or action manifest')
    owners = {'identity': (app,), 'method': (app,), 'render': (app, 'relay_core')}
    for name, apps in owners.items():
        if name in manifest and not (isinstance(manifest[name], str)
                                     and manifest[name].split('.')[0] in apps):
            raise ValueError(f'Capability {key} {name} must belong to {app}')
    label = manifest.get('label')
    if type(manifest.get('version')) is not int or manifest['version'] < 1 or not isinstance(label, str) or not 1 <= len(label) <= 140:
        raise ValueError(f'Capability {key} needs a version and a label')
    checked = validate_read(manifest) if manifest['kind'] == 'read' else validate_action(manifest, app)
    return dict(checked, key=key, app=app)


def validate_read(manifest):
    if not READ <= set(manifest) or set(manifest) - READ - READ_OPTIONAL:
        raise ValueError('Read capability fields are invalid')
    if (manifest['operation'] not in ('get_doc', 'get_list') or manifest['empty_result'] not in ('fixed_text', 'handoff')
            or manifest['confirmation'] not in ('Always', 'When required')
            or type(manifest['limit']) is not int or not 1 <= manifest['limit'] <= 20):
        raise ValueError('Read capability operation, limit or result rule is invalid')
    from frappe_tools.ai.tools import get_readable_meta
    meta = get_readable_meta(manifest['doctype'])
    rows = manifest['fields']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
        raise ValueError('Declare 1–20 capability fields')
    fields = [validate_field(meta, row) for row in rows]
    if len({row['name'] for row in fields}) != len(fields):
        raise ValueError('Capability fields must be distinct')
    checked = dict(manifest, fields=fields, order_by=manifest.get('order_by', 'name asc'))
    validate_scope(checked, meta)
    validate_filter_specs(checked)
    names = [row['name'] for row in fields]
    for part in checked['order_by'].split(','):
        match = re.fullmatch(r'\s*([a-z_][a-z0-9_]*) (asc|desc)\s*', part)
        if not match or match[1] not in names:
            raise ValueError('Order by declared fields only')
    return checked


def validate_field(meta, row):
    """Text fields never reach the model; they may reach the customer when the pack says so."""
    from frappe_tools.ai.tools import is_sensitive_field
    if not isinstance(row, dict) or set(row) - {'name', 'model', 'customer'} or not isinstance(row.get('name'), str):
        raise ValueError('Each capability field needs a name and model and customer flags')
    flags = {flag: row.get(flag, False) for flag in ('model', 'customer')}
    field = meta.get_field(row['name'])
    if (row['name'] != 'name' and (not field or field.fieldtype in UNREADABLE)) or is_sensitive_field(row['name']):
        raise ValueError(f'Field {row["name"]} is not a readable scalar field')
    if any(type(value) is not bool for value in flags.values()) or not any(flags.values()):
        raise ValueError(f'Field {row["name"]} must be shown to the model or the customer')
    if field and field.fieldtype in TEXT and flags['model']:
        raise ValueError(f'Text field {row["name"]} cannot be shown to the model')
    return dict(name=row['name'], **flags)


def validate_scope(manifest, meta):
    """The business link and the company rule are fixed by the pack, never by the model."""
    scope = manifest['scope']
    if not isinstance(scope, dict) or not {'business_field', 'company'} <= set(scope) or set(scope) - {'business_field', 'company', 'fixed'}:
        raise ValueError('Capability scope needs business_field and company')
    fixed = scope.get('fixed', {})
    if not isinstance(fixed, dict) or any(key != 'docstatus' and not meta.get_field(key) or type(value) not in (str, int)
                                          for key, value in fixed.items()):
        raise ValueError('Fixed scope filters must be scalar values on real fields')
    business = scope['business_field']
    field = meta.get_field(business) if isinstance(business, str) else None
    if business == 'name':
        valid = manifest['doctype'] == manifest['business_doctype']
    elif field and field.fieldtype == 'Dynamic Link':
        valid = fixed.get(field.options) == manifest['business_doctype']
    else:
        valid = bool(field) and field.fieldtype == 'Link' and field.options == manifest['business_doctype']
    if not valid:
        raise ValueError('Scope must link directly to the capability business type')
    company = scope['company']
    kind = company.get('kind') if isinstance(company, dict) else None
    if kind == 'company_field':
        field = meta.get_field(company.get('field')) if set(company) == {'kind', 'field'} else None
        if not field or field.fieldtype != 'Link' or field.options != 'Company':
            raise ValueError('The company field must link to Company')
    elif kind != 'company_neutral' or set(company) != {'kind'}:
        raise ValueError('Use a company field or a company-neutral business type')


def validate_filter_specs(manifest):
    model = {row['name'] for row in manifest['fields'] if row['model']}
    filters = manifest['filters']
    if not isinstance(filters, dict) or set(filters) - model:
        raise ValueError('Filters must be model fields')
    for spec in filters.values():
        if not is_filter_spec(spec):
            raise ValueError('Invalid capability filter')


def is_filter_spec(spec):
    if not isinstance(spec, dict) or set(spec) - {'type', 'operators', 'required', 'enum', 'max_length'}:
        return False
    operators, enum, length = spec.get('operators'), spec.get('enum', ['']), spec.get('max_length', 140)
    return (spec.get('type') in ('date', 'string', 'number') and type(spec.get('required', False)) is bool
            and isinstance(operators, list) and bool(operators) and not set(operators) - set(OPERATORS)
            and type(length) is int and 1 <= length <= 140
            and isinstance(enum, list) and 1 <= len(enum) <= 100 and all(isinstance(value, str) for value in enum))


def validate_action(manifest, app):
    """The fields of an AI action registration; ai_contract keeps drafts behind staff approval."""
    from relay_core.flows.action_contracts import ai_contract
    if not ACTION <= set(manifest) or set(manifest) - ACTION - ACTION_OPTIONAL:
        raise ValueError('Action capability fields are invalid')
    ai_contract(dict(manifest, ai_safe=True, contexts=['ai'], app=app))
    targets = manifest.get('targets') or {}
    for doctype, fields in (manifest.get('link_checks') or {}).items():
        properties = targets.get(doctype, {}).get('properties', {})
        if not isinstance(fields, list) or any(field not in properties for field in fields):
            raise ValueError('Link checks must name target fields')
    return manifest


def manifest_hash(manifest: dict) -> str:
    from relay_core.automation.contracts import canonical
    return hashlib.sha256(canonical(manifest).encode()).hexdigest()


def sync():
    """after_migrate: one row per declared pack. A new or changed pack waits for approval; Core packs are
    reviewed with Core and approve themselves."""
    loaded = manifests()
    for key, manifest in loaded.items():
        digest = manifest_hash(manifest)
        exists = frappe.db.exists(DOCTYPE, key)
        doc = frappe.get_doc(DOCTYPE, key) if exists else frappe.new_doc(DOCTYPE)
        doc.update(dict(capability_key=key, app=manifest['app'], kind=manifest['kind'].title(),
            business_doctype=manifest.get('business_doctype'), label=manifest['label'],
            manifest=json.dumps(manifest, sort_keys=True), current_hash=digest))
        doc.status = ('Approved' if doc.approved_hash == digest else 'Changed' if doc.approved_hash
                      else 'Pending approval')
        if manifest['app'] == 'relay_core' and doc.status != 'Approved':
            mark_approved(doc, 'Administrator')
        doc.flags.from_loader = True
        if exists:
            doc.save(ignore_permissions=True)
        else:
            doc.insert(ignore_permissions=True)
    for name in frappe.get_all(DOCTYPE, filters={'name': ['not in', list(loaded)], 'status': ['!=', 'Missing']}, pluck='name'):
        frappe.db.set_value(DOCTYPE, name, 'status', 'Missing')


def mark_approved(doc, user):
    from frappe.utils import now_datetime
    doc.update(dict(status='Approved', approved_version=json.loads(doc.manifest)['version'],
        approved_hash=doc.current_hash, approved_by=user, approved_on=now_datetime()))


@frappe.whitelist(methods=['POST'])
@ai_features.required
def approve(name):
    """A manager approves the exact loaded manifest."""
    document_name(name)
    require_access(DOCTYPE, 'write')
    require_access(manage=True)
    doc = frappe.get_doc(DOCTYPE, name)
    doc.check_permission('write')
    if doc.status == 'Missing':
        raise ValueError('An uninstalled capability cannot be approved')
    mark_approved(doc, frappe.session.user)
    doc.flags.from_loader = True
    doc.save()
    return {'name': doc.name, 'status': doc.status, 'approved_hash': doc.approved_hash}


def active(key: str) -> dict:
    """The approved manifest of an enabled pack from Core or a trusted adapter app."""
    row = frappe.db.get_value(DOCTYPE, key, ['app', 'enabled', 'status', 'approved_hash', 'current_hash', 'manifest'],
                              as_dict=True) if isinstance(key, str) else None
    if (not row or not row.enabled or row.status != 'Approved' or row.approved_hash != row.current_hash
            or row.app != 'relay_core' and row.app not in trusted_apps()):
        raise ValueError('Capability is not approved')
    return json.loads(row.manifest)


def trusted_apps() -> set[str]:
    value = frappe.db.get_single_value('Relay Settings', 'trusted_adapter_apps') or ''
    return {line.strip() for line in value.splitlines() if line.strip()}


def packs(kind: str, **filters) -> list[dict]:
    """Active manifests of one kind ('Read' or 'Action'), in key order."""
    keys = frappe.get_all(DOCTYPE, filters=dict(filters, kind=kind, enabled=1, status='Approved'),
                          pluck='name', order_by='name asc')
    active_packs = []
    for key in keys:
        try:
            active_packs.append(active(key))
        except ValueError:
            continue
    return active_packs


def options(business_doctype: str) -> list[dict]:
    return [dict(value=row['key'], label=row['label'], description=row.get('data_notes', ''))
            for row in packs('Read', business_doctype=business_doctype)]
