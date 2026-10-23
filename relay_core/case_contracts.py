"""Versionable case lifecycles and stage-specific required evidence."""
import json
import re
from relay_core.flows.action_contracts import check_schema, inputs

PRIORITIES = {'Low', 'Normal', 'High', 'Critical'}
STATES = {'open', 'active', 'waiting', 'done', 'cancelled'}


def lifecycle(value):
    if isinstance(value, str):
        if len(value) > 50000:
            raise ValueError('Case definition exceeds 50,000 characters')
        value = json.loads(value)
    if not isinstance(value, dict) or set(value) - {'fields', 'stages', 'initial_stage', 'priority'}:
        raise ValueError('Unsupported case definition fields')
    schema = value.get('fields')
    check_schema(schema)
    if schema['type'] != 'object':
        raise ValueError('Case fields must be an object schema')
    if value.get('priority', 'Normal') not in PRIORITIES:
        raise ValueError('Unsupported case priority')
    stages = value.get('stages')
    if not isinstance(stages, list) or not 1 <= len(stages) <= 30:
        raise ValueError('Choose 1–30 case stages')
    seen = set()
    for stage in stages:
        if not isinstance(stage, dict) or set(stage) - {'key', 'label', 'state', 'required_fields', 'next'}:
            raise ValueError('Unsupported case stage fields')
        key = stage.get('key')
        if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', key) or key in seen:
            raise ValueError('Choose unique case stage keys')
        seen.add(key)
        if not isinstance(stage.get('label'), str) or not 1 <= len(stage['label'].strip()) <= 140:
            raise ValueError('Case stage label is required')
        if stage.get('state') not in STATES:
            raise ValueError('Unsupported case stage state')
        required = stage.get('required_fields', [])
        if not isinstance(required, list) or any(not isinstance(k, str) or k not in schema.get('properties', {}) for k in required):
            raise ValueError('Required stage fields must be declared')
    if value.get('initial_stage') not in seen:
        raise ValueError('Initial case stage does not exist')
    for stage in stages:
        targets = stage.get('next')
        if targets is not None and (not isinstance(targets, list) or any(not isinstance(k, str) or k not in seen for k in targets)):
            raise ValueError('Case transition points to an unknown stage')
    return value


def transition(definition, target, values, current=None):
    definition = lifecycle(definition)
    stage = next((s for s in definition['stages'] if s['key'] == target), None)
    if not stage:
        raise ValueError('Unknown case stage')
    if current and current != target:
        previous = next((s for s in definition['stages'] if s['key'] == current), None)
        if not previous or ('next' in previous and target not in previous['next']):
            raise ValueError('This case transition is not allowed')
    clean = inputs(values, definition['fields'], {})
    for key in stage.get('required_fields', []):
        value = clean.get(key)
        if value is None or value == '' or isinstance(value, (list, dict)) and not value or isinstance(value, str) and not value.strip():
            raise ValueError('This stage requires ' + key)
    return clean, stage['state']
