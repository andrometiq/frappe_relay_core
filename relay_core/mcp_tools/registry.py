"""Tool registry of the user-facing MCP: definitions, argument checks, safety rules and safe tool errors."""
import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from frappe.exceptions import DoesNotExistError, DuplicateEntryError, ValidationError
from frappe.exceptions import PermissionError as FrappePermissionError

READ, WRITE, SEND = 'R', 'W', 'S'
SAFETY = {READ: 'read', WRITE: 'internal write', SEND: 'customer send or live change'}
DOC_PARTS = (('use_when', 'Use when'), ('avoid_when', 'Do not use when'), ('returns', 'Returns'), ('errors', 'Common errors'))
NAME = re.compile(r'^[a-z]+(_[a-z]+)+$')
GENERIC_ERROR = 'Relay could not complete this request. For a send, retry with the same request_key; it never sends twice.'

STRING = {'type': 'string', 'maxLength': 4096}
NAME_FIELD = {'type': 'string', 'minLength': 1, 'maxLength': 140}
CURSOR = {'type': 'string', 'maxLength': 140}
FLAG = {'type': 'integer', 'enum': [0, 1]}
CONFIRM = {'const': True, 'description': 'Must be the literal true after the user has agreed to this exact action.'}
AFTER_MESSAGE = {'type': 'string', 'pattern': '^RELAY-MSG-[0-9]{10}$',
                 'description': 'The newest message of this chat you have read. The send is refused with "Chat changed" '
                                'when a newer message or send exists. Always pass it. A repeat of your own request_key skips this check.'}
REQUEST_KEY = {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{8,120}$',
               'description': 'Your own stable key for this one send (8-120 letters, digits, _ or -). Reuse it to retry; '
                              'the same key never sends twice.'}


def obj(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


def limit(maximum, default):
    return {'type': 'integer', 'minimum': 1, 'maximum': maximum, 'default': default}


@dataclass
class Tool:
    name: str
    safety: str
    schema: dict
    doc: dict
    handler: Callable
    listed: bool = True
    large: bool = False
    chat: bool = False
    title: str = ''

    @property
    def description(self) -> str:
        if not self.listed:
            return self.doc.get('summary', '')
        return ' '.join([self.doc['summary']] + [f'{label}: {self.doc[key]}' for key, label in DOC_PARTS])

    @property
    def annotations(self) -> dict:
        return {'title': self.title or self.name.replace('_', ' ').capitalize(), 'readOnlyHint': self.safety == READ,
                'destructiveHint': self.safety == SEND, 'idempotentHint': 'request_key' in self.schema['properties'],
                'openWorldHint': self.safety == SEND}

    def definition(self) -> dict:
        return {'name': self.name, 'description': self.description, 'inputSchema': self.schema,
                'annotations': self.annotations}


TOOLS: dict[str, Tool] = {}


def tool(name, safety, schema, doc, *, listed=True, large=False, chat=False):
    """Register a handler. Listed tools need the four doc parts, a safety class and an area_verb name.

    A chat tool sends to one chat: it takes after_message and runs under that chat's claim and reply guard."""
    def register(handler):
        if name in TOOLS:
            raise ValueError(f'Duplicate MCP tool {name}')
        if chat:
            schema['properties']['after_message'] = AFTER_MESSAGE
        TOOLS[name] = Tool(name, safety, schema, doc, handler, listed, large, chat)
        return handler
    return register


class ToolError(Exception):
    """A specific, safe message for the AI client; it is returned as an isError tool result."""


def listed() -> list[Tool]:
    return [entry for entry in TOOLS.values() if entry.listed]


def find(name) -> Tool | None:
    return TOOLS.get(name) if isinstance(name, str) else None


def check(schema, value, path='arguments'):
    """The first schema violation as a readable message, or None. Covers the JSON Schema subset the tools use."""
    if 'const' in schema and not (type(value) is type(schema['const']) and value == schema['const']):
        return f'{path} must be {json.dumps(schema["const"])}'
    if 'type' in schema and not any(is_type(value, kind) for kind in as_list(schema['type'])):
        return f'{path} must be {" or ".join(as_list(schema["type"]))}'
    if 'enum' in schema and value not in schema['enum']:
        return f'{path} must be one of {", ".join(map(str, schema["enum"]))}'
    if isinstance(value, str):
        return check_text(schema, value, path)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return check_number(schema, value, path)
    if isinstance(value, list):
        return check_list(schema, value, path)
    if isinstance(value, dict):
        return check_object(schema, value, path)
    return None


def as_list(kind):
    return kind if isinstance(kind, list) else [kind]


def is_type(value, kind):
    if kind == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, {'string': str, 'boolean': bool, 'object': dict, 'array': list, 'null': type(None)}[kind])


