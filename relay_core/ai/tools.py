"""Capability reads: model arguments can only narrow a business scope."""
import json
import hashlib
from contextlib import contextmanager
import frappe

# Staff notes, desk comments, ticket internals and run journals. No customer read or knowledge source copies them.
STAFF_ONLY = frozenset({'Relay Internal Comment', 'Comment', 'Communication', 'ToDo', 'Version', 'Relay Ticket',
                        'Relay Ticket Message', 'Relay Automation Run', 'Relay Flow Action'})


def check_customer_doctype(doctype: str) -> None:
    """Refuse a customer read of a staff-only DocType."""
    if doctype in STAFF_ONLY:
        raise ValueError(f'{doctype} holds staff-only data')


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
    """The skill's approved read manifests for its business type; selected code tools are skipped here."""
    rows = json.loads(skill.allowed_tools or '[]')
    if not isinstance(rows, list) or len(rows) > 12:
        raise ValueError('Choose at most 12 read capabilities')
    if any(not isinstance(row, dict) or set(row) != {'capability'} or not isinstance(row['capability'], str)
           for row in rows):
        raise ValueError('Each read reference names one capability')
    keys = [row['capability'] for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError('Read capabilities must be distinct')
    from relay_core.ai.capabilities import active
    # Code tools share the selection; registry.tool.offered gates them.
    manifests = [manifest for manifest in map(active, keys) if manifest['kind'] != 'tool']
    if any(row['kind'] != 'read' or row['business_doctype'] != skill.business_doctype for row in manifests):
        raise ValueError('Choose read capabilities for the skill business type')
    for row in manifests:
        check_customer_doctype(row['doctype'])
    return manifests


class PrivacyDenied(ValueError):
    """A requested identity contradicts the authenticated business scope."""


def fixed_filters(contract, business, company):
    """The business, company and pack filters a model can never change."""
    rule = contract['scope']
    filters = dict(rule.get('fixed', {}), **{rule['business_field']: business[1]})
    if rule['company']['kind'] == 'company_field':
        filters[rule['company']['field']] = company
    return filters


def own_record_arguments(contract, arguments, business):
    """The model never sees the sender's record name, so a read of that record takes it from the scope."""
    if (contract['operation'] == 'get_doc' and contract['scope']['business_field'] == 'name'
            and isinstance(arguments, dict) and 'name' not in arguments):
        # Models send the list shape (empty filters, a limit) for a one-record read.
        if set(arguments) <= {'filters', 'limit'} and not arguments.get('filters'):
            return {'name': business[1]}
        return dict(arguments, name=business[1])
    return arguments


def check_identity_arguments(contract, arguments, business, scope):
    """Reject another party before even announcing a search; reads still enforce all fixed filters."""
    if not isinstance(arguments, dict):
        return
    if contract['operation'] == 'get_doc':
        if contract['scope']['business_field'] == 'name' and arguments.get('name') != business[1]:
            raise PrivacyDenied('Another business record was requested')
        return
    fixed = fixed_filters(contract, business, scope and scope['company'])
    filters = arguments.get('filters')
    for key, value in (filters.items() if isinstance(filters, dict) else ()):
        if key in fixed and value not in (fixed[key], ['=', fixed[key]]):
            raise PrivacyDenied('Another business identity was requested')


def company_neutral(doctype):
    """A pack without a company field reads only listed types on a site without Company or with one Company."""
    from relay_core.permissions import has_companies
    listed = frappe.db.get_single_value('Relay Settings', 'company_neutral_types') or ''
    if doctype not in {line.strip() for line in listed.splitlines()} or has_companies() and frappe.db.count('Company') != 1:
        raise ValueError('This business type is not company neutral')


def is_company_scoped(skill) -> bool:
    """On a site with Company, a skill needs the channel company unless all its reads are company neutral and it
    declares no draft action."""
    from relay_core.permissions import has_companies
    if not has_companies():
        return False
    kinds = {row['scope']['company']['kind'] for row in contracts(skill)}
    actions = json.loads(skill.get('allowed_actions') or '[]')
    return kinds != {'company_neutral'} or any(not isinstance(row, dict) or row.get('action') != 'reply' for row in actions)


def query(contract, arguments, fixed):
    """Model arguments can only narrow the fixed scope, inside the pack's filters and limit."""
    from relay_core.automation.contracts import validate_filters
    filters = dict(fixed)
    if contract['operation'] == 'get_doc':
        if (set(arguments) != {'name'} or not isinstance(arguments['name'], str)
                or not 1 <= len(arguments['name']) <= 140):
            raise ValueError('A document name is required')
        if filters.get('name', arguments['name']) != arguments['name']:
            raise ValueError('Document is outside the business')
        return dict(filters, name=arguments['name']), 1
    if set(arguments) - {'filters', 'limit'}:
        raise ValueError('Unexpected arguments')
    for key, value in validate_filters(contract, arguments.get('filters') or {}).items():
        if key in filters and value != filters[key]:
            raise ValueError('Invalid filter value')
        filters[key] = value
    limit = arguments.get('limit', contract['limit'])
    if type(limit) is not int or not 1 <= limit <= contract['limit']:
        raise ValueError('Invalid row limit')
    return filters, limit


class Reader:
    def __init__(self, skill, user, business, scope=None, *, authorize=None):
        self.skill, self.user, self.business = skill, user, business
        self.scope = dict(scope) if scope else None
        self.failed = False
        self.private = False
        self.evidence = []
        self.results = {}
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
                self.evidence.append({'tool': contract['key'], 'arguments': arguments,
                    'scope': fingerprint(self.scope), 'digest': fingerprint(self.results[contract['key']])})
                return result
        except PrivacyDenied:
            self.private = True
            raise ValueError('Business data is private') from None
        except Exception:
            self.failed = True
            # Never expose permission errors containing inaccessible document names.
            raise ValueError('Business data is unavailable; hand off to a person') from None

    def _read(self, contract, arguments):
        """Full rows stay in results for the renderer; the model sees only model fields."""
        from frappe_tools.ai.tools import get_readable_meta, get_readable_columns
        from relay_core.ai.identity import validate
        from relay_core.ai.render import visible_rows
        from relay_core.business_access import scoped_document
        self.check_scope()
        if contract not in contracts(self.skill) or self.business[0] != self.skill.business_doctype:
            raise ValueError('Tool is outside the skill')
        validate(contract, self.scope, self.business)
        doctype = contract['doctype']
        fields = [row['name'] for row in contract['fields'] if row['model'] or row['customer']]
        if not set(fields).issubset(get_readable_columns(get_readable_meta(doctype))):
            raise ValueError('Unreadable fields')
        if contract['scope']['company']['kind'] == 'company_neutral':
            company_neutral(doctype)
        fixed = fixed_filters(contract, self.business, self.scope['company'])
        filters, limit = query(contract, arguments, fixed)
        names = frappe.get_list(doctype, filters=filters, fields=['name'], page_length=limit + 1,
                                order_by=contract['order_by'])
        if not names and (contract['operation'] == 'get_doc' or contract['empty_result'] == 'handoff'):
            raise ValueError('No readable business data; hand off for review')
        rows = []
        for row in names[:limit]:
            doc = scoped_document(doctype, row.name, fixed, fields)
            rows.append({key: doc.get(key) for key in fields})
        self.check_scope()
        validate(contract, self.scope, self.business)
        self.results[contract['key']] = dict(rows=rows, truncated=len(names) > limit)
        model = visible_rows(contract, rows, 'model')
        if contract['operation'] == 'get_doc':
            return model[0]
        return dict(rows=model, truncated=len(names) > limit)

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
    allowed = {row['key']: row for row in contracts(skill)}
    reader = Reader(skill, user, business, scope, authorize=authorize)
    reader.check_scope()
    for entry in evidence:
        if entry.get('scope') != fingerprint(scope):
            raise ValueError('Read scope changed before delivery')
        reader.read(allowed[entry['tool']], **entry['arguments'])
        if fingerprint(reader.results[entry['tool']]) != entry['digest']:
            raise ValueError('Business data changed before delivery')
