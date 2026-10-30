"""Pure validation at the untrusted model boundary; no model-authored tools."""
import hashlib
import json
import math
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
    """A declaration can only narrow one approved capability."""
    from relay_core.ai.render import field_names
    if not isinstance(value, dict) or set(value) != {'purpose', 'reference', 'fields', 'arguments'}:
        raise ValueError('Invalid search declaration')
    if not isinstance(value['purpose'], str) or not 1 <= len(value['purpose'].strip()) <= 300:
        raise ValueError('State the search purpose')
    contract = next((row for row in references if row['key'] == value['reference']), None)
    if not contract or value['fields'] != field_names(contract, 'model'):
        raise ValueError('Search fields must match the declared reference')
    args = value['arguments']
    if not isinstance(args, dict):
        raise ValueError('Invalid search arguments')
    if contract['operation'] == 'get_doc':
        if set(args) != {'name'} or not isinstance(args['name'], str) or not 1 <= len(args['name']) <= 140:
            raise ValueError('Declare a document name')
    else:
        if set(args) - {'filters', 'limit'}:
            raise ValueError('Invalid search filters')
        limit = args.get('limit', contract['limit'])
        if type(limit) is not int or not 1 <= limit <= contract['limit']:
            raise ValueError('Invalid search limit')
        validate_filters(contract, args.get('filters', {}))
    return json.loads(canonical(value))


def validate_filters(contract, filters):
    """Model filters use only the capability's declared fields, operators and value types."""
    specs = contract['filters']
    if not isinstance(filters, dict) or set(filters) - set(specs):
        raise ValueError('Undeclared search filter')
    if any(spec.get('required') and key not in filters for key, spec in specs.items()):
        raise ValueError('A required search filter is missing')
    for key, value in filters.items():
        operator, operand = value if isinstance(value, list) and len(value) == 2 else ('=', value)
        operands = operand if operator == 'between' and isinstance(operand, list) and len(operand) == 2 else [operand]
        if (operator not in specs[key]['operators'] or (operator == 'between') != (len(operands) == 2)
                or not all(is_filter_value(specs[key], item) for item in operands) or operands[0] > operands[-1]):
            raise ValueError('Invalid search filter')
    return filters


def is_filter_value(spec, value):
    if spec['type'] == 'number':
        return type(value) in (int, float) and math.isfinite(value)
    if not isinstance(value, str) or len(value) > spec.get('max_length', 140):
        return False
    if spec['type'] == 'date':
        try:
            return date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    return value in spec.get('enum', [value])