def check_text(schema, value, path):
    if len(value) < schema.get('minLength', 0):
        return f'{path} must have at least {schema["minLength"]} characters'
    if len(value) > schema.get('maxLength', len(value)):
        return f'{path} must have at most {schema["maxLength"]} characters'
    if 'pattern' in schema and not re.search(schema['pattern'], value):
        return f'{path} has an invalid format'
    return None


def check_number(schema, value, path):
    if value < schema.get('minimum', value) or value > schema.get('maximum', value):
        return f'{path} must be between {schema.get("minimum", "-")} and {schema.get("maximum", "-")}'
    return None


def check_list(schema, value, path):
    if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', len(value)):
        return f'{path} must have {schema.get("minItems", 0)}-{schema.get("maxItems", "any")} items'
    for index, item in enumerate(value):
        problem = check(schema.get('items', {}), item, f'{path}[{index}]')
        if problem:
            return problem
    return None


def check_object(schema, value, path):
    properties = schema.get('properties', {})
    extra = sorted(set(value) - set(properties)) if schema.get('additionalProperties') is False else []
    if extra:
        return f'{path} has unknown field {extra[0]}; allowed: {", ".join(properties) or "none"}'
    missing = [name for name in schema.get('required', []) if name not in value]
    if missing:
        return f'{path}.{missing[0]} is required'
    for name, item in value.items():
        problem = check(properties.get(name, {}), item, f'{path}.{name}')
        if problem:
            return problem
    return None


def call(name, arguments) -> dict:
    """Run one tool; argument, Core and Hub failures become isError results with a safe message."""
    entry = find(name)
    if entry is None:
        raise LookupError(f'Unknown tool {name}')
    try:
        problem = check(entry.schema, arguments)
        if problem:
            raise ToolError(problem)
        if entry.safety == READ:
            return result(entry.handler(**arguments))
        from relay_core.mcp_tools.coordination import run
        return result(run(entry, arguments))
    except Exception as error:  # Each failure maps to a safe message below; nothing raw crosses the boundary.
        return failure(error)


def result(value) -> dict:
    data = json.loads(json.dumps(value, default=str))
    structured = data if isinstance(data, dict) else {'items': data}
    return {'content': [{'type': 'text', 'text': json.dumps(structured)}], 'structuredContent': structured, 'isError': False}


def failure(error) -> dict:
    from relay_core.hub import HubError
    data = {}
    if isinstance(error, ToolError):
        message = str(error)
    elif isinstance(error, FrappePermissionError):
        message = 'Not permitted: ' + (core_message(error) or 'your Relay role cannot do this')
    elif isinstance(error, DoesNotExistError):
        message = 'Not found: ' + (core_message(error) or 'check the name or id')
    elif isinstance(error, DuplicateEntryError):
        message = 'Already exists: ' + (core_message(error) or 'use the existing record')
    elif isinstance(error, (ValidationError, ValueError)) and core_message(error):
        message = core_message(error)
    elif isinstance(error, HubError):
        from relay_core.whatsapp import failure_message
        message, data = failure_message(error), dict(error.metadata or {})
    else:
        import frappe
        frappe.log_error(title='Relay MCP tool failed')
        message = GENERIC_ERROR
    structured = {'error': message, **({'hub': data} if data else {})}
    return {'content': [{'type': 'text', 'text': message}], 'structuredContent': structured, 'isError': True}


def core_message(error) -> str:
    """Core's user-facing frappe.throw text without markup, as the portal shows it."""
    text = html.unescape(re.sub(r'<[^>]+>', '', str(error.args[0] if error.args else ''))).strip()
    return text[:500]
