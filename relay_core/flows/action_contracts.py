"""Bounded typed inputs for installed, explicitly registered business actions."""
import json
import math
import re


def resolve(value, answers, *, depth=0, references=True):
    if depth > 8:
        raise ValueError('Action input nesting exceeds eight levels')
    if isinstance(value, dict):
        if references and set(value) == {'var'}:
            key = value['var']
            if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', key) or key not in answers:
                raise ValueError('Action refers to an input that has not been collected')
            return resolve(answers[key], {}, depth=depth+1, references=False)
        if len(value) > 50 or any(not isinstance(k, str) or len(k) > 100 for k in value):
            raise ValueError('Action input contains too many fields')
        return {k: resolve(v, answers, depth=depth+1, references=references) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > 100:
            raise ValueError('Action list exceeds 100 values')
        return [resolve(v, answers, depth=depth+1, references=references) for v in value]
    if value is not None and type(value) not in (str, bool, int, float):
        raise ValueError('Action inputs must be JSON values')
    if isinstance(value, str) and len(value) > 10000:
        raise ValueError('Action text exceeds 10,000 characters')
    if type(value) in (int, float) and (not math.isfinite(value) or abs(value) > 1e12):
        raise ValueError('Action number is outside its supported range')
    return value


def validate(value, schema, *, depth=0):
    """Closed-by-default JSON schema subset; no coercion or executable expressions."""
    if depth > 8 or not isinstance(schema, dict):
        raise ValueError('Invalid action input schema')
    kind = schema.get('type')
    matches = {'object': isinstance(value, dict), 'array': isinstance(value, list),
               'string': isinstance(value, str), 'boolean': type(value) is bool,
               'integer': type(value) is int, 'number': type(value) in (int, float),
               'null': value is None, 'json': True}
    if kind=='json':resolve(value,{},depth=depth,references=False)
    if kind not in matches or not matches[kind]:
        raise ValueError('Action input must match type ' + str(kind))
    if 'enum' in schema and not any(type(value) is type(item) and value == item for item in schema['enum']):
        raise ValueError('Action input is not an allowed choice')
    if kind == 'object':
        properties = schema.get('properties', {})
        if any(k not in value for k in schema.get('required', [])):
            raise ValueError('A required action field is missing')
        for key, item in value.items():
            if key not in properties:
                extra = schema.get('additionalProperties', False)
                if not isinstance(extra, dict):
                    raise ValueError('Unknown action field: ' + key)
                validate(item, extra, depth=depth+1)
            else:
                validate(item, properties[key], depth=depth+1)
    elif kind == 'array':
        if not schema.get('minItems', 0) <= len(value) <= min(schema.get('maxItems', 100), 100):
            raise ValueError('Action list length is outside its allowed range')
        for item in value:
            validate(item, schema.get('items'), depth=depth+1)
    elif kind == 'string':
        if not schema.get('minLength', 0) <= len(value) <= min(schema.get('maxLength', 10000), 10000):
            raise ValueError('Action text length is outside its allowed range')
    elif kind in ('number', 'integer'):
        if not math.isfinite(value) or not schema.get('minimum', -1e12) <= value <= schema.get('maximum', 1e12):
            raise ValueError('Action number is outside its allowed range')
    return value


def inputs(value, schema, answers):
    resolved = resolve(value, answers)
    if len(json.dumps(resolved, allow_nan=False)) > 20000:
        raise ValueError('Action input exceeds 20,000 characters')
    return validate(resolved, schema)


def ai_contract(action):
    """Only reviewed Core draft/reply handlers can enter the AI registry."""
    if (not action or action.get('ai_safe') is not True
            or 'ai' not in action.get('contexts', ['flow'])
            or not action.get('method', '').startswith('relay_core.')
            or action.get('effect') not in ('reply', 'create_draft')
            or action.get('approval_policy') not in ('None', 'Required')
            or not isinstance(action.get('permissions'), dict) or not action['permissions']
            or any(permission not in ('read', 'create') for permission in action['permissions'].values())):
        raise ValueError('Only explicitly AI-safe Core reply or draft actions are allowed')
    check_schema(action.get('parameters'))
    check_schema(action.get('output'))
    if (action['parameters']['type'] != 'object'
            or action['parameters'].get('additionalProperties', False) is not False):
        raise ValueError('Action parameters must be a closed object')
    return action


def ai_inputs(value, action, declaration):
    """Model values are literal data, never flow variable references."""
    ai_contract(action)
    value = resolve(value, {}, references=False)
    if len(json.dumps(value, allow_nan=False)) > 20000:
        raise ValueError('Action input exceeds 20,000 characters')
    validate(value, action['parameters'])
    if action['effect'] == 'create_draft':
        schema = (action.get('targets') or {}).get(declaration.get('doctype'))
        check_schema(schema)
        if (schema['type'] != 'object' or schema.get('additionalProperties', False) is not False
                or not isinstance(value, dict) or set(value) - set(declaration.get('fields', []))
                or action['permissions'].get(declaration.get('doctype')) != 'create'):
            raise ValueError('Action target or fields are not declared')
        validate(value, schema)
    return value


def check_schema(schema, *, depth=0):
    """Reject unsupported contracts instead of silently ignoring their constraints."""
    if depth > 8 or not isinstance(schema, dict):
        raise ValueError('Invalid action schema')
    common = {'type', 'title', 'description', 'enum'}
    fields = {'object': {'properties', 'required', 'additionalProperties'},
              'array': {'items', 'minItems', 'maxItems'},
              'string': {'minLength', 'maxLength'},
              'number': {'minimum', 'maximum'}, 'integer': {'minimum', 'maximum'},
              'boolean': set(), 'null': set(), 'json': set()}
    kind = schema.get('type')
    if not isinstance(kind, str) or kind not in fields or set(schema) - common - fields[kind]:
        raise ValueError('Unsupported action schema fields')
    for key, limit in (('title', 140), ('description', 2000)):
        if key in schema and (not isinstance(schema[key], str) or len(schema[key]) > limit):
            raise ValueError('Invalid action field description')
    if kind == 'object':
        properties = schema.get('properties', {})
        required = schema.get('required', [])
        if not isinstance(properties, dict) or len(properties) > 50 or any(not isinstance(k, str) or not 1 <= len(k) <= 100 for k in properties):
            raise ValueError('Invalid action properties')
        if not isinstance(required, list) or any(not isinstance(k, str) or k not in properties for k in required):
            raise ValueError('Required action fields must exist')
        for nested in properties.values():
            check_schema(nested, depth=depth+1)
        extra = schema.get('additionalProperties', False)
        if extra is not False:
            check_schema(extra, depth=depth+1)
    if kind == 'array':
        check_schema(schema.get('items'), depth=depth+1)
    pairs = {'array': ('minItems', 'maxItems', 0, 100), 'string': ('minLength', 'maxLength', 0, 10000),
             'number': ('minimum', 'maximum', -1e12, 1e12), 'integer': ('minimum', 'maximum', -1e12, 1e12)}
    if kind in pairs:
        low, high, minimum, maximum = pairs[kind]
        lower, upper = schema.get(low, minimum), schema.get(high, maximum)
        for bound in (lower, upper):
            if type(bound) not in (int, float) or not math.isfinite(bound) or not minimum <= bound <= maximum:
                raise ValueError('Invalid action schema bounds')
            if kind in ('array', 'string') and type(bound) is not int:
                raise ValueError('Action length bounds must be integers')
        if lower > upper:
            raise ValueError('Action minimum exceeds maximum')
    if 'enum' in schema:
        choices = schema['enum']
        if not isinstance(choices, list) or not 1 <= len(choices) <= 100:
            raise ValueError('Invalid action choices')
        for value in choices:
            resolve(value, {}, references=False)
            validate(value, {k: v for k, v in schema.items() if k != 'enum'})
    return schema
