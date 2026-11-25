"""Real loopback HTTP into Frappe for the read-only Relay role and for users without a Relay writer role.
Hub is patched in this process; synthetic fixtures only, and nothing reaches WhatsApp.
Run from the bench sites folder: PYTHONPATH=<core>:<core>/tests CI=1 ../env/bin/python -B <this file>
"""
import ast
import json
import secrets
import threading
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch
from wsgiref.simple_server import WSGIRequestHandler, make_server
import requests
import frappe
import frappe.app
from frappe.permissions import add_permission, reset_perms
from site_labels import phone, run_label

SITE = 'relay.test'
ROOT = Path(__file__).resolve().parents[1] / 'relay_core'
frappe.init(site=SITE)
frappe.connect()
frappe.set_user('Administrator')
from relay_core import conversation_start, messaging, messaging_api, whatsapp
from relay_core.permissions import READ_ONLY, install_roles, sequential_name
assert Path(messaging_api.__file__).resolve().is_relative_to(ROOT.parent), 'Run with this checkout first on PYTHONPATH'
assert frappe.db.exists('Relay Contact Type', {'business_doctype': 'Customer', 'enabled': 1}), 'Enable the Customer business type'

# What migrate does for this change: the role, then the DocType JSON with its DocPerm rows.
install_roles()
READABLE = ('Relay Message', 'Relay Contact', 'Relay Contact Endpoint', 'Relay Channel', 'Relay Chat', 'Relay Ticket',
            'Relay Ticket Status', 'Relay Ticket Type', 'Relay Ticket Category', 'Relay Contact Type')
for doctype in READABLE:
    frappe.reload_doc('relay_core', 'doctype', frappe.scrub(doctype), force=True)
# A bot role outside Relay with DocPerm read, as on a production site. These DocTypes had no Custom DocPerm before.
BOT_ROLE, BOT_DOCTYPES = 'AI Bot', ('Relay Message', 'Relay Contact')
assert not frappe.db.exists('Custom DocPerm', {'parent': ['in', BOT_DOCTYPES]}), 'Custom DocPerm rows would be reset'
if not frappe.db.exists('Role', BOT_ROLE):
    frappe.get_doc({'doctype': 'Role', 'role_name': BOT_ROLE, 'desk_access': 0}).insert()
for doctype in BOT_DOCTYPES:
    add_permission(doctype, BOT_ROLE)
frappe.clear_cache()

stamp = run_label()
account = 'ro-' + stamp
known = phone(stamp + 'known')
TEMPLATE = {'name': 'order_ready', 'language': 'en', 'components': [{'type': 'BODY', 'text': 'Order {{1}} is ready'}]}


def user(label, roles):
    email = f'relay-ro-{label}-{stamp.lower()}@example.invalid'
    key, secret = secrets.token_hex(12), secrets.token_hex(24)
    with patch('frappe.core.doctype.user.user.throttle_user_creation'):
        frappe.get_doc({'doctype': 'User', 'email': email, 'first_name': 'Relay RO ' + label, 'send_welcome_email': 0,
                        'user_type': 'Website User', 'roles': [{'role': role} for role in roles],
                        'api_key': key, 'api_secret': secret}).insert()
    return email, {'Authorization': f'token {key}:{secret}'}


channel = frappe.get_doc({'doctype': 'Relay Channel', 'channel': 'WhatsApp', 'account': account, 'enabled': 1}).insert(
    set_name=sequential_name('channel'))
customer = frappe.get_doc({'doctype': 'Customer', 'customer_name': 'Sim RO ' + stamp, 'customer_type': 'Company',
                           'customer_group': frappe.db.get_value('Customer Group', {'is_group': 0}, 'name'),
                           'territory': frappe.db.get_value('Territory', {'is_group': 0}, 'name')}).insert()
person = frappe.get_doc({'doctype': 'Contact', 'first_name': 'Sim RO ' + stamp, 'phone_nos': [
    {'phone': '+' + known, 'is_primary_mobile_no': 1}], 'links': [{'link_doctype': 'Customer', 'link_name': customer.name}]}).insert()
relay = frappe.get_doc({'doctype': 'Relay Contact', 'contact': person.name, 'display_name': person.first_name}).insert()
endpoint = frappe.get_doc({'doctype': 'Relay Contact Endpoint', 'channel': channel.name, 'relay_contact': relay.name,
                           'endpoint': known, 'verified': 1}).insert()
