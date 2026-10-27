# Authentication and permissions

Core uses Frappe authentication. A browser signs in to the Frappe site and uses
its session and CSRF token. Remote applications use a dedicated Frappe user's API
key and secret. Core does not store a separate login password or accept a Hub
token as a Frappe login.

## Roles

Relay has four roles. Each role gets its access from the DocType permissions (DocPerm) that Relay ships. Relay code checks `frappe.has_permission` on the DocType that an API reads or writes. It does not check role names.

| Role | What the user can do | Which conversations the user sees |
| --- | --- | --- |
| Relay Communication User | Works the inbox, tickets and contacts. Sends messages. | Conversations of the teams the user is a member of, conversations assigned to the user, and the user's claimed business groups. |
| Relay Communication Team User | Same work as a User. | All conversations of all teams. The user does not need to be in a team. |
| Relay Communication Manager | Same as a Team User. Also bulk campaigns, business events, WhatsApp templates, AI skills, saved replies, billing, teams and conversation assignment. | All conversations of all teams. |
| System Manager | Everything. Also settings, setup, channels, AI providers, health and activity, and all internal records. | All conversations of all teams. |
| Relay Hub Service | API user for Hub callbacks only. It can only create Relay Hub Event records. No desk access. | None. |

Business record permissions still apply to every role except Administrator. A user sees a conversation only when the user can read the Contact and at least one linked business record (for example the Customer).

The conversation rule is in one place: `relay_core/permissions.py` (`assignment_allowed` and its SQL twin `assignment_condition`). Relay Contact and Relay Message use it, and tickets use it through their messages.

The UI capability flags in `api.capabilities` come from DocType permissions: `manage` and `teams` = write on Relay Team, `billing` = read on Relay WhatsApp Billing Month, `skills` = write on Relay AI Skill, `business_events` = write on Relay Business Event Rule, `configure` = write on Relay Settings, `multi_team` = the user sees all teams.

The WhatsApp User, WhatsApp Manager and WhatsApp Multi-Channel User roles belong to frappe_whatsapp_core. Relay does not use them. The patch `use_four_relay_roles` gave their holders the matching Relay role: WhatsApp User to Relay Communication User, WhatsApp Manager to Relay Communication Manager, and WhatsApp Multi-Channel User to Relay Communication Team User. The patch does not remove roles from users.

For typed replies and sticker reads, Core checks the source Relay Message,
Relay Contact, Frappe Contact, readable business links, channel/account binding,
and verified endpoint. The recipient/group/topic is derived from the stored
source; the browser cannot override it.

## Hub access

Configure `relay_hub_url`, `relay_hub_token`, and `relay_hub_account` privately
on the site. Issue the Hub token with a grant to this account and the required
scopes. Examples include `account:read`, `messages:send`, `messages:read`,
`deliveries:read`, `templates:write`, and `calls:write`. Hub's
[reference](https://github.com/andrometiq/relay_hub/tree/develop/docs) is authoritative
for individual operation scopes.

WhatsApp bulk campaigns need `account:read`, `templates:read`, `messages:send` and `deliveries:cancel` on this token. Without `deliveries:cancel`, Hub refuses each cancellation. The campaign then stays `Cancelling`, shows the Hub reason and keeps the refused rows as queued. Hub can still send these rows. Relay retries by itself. To fix it, issue a new Hub auth key with `deliveries:cancel` under Permissions and save it in Relay Settings.

Do not distribute this token to browsers or AI clients. Those clients authenticate
to Core as their own Frappe user so Core can enforce business permissions.

## MCP authentication

POST to `/api/method/relay_core.mcp.endpoint` with:

```http
Authorization: token <frappe-api-key>:<frappe-api-secret>
Content-Type: application/json
```

This stateless JSON MCP facade supports protocol `2025-06-18`. It returns JSON-RPC
directly, without a Frappe `message` wrapper. Cookie-only callers and requests
with a browser `Origin` header are rejected. It is a provisioned-token interface;
it does not implement OAuth discovery or authorization.

Discover schemas with `tools/list`. Unknown tools and extra top-level arguments
are rejected. Notifications cannot execute actions. See the
[API reference](api-reference.md).

## Hub callbacks

Hub POSTs batches of 1–50 events to
`/api/method/relay_core.inbound.receive` using a Frappe API user with
`Relay Hub Service` or System Manager.

The request also needs `X-Relay-Timestamp` and `X-Relay-Signature`. The signature
is the lowercase hexadecimal HMAC-SHA256 of the timestamp, a literal period, and
the exact raw request body, using `relay_callback_secret`. Core accepts timestamps
within 300 seconds, bodies up to 2 MiB, and only its configured Hub account.

Identical event retries deduplicate; a reused event ID with different content is
rejected. A successful Frappe POST commits the events before acknowledgement.
Projection and automation operate on those durable records separately.

## Media access

Sticker bytes pass through Core and Hub. The browser receives a same-origin Core
URL, not a Telegram token URL or a Meta access token. Hub checks that the requested
sticker was observed in the account's inbound journal before retrieving it.
Core returns a bounded binary response with private, no-store caching and
`nosniff`.

This is a sticker-specific media path, not a general attachment or URL proxy.
