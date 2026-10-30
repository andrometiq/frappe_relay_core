"""Stateless, authenticated MCP facade over the Core's permission-checked services.

Endpoint: /api/method/relay_core.mcp.endpoint. Frappe API-key authentication runs
before this handler; the Hub token never leaves the site's server configuration.
This is a provisioned Frappe-token integration, not an OAuth authorization server.
"""
import json
import frappe
from relay_core.permissions import require_access
from relay_core import whatsapp
from relay_core.hub import HubError


def obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


STRING = {"type": "string"}
MESSAGE = obj({"key": STRING, "operation": {"type": "string", "enum": ["messages.send", "messages.media", "messages.react", "messages.location", "messages.contacts", "templates.send"]},
               "arguments": {"type": "object"}, "contact": STRING, "business_doctype": STRING, "business_name": STRING, "channel": STRING}, ("key", "operation"))
SEND_TO = {"number": STRING, "key": STRING, "business_doctype": STRING, "business_name": STRING, "channel": STRING}
TOOLS = [
    {"name":"relay.flows.providers","description":"List configured AI Models available for permission-checked workflow generation.","inputSchema":obj({"query":STRING,"after":STRING})},
    {"name":"relay.flows.references","description":"Search valid WhatsApp channels, execution users, or business document types for an AI-authored workflow.","inputSchema":obj({"kind":{"type":"string","enum":["channel","execution_user","business_doctype"]},"query":STRING},("kind",))},
    {"name":"relay.flows.actions","description":"List installed replay-safe business actions and their exact JSON input schemas for AI workflow authoring.","inputSchema":obj({})},
    {"name":"relay.flows.generate","description":"Generate a bounded, validated workflow draft with a configured AI Model. The draft is not saved, published, enabled, or executed.","inputSchema":obj({"requirement":STRING,"provider":STRING},("requirement","provider"))},
    {"name":"relay.flows.validate","description":"Validate a complete AI-authored workflow draft and its permission-bound runtime context without writing it.","inputSchema":obj({"name":STRING,"values":{"type":"object"}},("values",))},
    {"name":"relay.flows.list","description":"List persisted conversation flows.","inputSchema":obj({"after":STRING,"query":STRING})},
    {"name":"relay.flows.read","description":"Read a saved flow definition.","inputSchema":obj({"name":STRING},("name",))},
    {"name":"relay.flows.save","description":"Save a validated flow draft; System Manager only. Does not publish edited steps.","inputSchema":obj({"name":STRING,"values":{"type":"object"}},("values",))},
    {"name":"relay.flows.publish","description":"Publish an immutable snapshot of a saved flow and invalidate older active versions; System Manager only.","inputSchema":obj({"name":STRING},("name",))},
    {"name":"relay.flows.set_enabled","description":"Explicitly enable a published workflow or disable it immediately; System Manager only.","inputSchema":obj({"name":STRING,"enabled":{"type":"integer","enum":[0,1]}},("name","enabled"))},
    {"name":"relay.flows.runs","description":"Read permission-checked flow execution pages.","inputSchema":obj({"flow":STRING,"after":STRING},("flow",))},
    {"name":"relay.flows.cancel","description":"Cancel an active flow run in a readable conversation.","inputSchema":obj({"name":STRING},("name",))},
    {"name":"relay.flows.enqueue","description":"Queue an accessible incoming slash command or active flow input using durable replay protection.","inputSchema":obj({"message":STRING},("message",))},
    {"name":"relay.reports.preview","description":"Generate a communication report from at most 100 accessible messages on one business record.","inputSchema":obj({"doctype":STRING,"name":STRING},("doctype","name"))},
    {"name":"relay.business.messages", "description":"Read a bounded chronological page across readable Contacts linked to a configured business record; assignment and business permissions apply.", "inputSchema":obj({"doctype":STRING,"name":STRING,"before":STRING,"after":STRING,"channel":STRING,"limit":{"type":"integer","minimum":1,"maximum":100}},("doctype","name"))},
    {"name": "relay.messaging.send", "description": "Send a typed reply or set/clear a reaction against a readable verified source message. Recipient, group and topic are derived server-side. Stable request keys prevent duplicate sends.", "inputSchema": obj({"message": STRING, "kind": {"type": "string", "enum": ["text", "sticker", "reaction", "location", "contact", "photo", "video", "audio", "voice", "document"]}, "data": {"type": "object"}, "request_key": STRING}, ("message", "kind", "data", "request_key"))},
	{"name": "relay.telegram.send", "description": "Send to a verified Telegram contact/group with optional reply and topic routing. channel: the bot's Relay Channel; the chat's own bot sends.", "inputSchema": obj({"chat_id": {"type": "integer"}, "text": STRING, "reply_to": {"type": "integer"}, "message_thread_id": {"type": "integer"}, "channel": STRING}, ("chat_id", "text"))},
    {"name": "relay.telegram.groups", "description": "Manage account-scoped Telegram groups, membership, invitations, topics and pinned messages. Requires Relay Communication Manager.", "inputSchema": obj({"operation": STRING, "arguments": {"type": "object"}}, ("operation", "arguments"))},
    {"name": "relay.telegram.execute", "description": "Alias for the manager-only Telegram group operations facade.", "inputSchema": obj({"operation": STRING, "arguments": {"type": "object"}}, ("operation", "arguments"))},
	{"name": "relay.email.send", "description": "Send an email through the account-scoped Hub SMTP adapter.", "inputSchema": obj({"to": {"type": "array", "items": STRING}, "cc": {"type": "array", "items": STRING}, "bcc": {"type": "array", "items": STRING}, "subject": STRING, "body": STRING, "message":STRING,"html":STRING,"request_key":STRING,"attachment_ids":{"type":"array","items":STRING,"maxItems":8},"forward":{"type":"integer","enum":[0,1]},"channel":STRING}, ("to", "subject", "body"))},
    {"name": "relay.automation.enqueue", "description": "Queue an incoming Relay Message under its configured automation policy. May create a ticket and queue an approved reply when enabled.", "inputSchema": obj({"message": STRING}, ("message",))},
    {"name": "relay.automation.runs", "description": "Read permission-checked automation run pages.", "inputSchema": obj({"query": STRING, "before": STRING, "after": STRING})},
    {"name": "relay.automation.takeover", "description": "Pause or resume automation for an accessible contact; invalidates older queued replies.", "inputSchema": obj({"contact": STRING, "paused": {"type": "integer", "enum": [0, 1]}}, ("contact",))},
    {"name": "relay.tickets.create", "description": "Create a ticket from 1–50 readable Relay Messages.", "inputSchema": obj({"subject": STRING, "messages": {"type": "array", "items": STRING, "minItems": 1, "maxItems": 50}, "brief": STRING, "ticket_type": STRING}, ("subject", "messages"))},
    {"name": "relay.tickets.read", "description": "Read an accessible ticket and its checked message references.", "inputSchema": obj({"name": STRING}, ("name",))},
    {"name": "relay.tickets.update_status", "description": "Update an accessible ticket and queue updates for opted-in subscribers.", "inputSchema": obj({"name": STRING, "status": STRING}, ("name", "status"))},
    {"name": "relay.tickets.assign", "description": "Assign a ticket to an agent who can read its linked conversations; managers only.", "inputSchema": obj({"name": STRING, "user": STRING}, ("name",))},
    {"name": "relay.tickets.subscribe", "description": "Opt in or out of ticket updates using your own verified email or Telegram endpoint.", "inputSchema": obj({"ticket": STRING, "endpoint": STRING, "enabled": {"type":"integer","enum":[0,1]}}, ("ticket",))},
    {"name": "relay.messages.send", "description": "Queue one message using a stable request key and permission-checked business Contact.", "inputSchema": obj({"message": MESSAGE}, ("message",))},
    {"name": "relay.whatsapp.execute", "description": "Run a permitted template or account operation. Sends require a stable request key.", "inputSchema": obj({"operation": {"type": "string", "enum": sorted(whatsapp.READ | whatsapp.MANAGE | whatsapp.SEND)}, "arguments": {"type": "object"}, "contact": STRING, "business_doctype": STRING, "business_name": STRING, "request_key": STRING, "channel": STRING}, ("operation",))},
    {"name": "relay.channels.list", "description": "List the readable Relay Channels (WhatsApp numbers, Telegram bots, mailboxes) of this site. Give a send tool's channel argument one of these names; without it, a reply leaves from the number the customer wrote to last, else the default.", "inputSchema": obj({})},
    {"name": "relay.deliveries.list", "description": "Read or cancel account deliveries; requires Relay Communication Manager.", "inputSchema": obj({"after": STRING, "cancel_id": STRING})},
    {"name": "relay.contacts.list", "description": "List accessible Contacts linked to a business record.", "inputSchema": obj({"doctype": STRING, "name": STRING, "after": STRING}, ("doctype", "name"))},
    {"name": "relay.conversation.read", "description": "Read conversation pages for an accessible business Contact.", "inputSchema": obj({"contact": STRING, "business_doctype": STRING, "business_name": STRING, "before": STRING, "after": STRING}, ("contact", "business_doctype", "business_name"))},
    {"name": "relay.whatsapp.send_text", "description": "Send a WhatsApp text to a phone number inside its 24-hour reply window. An unknown number needs a manager and a business record for its new Contact. A repeated key, or the same content without a key within 10 minutes, is one message.", "inputSchema": obj(dict(SEND_TO, body=STRING), ("number", "body"))},
    {"name": "relay.whatsapp.send_media", "description": "Send a WhatsApp image, video, audio or document from an HTTPS link inside the 24-hour reply window.", "inputSchema": obj(dict(SEND_TO, media_url=STRING, media_type={"type": "string", "enum": ["image", "video", "audio", "document"]}, caption=STRING, filename=STRING), ("number", "media_url", "media_type"))},
    {"name": "relay.whatsapp.send_template", "description": "Send an approved WhatsApp template to a phone number. params: object of named values, or a list of every value in template order.", "inputSchema": obj(dict(SEND_TO, template=STRING, language=STRING, params={"type": ["object", "array"]}, header_media_url=STRING), ("number", "template", "language"))},
    {"name": "relay.whatsapp.send_messages", "description": "Queue 1-100 WhatsApp messages as one background job; each item is {type: text|media|template, number, ...that send's arguments, including channel}. Each item is checked at once and gets an accepted (Pending) or refused result. Poll relay.whatsapp.send_status with the returned batch.", "inputSchema": obj({"items": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 100}}, ("items",))},
    {"name": "relay.whatsapp.send_status", "description": "Read each item's status of your send_messages batch for 24 hours: Pending, Failed with its error, or the send status (Dispatching, Queued, Submitted, Uncertain or Rejected).", "inputSchema": obj({"batch": STRING}, ("batch",))},
    {"name": "relay.campaigns.create", "description": "Create a bulk WhatsApp campaign from up to 5000 JSON rows (column -> value), with an approved template or a text/media message; start=1 sends at once. Relay Communication Manager only.", "inputSchema": obj({"title": STRING, "rows": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 5000}, "message": {"type": "object"}, "template_name": STRING, "language": STRING, "mapping": {"type": "object"}, "start": {"type": "integer", "enum": [0, 1]}, "channel": STRING, "reply_window_hours": {"type": "integer", "minimum": 1, "maximum": 720}}, ("title", "rows"))},
    {"name": "relay.campaigns.append", "description": "Add up to 5000 more JSON rows to a Draft campaign created with rows. Relay Communication Manager only.", "inputSchema": obj({"name": STRING, "rows": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 5000}}, ("name", "rows"))},
    {"name": "relay.campaigns.read", "description": "Read a bulk campaign's status, counts, issues and first recipients. Relay Communication Manager only.", "inputSchema": obj({"name": STRING, "after": STRING, "status": STRING}, ("name",))},
]


