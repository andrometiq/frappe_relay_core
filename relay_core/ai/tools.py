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
        required = {'name', 'method', 'doctype', 'fields', 'scope_field'}
        if not isinstance(row, dict) or not required <= row.keys() or row.keys() - required - {'identity_anchor', 'identity_fields', 'company_field', 'report'}:
            raise ValueError('Each tool needs name, method, doctype, fields and scope_field')
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', row['name']) or row['name'] in names:
            raise ValueError('Tool names must be distinct lowercase identifiers')
        names.add(row['name'])
        if row.get('report'):
            from relay_core.ai.reports import validate
            validate(row, skill.business_doctype)
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


class PrivacyDenied(ValueError):
    """A requested identity contradicts the authenticated business scope."""


def check_identity_arguments(contract, arguments, business, scope):
    """Reject another party before even announcing a search; reads still enforce all fixed filters."""
    fixed = {contract['scope_field']: business[1]}
    if scope:
        fixed[contract.get('company_field', 'company')] = scope['company']
        if contract['doctype'] == business[0]:
            identity = contract.get('identity_fields', {}).get(scope['provider'])
            if identity:
                fixed[identity] = scope['endpoint']
    if contract['method'] == 'get_doc':
        if contract['scope_field'] == 'name' and arguments.get('name') != business[1]:
            raise PrivacyDenied('Another business record was requested')
    else:
        for key, value in (arguments.get('filters') or {}).items():
            if key in fixed and value != fixed[key]:
                raise PrivacyDenied('Another business identity was requested')


class Reader:
    def __init__(self, skill, user, business, scope=None, *, authorize=None):
        self.skill, self.user, self.business = skill, user, business
        self.scope = dict(scope) if scope else None
        self.failed = False
        self.private = False
        self.evidence = []
        self.ledger_results = []
        self.authorize = authorize

    def read(self, contract, **arguments):
        try:
            check_identity_arguments(contract, arguments, self.business, self.scope)
            if not self.authorize:
                raise ValueError('A delivered search declaration is required')
            self.authorize(contract, arguments)
            with as_user(self.user):
                result = self._read(contract, arguments)
                self.authorize(contract, arguments)
                self.evidence.append({'tool': contract['name'], 'arguments': arguments,
                    'scope': fingerprint(self.scope), 'digest': fingerprint(result)})
                return result
        except PrivacyDenied:
            self.private = True
            raise ValueError('Business data is private') from None
        except Exception:
            self.failed = True
            # Never expose permission errors containing inaccessible document names.
            raise ValueError('Business data is unavailable; hand off to a person') from None

    def _read(self, contract, arguments):
        from frappe_tools.ai.tools import get_readable_meta, get_readable_columns
        from relay_core.ai.configuration import read_contracts
        from relay_core.business_access import scoped_document
        self.check_scope()
        if (contract not in read_contracts(self.skill, self.scope['provider'])
                or not {'identity_anchor', 'identity_fields', 'company_field'} <= contract.keys()
                or self.business[0] != self.skill.business_doctype):
            raise ValueError('Tool is outside the skill')
        doctype, field = contract['doctype'], contract['scope_field']
        meta = get_readable_meta(doctype)
        columns = get_readable_columns(meta)
        if not set(contract['fields']).issubset(columns):
            raise ValueError('Unreadable fields')
        identity_field = contract['identity_fields'][self.scope['provider']]
        anchor_filters = {identity_field: self.scope['endpoint']}
        scoped_document(*self.business, anchor_filters)
        filters = {field: self.business[1]}
        filters[contract['company_field']] = self.scope['company']
        if doctype == self.business[0]:
            filters[identity_field] = self.scope['endpoint']
        scope_meta = meta.get_field(field)
        if scope_meta and scope_meta.fieldtype == 'Dynamic Link':
            filters[scope_meta.options] = self.business[0]
        if doctype == 'GL Entry':
            filters['is_cancelled'] = 0
        fixed = dict(filters)
        if contract['method'] == 'get_doc':
            if (set(arguments) != {'name'} or not isinstance(arguments['name'], str)
                    or not 1 <= len(arguments['name']) <= 140):
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
        ledger = doctype == 'GL Entry' and contract['method'] == 'get_list' and {'debit', 'credit'}.issubset(contract['fields'])
        fields = list(contract['fields'])
        if ledger and 'company' not in fields:
            raise ValueError('Ledger company must be a declared readable field')
        names = frappe.get_list(doctype, filters=filters, fields=['name'], page_length=limit + int(ledger), order_by='name asc')
        if not names:
            raise ValueError('No readable business data; hand off for review')
        result = []
        for row in names[:limit]:
            doc = scoped_document(doctype, row.name, fixed, fields)
            result.append({key: doc.get(key) for key in fields})
        self.check_scope()
        scoped_document(*self.business, anchor_filters)
        if contract['method'] == 'get_doc':
            return result[0]
        if ledger:
            from relay_core.ai.ledger import summarize
            result = summarize(result, len(names) > limit)
            self.ledger_results.append(result)
        return result

    def check_scope(self):
        from relay_core.ai.service import context
        if not self.scope:
            raise ValueError('Authenticated read scope is required')
        message = frappe.get_doc('Relay Message', self.scope['message'])
        user, business, scope = context(self.skill, message)
        if user != self.user or business != self.business or scope != self.scope:
            raise ValueError('Sender scope changed')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()


def recheck(skill, user, business, evidence, scope=None, *, authorize=None):
    allowed = {row['name']: row for row in contracts(skill)}
    reader = Reader(skill, user, business, scope, authorize=authorize)
    reader.check_scope()
    for entry in evidence:
        if entry.get('scope') != fingerprint(scope):
            raise ValueError('Read scope changed before delivery')
        result = reader.read(allowed[entry['tool']], **entry['arguments'])
        if fingerprint(result) != entry['digest']:
            raise ValueError('Business data changed before delivery')
