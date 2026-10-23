"""Installed business-action hooks. Handlers own permissions and idempotent side effects.

Hook definitions must declare replay_safe=True. Each handler receives a stable
idempotency_key and must reuse it across retries, including external requests.
The runtime journal avoids replay after a recorded result; the hook contract
also covers a crash between the handler's side effect and journal persistence.
"""
import hashlib
import json
import re

import frappe
from relay_core.permissions import require_access, readable_contact
from relay_core.flows.action_contracts import inputs, resolve, check_schema


def _hook_value(value, key=None):
    # Frappe merges scalar hook leaves into lists; schema arrays remain arrays.
    if isinstance(value, dict):
        return {k:_hook_value(v,k) for k,v in value.items()}
    if isinstance(value,list) and key not in ('required','enum'):
        return _hook_value(value[-1],key) if value else None
    return value


def definitions(hook="relay_flow_actions"):
    hooks = frappe.get_hooks(hook) or {}
    if not isinstance(hooks, dict):
        return {}
    result = {}
    for key, raw in hooks.items():
        if isinstance(raw, list):
            raw = raw[-1] if raw else None
        if not isinstance(key,str) or not isinstance(raw, dict) or not re.fullmatch(r'[a-z][a-z0-9_.]{0,99}', key):
            continue
        raw=_hook_value(raw)
        if raw.get('replay_safe') is not True or not isinstance(raw.get('parameters'), dict):
            continue
        method = raw.get('method', '')
        if not isinstance(method, str) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+', method):
            continue
        try:
            check_schema(raw['parameters'])
            if raw['parameters']['type']!='object':continue
        except (ValueError,TypeError):
            continue
        result[key] = dict(raw, key=key)
    return result


@frappe.whitelist(methods=['GET'])
def catalog():
    require_access(manage=True)
    return [{'key': key, 'label': row.get('label') or key, 'description': row.get('description', ''),
             'parameters': row['parameters']} for key, row in sorted(definitions().items())]


def execute(run, node, answers, key):
    require_access()
    readable_contact(run.relay_contact)
    definition = definitions().get(node['action'])
    if not definition:
        raise ValueError('Business action is not registered or replay safe')
    values = inputs(node.get('arguments', {}), definition['parameters'], answers)
    input_hash = hashlib.sha256(json.dumps([definition['method'], values], sort_keys=True).encode()).hexdigest()
    action_key = hashlib.sha256(key.encode()).hexdigest()
    with frappe.cache.lock('relay-flow-action-' + action_key, timeout=300, blocking_timeout=3):
        prior = frappe.db.get_value('Relay Flow Action', {'action_key': action_key}, ['name', 'input_hash', 'result'], as_dict=True)
        if prior:
            if prior.input_hash != input_hash:
                raise ValueError('Business action changed after execution')
            return json.loads(prior.result)
        handler = frappe.get_attr(definition['method'])
        result = handler(action_input=values, relay_contact=run.relay_contact,
                         business_doctype=run.get('business_doctype'),business_name=run.get('business_name'),
                         flow_run=run.name, idempotency_key=action_key)
        result = resolve(result, {}, references=False)
        encoded = json.dumps(result, allow_nan=False)
        if len(encoded) > 20000:
            raise ValueError('Business action result exceeds 20,000 characters')
        frappe.get_doc({'doctype': 'Relay Flow Action', 'action_key': action_key,
                        'run': run.name, 'action': node['action'], 'input_hash': input_hash,
                        'result': encoded}).insert(ignore_permissions=True)
        frappe.db.commit()
        return result