def dispatch(method, params):
    if method == "initialize":
        if params.get("protocolVersion") != "2025-06-18":
            raise ValueError("Unsupported protocol")
        return {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "relay-core", "version": "0.1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method != "tools/call":
        raise ValueError("Unsupported method")
    name, arguments = params.get("name"), params.get("arguments", {})
    definition = next((tool for tool in TOOLS if tool["name"] == name), None)
    if definition is None or not isinstance(arguments, dict):
        raise ValueError("Unsupported tool or arguments")
    schema = definition["inputSchema"]
    if set(arguments) - set(schema["properties"]) or set(schema["required"]) - set(arguments):
        raise ValueError("Invalid tool arguments")
    handlers = {
        
        "relay.messages.send": whatsapp.send,
        "relay.whatsapp.execute": whatsapp.execute,
        "relay.deliveries.list": whatsapp.deliveries,
        "relay.contacts.list": whatsapp.business_contacts,
        "relay.conversation.read": whatsapp.conversation,
    }
    if name == 'relay.channels.list':
        from relay_core.api import channel_options
        handlers[name] = channel_options
    if name == 'relay.email.send':
        from relay_core import email
        handlers[name] = email.send
        if 'channel' in arguments:
            arguments = {**arguments, 'channel_name': arguments['channel']}
            del arguments['channel']
    if name == 'relay.reports.preview':
        from relay_core.reports import preview
        handlers[name] = preview
    if name == 'relay.business.messages':
        from relay_core.business_inbox import messages
        handlers[name] = messages
    if name.startswith('relay.flows.'):
        from relay_core.flows import service as flows
        handlers.update({'relay.flows.list':flows.directory,'relay.flows.read':flows.read,
                         'relay.flows.save':flows.save,'relay.flows.publish':flows.publish,
                         'relay.flows.validate':flows.validate_draft,
                         'relay.flows.set_enabled':flows.set_enabled,
                         'relay.flows.runs':flows.runs,'relay.flows.cancel':flows.cancel,
                         'relay.flows.enqueue':flows.enqueue})
        if name == 'relay.flows.generate':
            from relay_core.flows.authoring import draft
            handlers[name] = draft
        elif name == 'relay.flows.actions':
            from relay_core.flows.actions import catalog
            handlers[name] = catalog
        elif name == 'relay.flows.providers':
            handlers[name] = flows.providers
        elif name == 'relay.flows.references':
            handlers[name] = flows.references
    if name.startswith('relay.whatsapp.send_'):
        from relay_core import messaging_api
        handlers[name] = getattr(messaging_api, name.rsplit('.', 1)[-1])
    if name.startswith('relay.campaigns.'):
        from relay_core import bulk_campaigns
        handlers.update({'relay.campaigns.create': bulk_campaigns.create_with_rows,
                         'relay.campaigns.append': bulk_campaigns.append_rows, 'relay.campaigns.read': bulk_campaigns.read})
    if name == 'relay.messaging.send':
        from relay_core import messaging
        handlers[name] = messaging.send
    if name.startswith('relay.telegram.'):
        from relay_core import telegram
        handlers.update({'relay.telegram.send': telegram.send, 'relay.telegram.groups': telegram.groups,
                         'relay.telegram.execute': telegram.execute})
    if name.startswith("relay.tickets."):
        from relay_core import tickets
        from relay_core.ticket_notifications import subscribe
        handlers.update({"relay.tickets.create": tickets.create,
                         "relay.tickets.read": tickets.read,
                         "relay.tickets.update_status": tickets.update_status,
                         "relay.tickets.assign": tickets.assign,
                         "relay.tickets.subscribe": subscribe})
    if name.startswith("relay.automation."):
        from relay_core.automation import service
        handlers.update({"relay.automation.enqueue": service.enqueue,
                         "relay.automation.runs": service.runs,
                         "relay.automation.takeover": service.takeover})
    result = handlers[name](**arguments)
    return {"content": [{"type": "text", "text": json.dumps(result)}], "structuredContent": result, "isError": False}


@frappe.whitelist(methods=["POST"])
def endpoint(**kwargs):
    from werkzeug.wrappers import Response
    # Frappe validates this token before dispatch; reject cookie-only browser use.
    authorization = frappe.get_request_header("Authorization") or ""
    if frappe.session.user == "Guest" or not authorization.startswith("token "):
        return Response("API token required", status=401)
    if frappe.get_request_header("Origin"):
        return Response("Browser access is not permitted", status=403)
    require_access()
    if not frappe.request.content_length or frappe.request.content_length > 7 * 1024 * 1024:
        return Response("Request size rejected", status=413)
    request_id = None
    try:
        body = frappe.request.get_json()
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
            raise ValueError("Invalid request")
        request_id = body.get("id")
        if isinstance(request_id, bool) or not isinstance(request_id, (str, int, type(None))):
            raise ValueError("Invalid request ID")
        params = body.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("Invalid parameters")
        if frappe.request.content_length > 1048576:
            arguments = params.get('arguments', {})
            photo_operation = (
                params.get('name') in ('relay.telegram.groups', 'relay.telegram.execute') and arguments.get('operation') == 'photo.set'
            ) if isinstance(arguments, dict) else False
            if body['method'] != 'tools/call' or not photo_operation:
                return Response('Request size rejected', status=413)
        if "id" not in body:
            # Notifications never execute business actions.
            if body["method"] != "notifications/initialized":
                return Response("Unsupported notification", status=400)
            return Response(status=202)
        result = dispatch(body["method"], params)
        response = {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        # No provider/site secrets or raw exception text cross the MCP boundary.
        response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Request rejected; check arguments and permissions. For uncertain sends, reuse the same request keys."}}
        if isinstance(exc, HubError) and exc.metadata:
            response['error']['data'] = exc.metadata
    return Response(json.dumps(response), content_type="application/json", headers={"Cache-Control": "no-store"})
