"""Pure validation at the untrusted model boundary; no model-authored tools."""
import hashlib
import json
from datetime import date

CATEGORIES = ('Query', 'Payment evidence', 'Support', 'Other')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def event_key(message):
    return hashlib.sha256(('relay-automation-v1:' + message).encode()).hexdigest()


def validate_decision(value, allowed_replies, *, allow_ticket, allow_report=False):
    if isinstance(value, str):
        value = json.loads(value)
    fields = {'category', 'brief', 'create_ticket', 'reply', 'handoff'}
    if not isinstance(value, dict) or set(value) not in (fields, fields | {'create_report'}):
        raise ValueError('Decision must match the action schema')
    if value['category'] not in CATEGORIES:
        raise ValueError('Unknown category')
    if not isinstance(value['brief'], str) or not 1 <= len(value['brief'].strip()) <= 1000:
        raise ValueError('Brief must contain 1–1000 characters')
    if type(value['create_ticket']) is not bool or type(value['handoff']) is not bool:
        raise ValueError('Action flags must be booleans')
    if value['create_ticket'] and not allow_ticket:
        raise ValueError('Ticket creation is not permitted')
    if value['reply'] is not None and (not isinstance(value['reply'], str) or value['reply'] not in allowed_replies):
        raise ValueError('Reply is not approved for this policy')
    if 'create_report' in value and (type(value['create_report']) is not bool or value['create_report'] and not allow_report):
        raise ValueError('Report generation is not permitted')
    return value


def action_key(message, slot):
    if slot not in ('ticket', 'reply', 'search', 'handoff', 'event_reply_0', 'event_reply_1', 'event_reply_2', 'event_reply_3'):
        raise ValueError('Unknown action slot')
    return 'relay_ai_' + event_key(message) + '_' + slot


def validate_search(value, references):
    """A declaration can only narrow one owner-declared read contract."""
    if not isinstance(value, dict) or set(value) != {'purpose', 'reference', 'fields', 'arguments'}:
        raise ValueError('Invalid search declaration')
    if not isinstance(value['purpose'], str) or not 1 <= len(value['purpose'].strip()) <= 300:
        raise ValueError('State the search purpose')
    contract = next((row for row in references if row['name'] == value['reference']), None)
    if not contract or value['fields'] != contract['fields']:
        raise ValueError('Search fields must match the declared reference')
    args = value['arguments']
    if not isinstance(args, dict):
        raise ValueError('Invalid search arguments')
    if contract['method'] == 'get_doc':
        if set(args) != {'name'} or not isinstance(args['name'], str) or not 1 <= len(args['name']) <= 140:
            raise ValueError('Declare a document name')
    else:
        if set(args) - {'filters', 'limit'} or not isinstance(args.get('filters', {}), dict):
            raise ValueError('Invalid search filters')
        if type(args.get('limit', 20)) is not int or not 1 <= args.get('limit', 20) <= 20:
            raise ValueError('Invalid search limit')
        for key, operand in args.get('filters', {}).items():
            if key not in contract['fields']:
                raise ValueError('Undeclared search field')
            valid = isinstance(operand, str) and len(operand) <= 140
            if isinstance(operand, list) and len(operand) == 2 and operand[0] in ('=', '>=', '<=', 'between'):
                bound = operand[1]
                valid = (isinstance(bound, str) and len(bound) <= 140 if operand[0] != 'between' else
                    isinstance(bound, list) and len(bound) == 2 and all(isinstance(v, str) and len(v) <= 140 for v in bound))
            if not valid:
                raise ValueError('Invalid search filter')
    if 'Ledger' in contract['doctype'] or contract['doctype'] == 'GL Entry':
        bound = args.get('filters', {}).get('posting_date')
        if not isinstance(bound, list) or len(bound) != 2 or bound[0] != 'between' or not isinstance(bound[1], list) or len(bound[1]) != 2:
            raise ValueError('Ledger searches require an explicit date range')
        start, end = bound[1]
        if date.fromisoformat(start).isoformat() != start or date.fromisoformat(end).isoformat() != end or start > end:
            raise ValueError('Invalid ledger date range')
    return json.loads(canonical(value))
