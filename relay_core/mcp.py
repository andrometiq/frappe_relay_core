"""Stateless, authenticated MCP endpoint over the Core's permission-checked services.

Endpoint: /api/method/relay_core.mcp.endpoint. Frappe API-key authentication runs before this handler; the Hub
token never leaves the site's server configuration. Tools live in relay_core.mcp_tools.
"""
import json

import frappe

from relay_core.mcp_tools import guide, registry
from relay_core.permissions import require_access

PROTOCOL = '2025-06-18'
SMALL_BYTES = 1024 * 1024
LARGE_BYTES = 7 * 1024 * 1024


class ProtocolError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def initialize(params):
    from relay_core.mcp_tools.coordination import remember_client
    remember_client(params.get('clientInfo'))
    return {'protocolVersion': PROTOCOL, 'capabilities': {'tools': {'listChanged': False}, 'resources': {'listChanged': False}},
            'serverInfo': {'name': 'relay-core', 'version': '0.2.0'}, 'instructions': guide.INSTRUCTIONS}


def read_resource(params):
    try:
        return guide.read_resource(params.get('uri'))
    except LookupError as error:
        raise ProtocolError(-32002, str(error)) from None


def call_tool(params):
    name, arguments = params.get('name'), params.get('arguments', {})
    if registry.find(name) is None:
        raise ProtocolError(-32602, f'Unknown tool {name}; call tools/list')
    if not isinstance(arguments, dict):
        raise ProtocolError(-32602, 'Tool arguments must be an object')
    result = registry.call(name, arguments)
    if result['isError']:
        frappe.db.rollback()  # As the portal does when a Core call fails.
    return result


METHODS = {'initialize': initialize, 'ping': lambda params: {}, 'tools/call': call_tool, 'resources/read': read_resource,
           'tools/list': lambda params: {'tools': [entry.definition() for entry in registry.listed()]},
           'resources/list': lambda params: {'resources': guide.resources()}}


def dispatch(method, params):
    if method not in METHODS:
        raise ProtocolError(-32601, f'Unsupported method {method}')
    return METHODS[method](params)


def parsed_body():
    body = frappe.request.get_json()
    if not isinstance(body, dict) or body.get('jsonrpc') != '2.0' or not isinstance(body.get('method'), str):
        raise ProtocolError(-32600, 'Invalid JSON-RPC request')
    request_id = body.get('id')
    if isinstance(request_id, bool) or not isinstance(request_id, (str, int, type(None))):
        raise ProtocolError(-32600, 'Invalid request id')
    if not isinstance(body.get('params', {}), dict):
        raise ProtocolError(-32602, 'params must be an object')
    return body


def is_large_allowed(body):
    params = body.get('params') or {}
    entry = registry.find(params.get('name'))
    return body['method'] == 'tools/call' and entry is not None and entry.large


def respond(payload, status=200):
    from werkzeug.wrappers import Response
    if isinstance(payload, str):
        return Response(payload, status=status)
    return Response(json.dumps(payload), content_type='application/json', headers={'Cache-Control': 'no-store'})


@frappe.whitelist(methods=['GET', 'POST'], allow_guest=True)  # So a request without a token gets 401, not Frappe's 403.
def endpoint(**kwargs):
    if frappe.request.method == 'GET':
        return respond('This MCP server has no event stream', 405)
    # Frappe validates this token before dispatch; reject cookie-only browser use.
    authorization = frappe.get_request_header('Authorization') or ''
    if frappe.session.user == 'Guest' or not authorization.startswith('token '):
        return respond('API token required', 401)
    if frappe.get_request_header('Origin'):
        return respond('Browser access is not permitted', 403)
    require_access()
    length = frappe.request.content_length
    if not length or length > LARGE_BYTES:
        return respond('Request size rejected', 413)
    return answer(length)


def answer(length):
    """The JSON-RPC answer to one authenticated request of an accepted size."""
    request_id = None
    try:
        body = parsed_body()
        request_id = body.get('id')
        if length > SMALL_BYTES and not is_large_allowed(body):
            return respond('Request size rejected', 413)
        if 'id' not in body:
            # Notifications never execute business actions.
            return respond('', 202) if body['method'].startswith('notifications/') else respond('Unsupported notification', 400)
        response = {'jsonrpc': '2.0', 'id': request_id, 'result': dispatch(body['method'], body.get('params', {}))}
    except ProtocolError as error:
        response = {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': error.code, 'message': str(error)}}
    except Exception:  # No provider or site secret, or raw exception text, crosses the MCP boundary.
        frappe.db.rollback()
        frappe.log_error(title='Relay MCP request failed')
        response = {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32603, 'message': registry.GENERIC_ERROR}}
    return respond(response)