incoming = frappe.get_doc({'doctype': 'Relay Message', 'relay_contact': relay.name, 'channel': channel.name,
                           'sender_endpoint': known, 'direction': 'Incoming', 'content': 'Is order 25 ready?', 'status': 'Sent',
                           'provider_id': 'wamid.ro.' + stamp, 'business_doctype': 'Customer', 'business_name': customer.name,
                           'provider_context': json.dumps({'provider': 'WhatsApp'})}).insert()
emails, headers = {}, {}
for label, roles in (('reader', [READ_ONLY]), ('bot', [BOT_ROLE]), ('manager', ['Relay Communication Manager'])):
    emails[label], headers[label] = user(label, roles)
frappe.db.commit()


class Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def application(environ, start_response):
    environ['HTTP_X_FRAPPE_SITE_NAME'] = SITE
    return frappe.app.application(environ, start_response)


server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
host = f'http://127.0.0.1:{server.server_port}'
hub = Mock()
hub.call_tool.side_effect = lambda tool, arguments: {'messages': [{'id': 'wamid.' + arguments['request_key'][:24]}]}


def request(verb, path, who, **kwargs):
    return requests.request(verb, host + path, headers=headers[who], timeout=30, **kwargs)


def ok(response, key='message'):
    assert response.status_code == 200, (response.status_code, response.text[:400])
    return response.json()[key]


def refused(response):
    assert response.status_code == 403, (response.status_code, response.text[:400])


def post_methods():
    """Every Relay method that takes POST, except the guest webhooks and the MCP endpoint, which checks each tool."""
    names = []
    for path in sorted(ROOT.rglob('*.py')):
        module = '.'.join(path.relative_to(ROOT.parent).with_suffix('').parts)
        for node in ast.parse(path.read_text()).body:
            for decorator in getattr(node, 'decorator_list', []):
                text = ast.unparse(decorator)
                if 'whitelist' in text and 'POST' in text and 'allow_guest' not in text:
                    names.append(module + '.' + node.name)
    return names


def resource_names(doctype, who, **filters):
    rows = ok(request('GET', '/api/resource/' + doctype, who, params={'filters': json.dumps(filters), 'limit_page_length': 100}), 'data')
    return {row['name'] for row in rows}


def mcp(who, method, **params):
    body = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
    return ok(request('POST', '/api/method/relay_core.mcp.endpoint', who, json=body), 'result')


def check_reads(who):
    assert resource_names('Relay Message', who, relay_contact=relay.name) == {incoming.name}
    assert ok(request('GET', '/api/resource/Relay Message/' + incoming.name, who), 'data')['content'] == 'Is order 25 ready?'
    assert resource_names('Relay Contact', who, name=relay.name) == {relay.name}
    assert resource_names('Relay Contact Endpoint', who, relay_contact=relay.name) == {endpoint.name}
    assert resource_names('Relay Channel', who, name=channel.name) == {channel.name}
    ok(request('GET', '/api/resource/Relay Ticket', who), 'data')
    ok(request('GET', '/api/resource/Relay Chat', who), 'data')
    items = ok(request('GET', '/api/method/relay_core.api.messages', who, params={'contact': relay.name}))['items']
    assert [row['name'] for row in items] == [incoming.name], items
    page = mcp(who, 'tools/call', name='messages_list', arguments={'contact': relay.name, 'limit': 5})
    assert not page['isError'] and [row['name'] for row in page['structuredContent']['items']] == [incoming.name], page


def check_no_writes(who, methods):
    for method in methods:
        for prefix in ('/api/method/', '/api/v2/method/'):
            refused(request('POST', prefix + method, who, json={}))
    refused(request('POST', '/', who, data={'cmd': 'relay_core.messaging_api.send_text', 'number': known, 'body': 'x'}))
    refused(request('PUT', '/api/resource/Relay Message/' + incoming.name, who, json={'content': 'changed'}))
    refused(request('DELETE', '/api/resource/Relay Contact/' + relay.name, who))
    refused(request('POST', '/api/resource/Relay Message', who, json={'relay_contact': relay.name, 'direction': 'Outgoing'}))
    tools = {entry['name']: entry for entry in mcp(who, 'tools/list')['tools']}
    assert tools and all(entry['annotations']['readOnlyHint'] for entry in tools.values()), sorted(tools)
    sent = mcp(who, 'tools/call', name='chat_send_text', arguments={'message': incoming.name, 'text': 'Hi',
                                                                     'request_key': 'ro-' + stamp[-8:] + 'abc'})
    assert sent['isError'] and 'can only read' in sent['structuredContent']['error'], sent
    assert hub.call_tool.call_count == 0 and not frappe.db.exists('Relay Message', {'relay_contact': relay.name, 'direction': 'Outgoing'})
    frappe.db.rollback()
    assert not frappe.db.exists('Relay Message Read', {'message': incoming.name, 'user': emails[who]}), 'A reader leaves no read trace'


