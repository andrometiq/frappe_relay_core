"""The first relay.* tool names. They keep working for existing clients but are not listed; new clients use the area tools."""
import importlib

from relay_core.mcp_tools.registry import READ, WRITE, tool

STRING = {"type": "string"}
OPERATIONS = sorted({'account.profile', 'account.metadata', 'capabilities', 'templates.list', 'templates.media_upload',
                     'templates.delete', 'templates.create', 'templates.update', 'messages.media', 'messages.send', 'messages.react',
                     'messages.location', 'messages.contacts', 'templates.send'})
READS = {'relay.flows.providers', 'relay.flows.references', 'relay.flows.actions', 'relay.flows.generate', 'relay.flows.validate',
         'relay.flows.list', 'relay.flows.read', 'relay.flows.runs', 'relay.reports.preview', 'relay.business.messages',
         'relay.automation.runs', 'relay.tickets.read', 'relay.channels.list', 'relay.contacts.list', 'relay.conversation.read',
         'relay.whatsapp.send_status', 'relay.campaigns.read'}
LARGE = {'relay.telegram.groups', 'relay.telegram.execute'}  # Group photo.set carries image bytes.
RENAMED = {'relay.email.send': {'channel': 'channel_name'}}


def obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


MESSAGE = obj({"key": STRING, "operation": {"type": "string", "enum": ["messages.send", "messages.media", "messages.react", "messages.location", "messages.contacts", "templates.send"]},
               "arguments": {"type": "object"}, "contact": STRING, "business_doctype": STRING, "business_name": STRING, "channel": STRING}, ("key", "operation"))
SEND_TO = {"number": STRING, "key": STRING, "business_doctype": STRING, "business_name": STRING, "channel": STRING}
DEFINITIONS = [
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
    {"name": "relay.tickets.create", "description": "Create a ticket from 1-50 readable Relay Messages.", "inputSchema": obj({"subject": STRING, "messages": {"type": "array", "items": STRING, "minItems": 1, "maxItems": 50}, "brief": STRING, "ticket_type": STRING}, ("subject", "messages"))},
    {"name": "relay.tickets.read", "description": "Read an accessible ticket and its checked message references.", "inputSchema": obj({"name": STRING}, ("name",))},
    {"name": "relay.tickets.update_status", "description": "Update an accessible ticket and queue updates for opted-in subscribers.", "inputSchema": obj({"name": STRING, "status": STRING}, ("name", "status"))},
    {"name": "relay.tickets.assign", "description": "Assign a ticket to an agent who can read its linked conversations; managers only.", "inputSchema": obj({"name": STRING, "user": STRING}, ("name",))},
    {"name": "relay.tickets.subscribe", "description": "Opt in or out of ticket updates using your own verified email or Telegram endpoint.", "inputSchema": obj({"ticket": STRING, "endpoint": STRING, "enabled": {"type":"integer","enum":[0,1]}}, ("ticket",))},
    {"name": "relay.messages.send", "description": "Queue one message using a stable request key and permission-checked business Contact.", "inputSchema": obj({"message": MESSAGE}, ("message",))},
    {"name": "relay.whatsapp.execute", "description": "Run a permitted template or account operation. Sends require a stable request key.", "inputSchema": obj({"operation": {"type": "string", "enum": OPERATIONS}, "arguments": {"type": "object"}, "contact": STRING, "business_doctype": STRING, "business_name": STRING, "request_key": STRING, "channel": STRING}, ("operation",))},
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

TARGETS = {
    'relay.flows.providers': ('relay_core.flows.service', 'providers'),
    'relay.flows.references': ('relay_core.flows.service', 'references'),
    'relay.flows.actions': ('relay_core.flows.actions', 'catalog'),
    'relay.flows.generate': ('relay_core.flows.authoring', 'draft'),
    'relay.flows.validate': ('relay_core.flows.service', 'validate_draft'),
    'relay.flows.list': ('relay_core.flows.service', 'directory'),
    'relay.flows.read': ('relay_core.flows.service', 'read'),
    'relay.flows.save': ('relay_core.flows.service', 'save'),
    'relay.flows.publish': ('relay_core.flows.service', 'publish'),
    'relay.flows.set_enabled': ('relay_core.flows.service', 'set_enabled'),
    'relay.flows.runs': ('relay_core.flows.service', 'runs'),
    'relay.flows.cancel': ('relay_core.flows.service', 'cancel'),
    'relay.flows.enqueue': ('relay_core.flows.service', 'enqueue'),
    'relay.reports.preview': ('relay_core.reports', 'preview'),
    'relay.business.messages': ('relay_core.business_inbox', 'messages'),
    'relay.messaging.send': ('relay_core.messaging', 'send'),
    'relay.telegram.send': ('relay_core.telegram', 'send'),
    'relay.telegram.groups': ('relay_core.telegram', 'groups'),
    'relay.telegram.execute': ('relay_core.telegram', 'execute'),
    'relay.email.send': ('relay_core.email', 'send'),
    'relay.automation.enqueue': ('relay_core.automation.service', 'enqueue'),
    'relay.automation.runs': ('relay_core.automation.service', 'runs'),
    'relay.automation.takeover': ('relay_core.automation.service', 'takeover'),
    'relay.tickets.create': ('relay_core.tickets', 'create'),
    'relay.tickets.read': ('relay_core.tickets', 'read'),
    'relay.tickets.update_status': ('relay_core.tickets', 'update_status'),
    'relay.tickets.assign': ('relay_core.tickets', 'assign'),
    'relay.tickets.subscribe': ('relay_core.ticket_notifications', 'subscribe'),
    'relay.messages.send': ('relay_core.whatsapp', 'send'),
    'relay.whatsapp.execute': ('relay_core.whatsapp', 'execute'),
    'relay.channels.list': ('relay_core.api', 'channel_options'),
    'relay.deliveries.list': ('relay_core.whatsapp', 'deliveries'),
    'relay.contacts.list': ('relay_core.whatsapp', 'business_contacts'),
    'relay.conversation.read': ('relay_core.whatsapp', 'conversation'),
    'relay.whatsapp.send_text': ('relay_core.messaging_api', 'send_text'),
    'relay.whatsapp.send_media': ('relay_core.messaging_api', 'send_media'),
    'relay.whatsapp.send_template': ('relay_core.messaging_api', 'send_template'),
    'relay.whatsapp.send_messages': ('relay_core.messaging_api', 'send_messages'),
    'relay.whatsapp.send_status': ('relay_core.messaging_api', 'send_status'),
    'relay.campaigns.create': ('relay_core.bulk_campaigns', 'create_with_rows'),
    'relay.campaigns.append': ('relay_core.bulk_campaigns', 'append_rows'),
    'relay.campaigns.read': ('relay_core.bulk_campaigns', 'read'),
}


def handler(name):
    module, function = TARGETS[name]

    def call(**arguments):
        renamed = {RENAMED.get(name, {}).get(key, key): value for key, value in arguments.items()}
        return getattr(importlib.import_module(module), function)(**renamed)
    return call


for definition in DEFINITIONS:
    tool(definition['name'], READ if definition['name'] in READS else WRITE, definition['inputSchema'],
         {'summary': definition['description']}, listed=False, large=definition['name'] in LARGE)(handler(definition['name']))
