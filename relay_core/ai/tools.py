"""Fixed read contracts: model arguments can only narrow a business scope."""
import json
import hashlib
import re
from contextlib import contextmanager
import frappe


@contextmanager
def as_user(user):
    previous = frappe.session.user
    try:
        if not user or user in ('Guest', 'Administrator') or not frappe.db.get_value('User', user, 'enabled'):
            raise ValueError('An enabled non-administrator identity is required')
        frappe.set_user(user)
        yield
    finally:
        frappe.set_user(previous)


def contracts(skill):
    value = json.loads(skill.allowed_tools or '[]')
    if not isinstance(value, list) or len(value) > 12:
        raise ValueError('Choose at most 12 read tools')
    names = set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {'name', 'method', 'doctype', 'fields', 'scope_field'}:
            raise ValueError('Each tool needs name, method, doctype, fields and scope_field')
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', row['name']) or row['name'] in names:
            raise ValueError('Tool names must be distinct lowercase identifiers')
        names.add(row['name'])
        if row['method'] not in ('get_doc', 'get_list'):
            raise ValueError('Only get_doc and get_list are allowed')
        from frappe_tools.ai.tools import get_readable_meta, is_sensitive_field
        meta = get_readable_meta(row['doctype'])
        fields = row['fields']
        if not isinstance(fields, list) or not 1 <= len(fields) <= 20:
            raise ValueError('Choose 1–20 readable fields')
        for name in fields:
            field = meta.get_field(name)
            if name != 'name' and (not field or field.fieldtype in ('Table', 'Table MultiSelect', 'Password', 'Code', 'HTML')):
                raise ValueError('Only scalar fields are allowed')
            if is_sensitive_field(name):
                raise ValueError('Sensitive fields are unavailable')
        scope = row['scope_field']
        if row['doctype'] == skill.business_doctype and scope == 'name':
            continue
        field = meta.get_field(scope)
        if not field or not (field.fieldtype == 'Link' and field.options == skill.business_doctype or field.fieldtype == 'Dynamic Link'):
            raise ValueError('Scope must link directly to the skill business type')
    return value


def schema(contract):
    if contract['method'] == 'get_doc':
        properties = {'name': {'type': 'string', 'maxLength': 140}}
        required = ['name']
    else:
        properties = {'filters': {'type': 'object', 'additionalProperties': False,
            'properties': {field: {'oneOf': [{'type': 'string', 'maxLength': 140},
                {'type': 'array', 'minItems': 2, 'maxItems': 2, 'items': {}}]} for field in contract['fields']}},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}}
        required = []
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}


class Reader:
    def __init__(self, skill, user, business):
        self.skill, self.user, self.business = skill, user, business
        self.failed = False
        self.evidence = []

    def read(self, contract, **arguments):
        try:
            with as_user(self.user):
                result = self._read(contract, arguments)
                self.evidence.append({'tool': contract['name'], 'arguments': arguments, 'digest': fingerprint(result)})
                return result
        except Exception:
            self.failed = True
            # Never expose permission errors containing inaccessible document names.
            raise ValueError('Business data is unavailable; hand off to a person') from None

    def _read(self, contract, arguments):
        from frappe_tools.ai.tools import get_readable_meta, get_readable_columns
        if contract not in contracts(self.skill) or self.business[0] != self.skill.business_doctype:
            raise ValueError('Tool is outside the skill')
        doctype, field = contract['doctype'], contract['scope_field']
        meta = get_readable_meta(doctype)
        columns = get_readable_columns(meta)
        if not set(contract['fields']).issubset(columns):
            raise ValueError('Unreadable fields')
        frappe.get_doc(*self.business).check_permission('read')
        filters = {field: self.business[1]}
        scope_meta = meta.get_field(field)
        if scope_meta and scope_meta.fieldtype == 'Dynamic Link':
            filters[scope_meta.options] = self.business[0]
        if contract['method'] == 'get_doc':
            if set(arguments) != {'name'} or not isinstance(arguments['name'], str):
                raise ValueError('A document name is required')
            # get_list enforces query hooks as well as get_doc's document hooks.
            filters['name'] = arguments['name']
            if field == 'name' and arguments['name'] != self.business[1]:
                raise ValueError('Document is outside the business')
            limit = 1
        else:
            if set(arguments) - {'filters', 'limit'}:
                raise ValueError('Unexpected arguments')
            extra = arguments.get('filters') or {}
            if not isinstance(extra, dict) or set(extra) - set(contract['fields']):
                raise ValueError('Invalid filters')
            for key, value in extra.items():
                valid = isinstance(value, str) and len(value) <= 140
                if isinstance(value, list) and len(value) == 2 and value[0] in ('=', '>=', '<=', 'between'):
                    operand = value[1]
                    valid = (isinstance(operand, str) and len(operand) <= 140 if value[0] != 'between' else
                        isinstance(operand, list) and len(operand) == 2 and all(isinstance(v, str) and len(v) <= 140 for v in operand))
                if not valid or key in filters and value != filters[key]:
                    raise ValueError('Invalid filter value')
                filters[key] = value
            limit = arguments.get('limit', 20)
            if type(limit) is not int or not 1 <= limit <= 20:
                raise ValueError('Invalid row limit')
        names = frappe.get_list(doctype, filters=filters, fields=['name'], page_length=limit, order_by='name asc')
        if not names:
            raise ValueError('No readable business data; hand off for review')
        result = []
        for row in names:
            doc = frappe.get_doc(doctype, row.name)
            doc.check_permission('read')
            if doc.get(field) != self.business[1] or scope_meta and scope_meta.fieldtype == 'Dynamic Link' and doc.get(scope_meta.options) != self.business[0]:
                raise ValueError('Document scope changed')
            doc.apply_fieldlevel_read_permissions()
            result.append({key: doc.get(key) for key in contract['fields']})
        if contract['method'] == 'get_doc':
            return result[0]
        return result


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()


def recheck(skill, user, business, evidence):
    allowed = {row['name']: row for row in contracts(skill)}
    reader = Reader(skill, user, business)
    for entry in evidence:
        result = reader.read(allowed[entry['tool']], **entry['arguments'])
        if fingerprint(result) != entry['digest']:
            raise ValueError('Business data changed before delivery')
