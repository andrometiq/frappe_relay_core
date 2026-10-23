"""Pure validation at the untrusted model boundary; no model-authored tools."""
import hashlib
import json

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
    if slot not in ('ticket', 'reply'):
        raise ValueError('Unknown action slot')
    return 'relay_ai_' + event_key(message) + '_' + slot
