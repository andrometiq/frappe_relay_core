# Core API and MCP reference

Paths below are Frappe methods. Ordinary methods return a Frappe `message`
envelope. The MCP endpoint returns JSON-RPC directly; the sticker route returns
binary bytes. See [authentication](authentication.md) before calling any route.

## Conversation methods

| Method | HTTP | Arguments | Result |
| --- | --- | --- | --- |
| `relay_core.api.contacts` | GET | `query='', before=None, after=None, limit=50` | `items, previous, next` |
| `relay_core.api.messages` | GET/POST | `contact, before=None, after=None, channel=None, limit=50` | `items, has_more, first, last` |
| `relay_core.api.channel_settings` | GET/POST | `name` | Channel name/provider/account/enabled only |
| `relay_core.api.update_channel` | POST | `name, account, enabled=0` | Updated channel summary; System Manager |
| `relay_core.messaging.send` | POST | `message, kind, data, request_key` | `action, status, message` |
| `relay_core.messaging.sticker` | GET | `message` | Authenticated sticker bytes |

Prefix each method with `/api/method/`. Contact pages cap at 50; message pages cap
at 100. Use either `before` or `after`, not both. Relay record references use
their full sequential names, for example `RELAY-CON-0000000001`.

Contact search uses bound database subsequence matching on display name and
record name. It does not load all records into the browser or implement typo
correction.

The typed-send `kind` is `text`, `sticker`, `reaction`, `location`, or
`contact`. Extra top-level content keys and caller-supplied routing overrides are
rejected. Nested contact-card data is normalized to supported fields.
See [message examples and statuses](messaging.md).

## WhatsApp queue and administration

| Method | Arguments |
| --- | --- |
| `relay_core.whatsapp.send` | `message` |
| `relay_core.whatsapp.enqueue` | `messages`, 1–50 items |
| `relay_core.whatsapp.execute` | `operation, arguments=None, contact=None, business_doctype=None, business_name=None` |
| `relay_core.whatsapp.deliveries` | `after='', cancel_id=None` |
| `relay_core.whatsapp.business_contacts` | `doctype, name, after=None` |
| `relay_core.whatsapp.conversation` | `contact, business_doctype, business_name, after=None, before=None` |

These methods are POST, except `business_contacts` also accepts GET.
The business-contact list supports several Contacts for one business record.

Each queue item has `key`, `operation`, `arguments`, and the business record
and Contact required by that operation. Core resolves direct-message telephone
numbers from the Contact. Reuse queue keys after uncertain admission.

```json
{
  "messages": [{
    "key": "example-order-ack-001",
    "operation": "messages.send",
    "arguments": {"body": "Your request has been received."},
    "contact": "<Contact name>",
    "business_doctype": "Customer",
    "business_name": "<Customer name>"
  }]
}
```

This example requires an enabled Customer Relay Contact Type and permission to
both records. Group administration and account-wide delivery management require
manager access. Provider operation details belong in
[Hub's reference](https://github.com/andrometiq/relay_hub/tree/develop/docs).

## MCP

POST `/api/method/relay_core.mcp.endpoint`. Supported protocol methods:
`initialize`, `notifications/initialized`, `ping`, `tools/list`,
and `tools/call`.

Initialize:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "relay-example", "version": "1"}
  }
}
```

Discover the exact argument schemas:

```json
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
```

Call a typed reply:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "relay.messaging.send",
    "arguments": {
      "message": "RELAY-MSG-0000000001",
      "kind": "text",
      "data": {"text": "We received your request."},
      "request_key": "test-reply-001"
    }
  }
}
```

| Tools | Purpose |
| --- | --- |
| `relay.messaging.send` | Typed reply/reaction bound to a readable source message |
| `relay.messages.send`, `relay.messages.bulk` | Durable WhatsApp queue admission |
| `relay.whatsapp.execute`, `relay.deliveries.list` | WhatsApp operations and delivery management |
| `relay.telegram.send`, `relay.telegram.groups`, `relay.telegram.execute` | Verified Telegram sends and manager group operations |
| `relay.email.send` | Account-level email send with CC/BCC; does not yet enforce Contact recipient lookup |
| `relay.contacts.list`, `relay.conversation.read` | Business-contact lookup and WhatsApp history |
| `relay.tickets.create`, `relay.tickets.read`, `relay.tickets.update_status` | Ticket creation/read/status; status updates do not send notifications |
| `relay.automation.enqueue`, `relay.automation.runs`, `relay.automation.takeover` | Configured automation and human control |
| `relay.flows.providers`, `relay.flows.references`, `relay.flows.actions` | Discover AI providers and permission-safe workflow inputs |
| `relay.flows.generate`, `relay.flows.validate`, `relay.flows.save` | Generate, dry-validate, and persist an AI-authored disabled draft |
| `relay.flows.publish`, `relay.flows.set_enabled` | Publish an immutable workflow version, then explicitly activate or disable it |
| `relay.flows.list`, `relay.flows.read`, `relay.flows.runs`, `relay.flows.cancel` | Inspect definitions and permission-checked executions |

Relay includes a read-only workflow viewer for definitions and execution history,
but no frontend editor. An MCP client discovers
the installed action schemas and valid runtime references, generates or authors
a bounded draft, validates it without a write, saves it disabled, publishes an
immutable version, and activates it explicitly. Generation never publishes,
enables, or executes a workflow.

`relay.telegram.execute` is an alias for the group-operation facade, not arbitrary
Telegram API execution. MCP preserves Core's role/document checks; it cannot call
arbitrary Python functions.

## Errors and limits

Unknown methods, extra arguments, invalid references, and permission failures
are rejected. MCP returns sanitized JSON-RPC errors; callers must inspect
`error` or tool error results rather than rely on HTTP status alone.
Core MCP request bodies cap at 1 MiB; supported group-photo MCP calls allow up to
7 MiB to carry bounded base64 content. These are MCP-specific limits, not a
blanket limit for every whitelisted REST method. Sticker bytes cap at 2 MiB;
signed callback bodies have their own 2 MiB limit.

A remote error or timeout may happen after provider acceptance. Follow the
[retry contract](messaging.md#retry-safely); do not turn every error into a fresh send.

## Site connection settings

| Method | Route | Access |
| --- | --- | --- |
| GET | `/api/method/relay_core.settings.connection` | Relay user/manager or System Manager |
| POST | `/api/method/relay_core.settings.save_connection` | System Manager only; session CSRF required |

Read returns `url`, `account`, `token_configured`, `callback_configured`, and
`can_configure`. Save accepts `url`, `account`, optional `token` and optional
`callback_secret`; blank secrets preserve existing values. Before saving, Core
calls Hub `account.get` and verifies the token account and canonical Frappe site
origin. Tokens therefore need `account:read`. The callback signing secret must
contain 32–512 printable characters when supplied. Values are stored in the
`Relay Settings` Single DocType, with encrypted Frappe Password fields.


## Workspace directories

- `GET relay_core.telegram.group_chats`: manager-only verified Telegram group
  directory for the configured account. `limit` is 1–50 (default 30), and `after`
  is the prior `next` endpoint cursor. Returns `items`, `next`, `configured`.
- `GET relay_core.api.business_types`: configured business DocTypes the caller can read.
- `GET relay_core.api.business_records`: `doctype` and optional `query`; returns
  up to 30 permission-filtered record names. Unconfigured DocTypes are rejected.
- `relay_core.api.messages` additionally accepts `sender_endpoint` to narrow
  history to one group/chat while preserving Contact and channel permissions.
