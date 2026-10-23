# Current support and limitations

Reviewed against the local `develop` working tree on 2026-09-23.
Local changes may not yet be pushed or deployed. Use the
[documentation index](README.md) for current setup instructions; older plans are
design records rather than promises of implemented behavior.

## Implemented paths

- Frappe-native users, authentication, Relay roles, DocTypes, naming series,
  business Contact links, and configured contact types.
- Hub MCP client with account-scoped provider operations; Hub owns provider
  credentials and delivery.
- Durable incoming-event storage, verified endpoint projection, separate group,
  topic and private-chat provenance, and deduplication.
- WhatsApp and Telegram typed replies, stickers, reactions, static locations, and
  contact cards within the [provider support matrix](messaging.md#provider-support).
- Ticket creation from messages, approved canned-reply automation, Shadow mode,
  human takeover, durable run/outbox state, and bounded model calls.
- Database-paged contacts/messages, reusable Frappe-style fields, connected
  Messages/Automation/WhatsApp workspaces, and separate design-preview screens.

Automated tests cover these implementations with synthetic data and local
provider fixtures. The [testing guide](testing.md) explains what is real in each
layer and where the current report is stored.

## Current UI boundaries

The installed `/relay` workspace uses the hosting site’s standard Frappe login
and same-origin APIs. Build it with `npm run build:site` before opening it.
The separate `npm run build` artifact remains a design preview. The sample Inbox, dashboard, folders,
team forms, and flow diagram are not a completed installed communication client.
The Messages view has bounded explicit history paging; complete automatic
scroll restoration, per-agent unread state, and full team assignment remain work.

The installed workspace includes Messages, Groups, Calls, WhatsApp, Automation, and Settings.
See [Groups and Calls](groups-and-calls-ui.md) for implemented controls and channel limits.
Settings saves encrypted Hub/callback credentials and verifies the token’s account
and site binding before accepting the connection. Only System Managers can change
configuration. Provider acceptance and the remaining product features below are
still separate release requirements.

## Before production

| Area | Remaining work or acceptance requirement |
| --- | --- |
| Real providers | Account eligibility, credentials, permissions, template/call/group acceptance, real deliveries and receipts |
| Permissions | Complete team assignment and agent visibility rules; Contact-recipient enforcement for the account-level email MCP facade; site-specific business/Contact permission review |
| Provisioning | Full external identity enrollment and expiring verification; current endpoints are administrator verified |
| Media and email | Full attachment viewer/upload flows and the complete email composition workflow; the new media proxy is sticker specific |
| Automation | Voice/vision, direct OpenAI adapter, fallback routing, learned-guidance publication/evaluation, report/artifact actions |
| Tickets | Assignment workflow and notification preferences/delivery on ticket updates |
| Recovery | User-facing uncertain-send reconciliation, full delivery-state UI, retention and operational audit policies |
| Deployment | TLS, service recovery, backup/restore rehearsal, migration rehearsal, monitoring and measured load/capacity limits |

Do not equate a successful simulation with all platform features being complete.
These are explicit remaining requirements, not hidden setup steps. For Hub's
separate operational limits, read its
[documentation](https://github.com/andrometiq/relay_hub/tree/develop/docs).