def add_role(email, role):
    frappe.db.rollback()  # A fresh snapshot: the server has written the User's last activity since this one began.
    frappe.get_doc('User', email).add_roles(role)
    frappe.db.commit()


try:
    with ExitStack() as stack:
        from relay_core import settings
        original = settings.value
        hub_account = lambda key, *args, **kwargs: account if key == 'relay_hub_account' else original(key, *args, **kwargs)
        stack.enter_context(patch.object(settings, 'value', side_effect=hub_account))
        for module in (whatsapp, conversation_start, messaging, messaging_api):
            stack.enter_context(patch.object(module, 'connection_value', side_effect=hub_account))
        stack.enter_context(patch.object(whatsapp, 'client', return_value=hub))
        stack.enter_context(patch('relay_core.whatsapp_templates.definition', return_value=TEMPLATE))
        stack.enter_context(patch.object(frappe, 'enqueue'))
        stack.enter_context(patch.object(frappe, 'publish_realtime'))
        stack.enter_context(patch('relay_core.automation.queue.wake'))
        methods = post_methods()
        assert len(methods) > 100 and 'relay_core.messaging_api.send_text' in methods, len(methods)
        assert frappe.db.get_value('User', emails['reader'], 'user_type') == 'Website User'
        assert frappe.db.get_value('Role', READ_ONLY, 'desk_access') == 0
        check_reads('reader')
        check_no_writes('reader', methods)
        # DocPerm read through another role reaches no conversation and sends nothing.
        assert resource_names('Relay Message', 'bot', relay_contact=relay.name) == set()
        refused(request('GET', '/api/method/relay_core.api.messages', 'bot', params={'contact': relay.name}))
        check_no_writes('bot', methods)
        add_role(emails['bot'], READ_ONLY)
        check_reads('bot')
        check_no_writes('bot', methods)
        # Past the request gate, as server code calling Core directly, the send journal still refuses the reader.
        frappe.set_user(emails['reader'])
        try:
            messaging_api.send_text(known, 'Order 25 is ready', channel=channel.name)
            raise AssertionError('A read-only user journaled a send')
        except frappe.PermissionError as error:
            assert 'can only read' in str(error), error
        finally:
            frappe.set_user('Administrator')
            frappe.db.rollback()
        assert hub.call_tool.call_count == 0
        # A Relay writer still sends.
        sent = ok(request('POST', '/api/method/relay_core.messaging_api.send_text', 'manager', json={'number': known, 'body': 'Order 25 is ready', 'channel': channel.name}))
        assert sent['status'] == 'Submitted' and hub.call_tool.call_count == 1, sent
    print(f'PASS read-only HTTP: a Website User with {READ_ONLY} reads messages, contacts, endpoints, channels, chats and tickets '
          f'over /api/resource, the Relay read API and MCP read tools; {len(methods)} Relay POST methods (v1, v2 and cmd), '
          'REST writes and MCP send tools are refused for it and for a bot whose read DocPerm comes from another role, '
          'which also sees no conversation until it gets the read-only role; a manager still sends')
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    frappe.db.rollback()
    for doctype in BOT_DOCTYPES:
        reset_perms(doctype)
    for name in frappe.get_all('Relay Message', filters={'relay_contact': relay.name}, pluck='name'):
        frappe.delete_doc('Relay Message', name, ignore_permissions=True, force=True)
    frappe.db.delete('Relay Message Action', {'start_contact': relay.name})
    frappe.db.delete('Relay Chat', {'business_name': ['in', [relay.name, customer.name]]})
    for doctype, name in (('Relay Contact Endpoint', endpoint.name), ('Relay Contact', relay.name), ('Contact', person.name),
                          ('Customer', customer.name), ('Relay Channel', channel.name)):
        frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
    for email in emails.values():
        frappe.delete_doc('User', email, ignore_permissions=True, force=True)
    frappe.db.commit()
    frappe.destroy()
