# Relay requirement verification — 2026-09-23

## Conclusion

Relay is a partially implemented platform, not a production-complete application. The installed Core is substantially narrower than the design preview. Passing provider simulations does not establish complete product coverage.

This review inspected both local `develop` trees, the installed workspace entry point, active review services, and retained simulation results. It did not send live provider messages or change production data. Existing browser results are prior evidence, not a new browser acceptance run. No percentage of completion is justified.

## Verified gaps

| Requirement | Finding | Code evidence / acceptance needed |
| --- | --- | --- |
| Complete installed inbox, dashboards, campaigns, teams, folders, flows | Partial. Installed navigation contains Messages, Groups, Calls, WhatsApp, Automation, Settings. Richer preview screens use sample data and local state. | `frontend/src/SiteApp.vue` versus `frontend/src/App.vue` and `data.js`. Persist and connect each feature before claiming completion. |
| Agent sees only assigned conversations | Missing complete assignment enforcement. Relay roles and business permission checks exist, but there is no implemented team/assignment model among the current 15 DocTypes. | `relay_core/permissions.py`, DocType schemas. Require server-side assignment rules and cross-agent denial tests. |
| Per-user read position, unread counts, folders, stars, presence | Not implemented in installed inbox. Preview state is insufficient. | `ConnectedMessages.vue`, current DocType schemas. Need persisted per-user state and realtime reconciliation. |
| Reverse infinite scrolling and last-read restoration | Partial. Installed Messages has an explicit Load earlier button, 50-row pages and a 150-row cap; no automatic restoration. Contact selector fetches only first 50 matches without next-page UI. | `ConnectedMessages.vue`. Bounded memory exists but requested interaction does not. |
| Database search and bounded tables everywhere | Partial. Core contact API searches the database with cursors. Hub Accounts loads all accounts and filters in the browser, rendering all matches. | Core `api.py`; Hub `internal/accounts/store.go:List`, `frontend/src/App.vue`. Need Hub database pagination/search and measured large-data tests. |
| Unified business-record conversation | Partial. Relay Contact uniquely links one Frappe Contact; permission checks traverse business links. Installed selection remains per Contact, not one aggregate customer with all linked Contacts. No channel filter exposed in installed Messages despite API support. | Relay Contact schema, `permissions.py`, `ConnectedMessages.vue`, `api.py`. |
| WhatsApp/Telegram group UI | Partial. Group workspaces and multiple administration operations exist. This is not full parity with adapters: Telegram topics can require manual IDs; complete member/group discovery and every group operation are not exposed. | `TelegramGroups.vue`, `WhatsAppWorkspace.vue`, `docs/groups-and-calls-ui.md`. Verify each desired operation separately. |
| Calls | WhatsApp signaling and browser recording controls exist; no other calling adapter. No server recording archive. Real audio, permissions and recording interoperability remain unverified. | `CallsWorkspace.vue`, `WhatsAppWorkspace.vue`, Hub provider matrix. Prior browser call simulation uses mocked media. |
| Rich message coverage | Partial. Typed stickers/reactions/locations/contact cards exist with channel restrictions. Telegram general photo/video/audio/document sending is absent from typed adapter. General attachment upload/viewer is incomplete. | `messaging.py`, `MessageContent.vue`, Hub `docs/provider-support.md`. |
| Full email workflow | Missing mailbox sync, MIME attachments/HTML, thread-header composition, forwarding and complete auto-reply handling. Current SMTP provides plain text To/CC/BCC; normalized ingress is not a mailbox reader. | Hub `internal/email/adapter.go`; Core lacks a complete installed email composer. |
| Equivalent durable outbound delivery across channels | Partial. WhatsApp has durable Hub outbox. Telegram/email MCP handlers submit directly; they lack equivalent Hub durable intent/retry handling. | Hub `internal/hubmcp/server.go`, `internal/whatsapp/outbox.go`. Core automation outbox does not make every direct Hub request durable. |
| Recipient permissions everywhere | Release blocker. Core `relay.email.send` forwards supplied recipients to the account-level Hub without business Contact validation. Other direct send/ticket paths need consistent business-permission review. | `relay_core/mcp.py:email_send`; `tickets.py:validate_ticket` checks Message/Relay Contact but does not call `readable_contact`. No exploit test performed in this audit; do not treat this as validated authorization coverage. |
| Visual flow builder and agent-created flows | Preview only, not a persisted production flow engine. Current automation decision schema is category/brief/ticket/canned reply/handoff. | `frontend/src/App.vue`, `automation/contracts.py`, DocType inventory. |
| Multi-model AI including voice/vision, reports and learning | Partial. Text adapters support OpenRouter, Anthropic, GLM and Gemini. Direct Codex/OpenAI adapter, fallback routing, voice/vision, scoped report/PDF actions and published learned procedures are not implemented by this adapter/decision model. | `automation/providers.py`, `contracts.py`, `docs/implementation-status.md`. |
| Ticket workflow | Partial. Tickets link multiple messages and support status changes. Complete installed ticket workspace, assignment, chat-position navigation and email/Telegram update notifications remain missing. | `tickets.py`, Relay Ticket schema, `SiteApp.vue`. |
| Provider metadata synchronization | Hourly account/template reconciliation remains outstanding; webhook ingestion is not equivalent to periodic reconciliation. | Hub provider support matrix; reviewed Hub startup has no corresponding hourly sync loop. |
| Automatic recovery in review environment | Recovery functions are registered but periodic recovery is not running: review common configuration has `pause_scheduler: 1`; active review units include a worker but no scheduler. | `relay_core/hooks.py`, isolated runtime configuration, user systemd unit listing. A running worker alone does not execute cron hooks. |
| Production operations and automatic scaling | Not production validated. Adaptive WhatsApp workers are not machine/container autoscaling. Review uses a temporary tunnel and transient services. Restore/migration rehearsal, sustained capacity and production monitoring still need acceptance. | Hub provider matrix and active review service configuration. |

## Existing foundations and test boundaries

PostgreSQL migrations, encrypted account credentials, Hub authentication and scoped MCP, native Frappe authentication, Relay-prefixed DocTypes, provider adapters, callback journals, WhatsApp durable queue, and bounded Core message queries are implemented. These foundations must not be confused with completion of the user-facing workflows above.

Retained evidence inspected:

- Core `.runtime/groups-ui-integration.log`: 22 synthetic database group scenarios passed, 12 fixture HTTP submissions.
- Core `.runtime/groups-ui-unit.log`: 67 tests run, 65 passed, two skipped.
- Core `.runtime/groups-ui-frontend.log`: no failures; these tests do not establish a complete connected product.
- Hub `.runtime/simulation-report.json`: prior combined provider/database and frontend run. Its provider transports are simulated; it does not prove live account eligibility, audio or recipient rendering.

This audit did not rerun the full suite or validate live provider accounts. Both working trees remain on `develop`; nothing was pushed or merged as part of the audit.

## Release sequence

1. Close authorization inconsistencies and implement assignment isolation.
2. Complete durable cross-channel delivery/recovery and operational scheduling.
3. Replace preview-only screens with connected inbox, contact aggregation, unread/folder/team/ticket workflows.
4. Complete requested group/call/media/email controls and their provider-specific acceptance tests.
5. Implement persistent flows, expanded AI actions and approved learning.
6. Verify bounded database/UI behavior, failure recovery, backup restore and sustained load; then perform configured live-provider acceptance.
