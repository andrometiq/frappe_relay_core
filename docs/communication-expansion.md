# Business communication

Relay Core supports business conversations through WhatsApp, Telegram and email. Core owns identity, business permissions, conversations, tickets, AI skills and business-event rules. Relay Hub is a Go service that owns provider credentials, transport, durable sends and callbacks.

## Identity and business context

A standard Frappe Contact can link to both a Supplier and a Customer. Verified WhatsApp, Telegram and email endpoints can identify the same person. Core keeps the selected business on each message and conversation. A shared identity does not give access to every linked business.

| Routing condition | Current behavior |
| --- | --- |
| Valid reply context | Use the business of the referenced conversation. Email checks thread ancestry; Telegram keeps chat/topic scope. |
| One linked business | Use that business after endpoint and sender-authentication checks. |
| Valid saved sender choice | Reuse the choice within its conversation scope. |
| Several businesses without a resolved context | Ask the sender to choose when the channel and conversation permit it. |
| Missing, conflicting, expired or untrusted context | Keep the event in triage for review. Do not guess a business. |

Telegram and email choices use expiring `relay-business:` text tokens. Telegram prompts require a private chat whose sender matches the chat. Email prompts require authenticated, non-automatic mail with a valid Message-ID. Choices expire after 24 hours and cannot be replayed into another conversation. Unrelated email threads from the same person retain separate business choices. Unknown or revoked endpoints remain in triage.

## Permissions and business lifecycle

Core uses Frappe users, roles, User Permissions and document permissions. Message queries apply business access before pagination. Direct reads and actions recheck access. A readable Contact is not permission to read another linked Supplier or Customer conversation. Attachments and message-linked tickets use the same message access checks.

Relay messages do not place a business record in a locked state. Relay history does not block update, cancel or delete. Delete/cancel hooks exclude Relay references from lifecycle link checks. Delivery and automation still use short database locks to protect their own state. Other apps and normal Frappe business rules retain their checks.

## AI skills and handoff

Enabled AI skills handle incoming text on WhatsApp, Telegram and email. Each skill is scoped to one channel and business DocType. Reads run as the linked Contact user or the configured non-administrator execution user. Missing or revoked access cannot fall back to a broader identity.

| Control | Behavior |
| --- | --- |
| Tools | Only configured `get_doc` and `get_list` read contracts are allowed. The server fixes business filters and readable fields. Model arguments can only narrow that scope. |
| Limits | At most 12 read tools, 20 selected fields per tool and 20 returned rows per list read. |
| Delivery | Replies use the durable action journal. Core rechecks permissions and read evidence before delivery. |
| Handoff | An explicit request for a person or a decision/authorization failure creates or reuses one assigned ticket for the conversation, business and automation generation. |
| Pause | Handoff pauses contact automation. Paused messages do not create another AI reply or ticket. |
| Email loops | Automatic mail, bulk/list mail and reports cannot start automatic replies. AI and fixed email rules check for an existing automatic reply. |

The handoff owner must be enabled and able to read the conversation. If no eligible owner exists, the run remains recoverable for configuration review. Read-only AI tool scope does not allow arbitrary document writes or arbitrary report execution. Published conversational flows remain limited to private WhatsApp conversations.

## Business events and channel consent

Business-event rules support `after_insert`, `on_submit` and `on_cancel`. The source transaction stores an immutable delivery intent. Provider work is enqueued after commit. A Hub outage leaves the intent available for recovery. Capture failures are logged without rejecting the business transaction.

| Channel | Event content |
| --- | --- |
| WhatsApp | Approved template and captured parameters |
| Telegram | Captured plain text |
| Email | Captured subject, text/escaped HTML and signature |

Rules select an explicit Contact or require exactly one linked Contact. Preference-based selection ranks verified, available endpoints for that person and business. Only Granted consent qualifies. Equal priorities require an explicit choice. Telegram/email event selection uses these consent checks even when a rule fixes the channel. Fixed-channel WhatsApp template rules retain their direct template path.

Core saves the chosen channel, endpoint and content with preference-based deliveries. It rechecks binding, consent and access before sending those deliveries. The preference resolver allows another selection only before admission or after confirmed rejection/failure. An admitted or uncertain outcome cannot trigger channel fallback.

## Installed UI and evidence

The installed `/relay` workspace uses the site's Frappe login and same-origin APIs. It includes business conversations, Telegram and email composers, tickets, automation and settings. Telegram preserves reply/topic context. Email provides Reply, Reply all, Forward, To/CC/BCC, signatures and bounded attachments. Drafts retain stable request keys.

Live updates use Socket.IO over WebSocket only. Payload-free invalidations trigger permission-checked reads. Reconnect and visibility changes refresh bounded state. There is no periodic HTTP polling fallback.

The 2026-10-24 connected reports pass 10/10 WhatsApp, 11/11 Telegram and 13/13 email cases. They include shared identities, business-scoped AI ledger reads, one-ticket handoff and business-event outage isolation. Single inbound checkpoint p50/p95 values are approximately 270/295 ms, 105/123 ms and 107/119 ms. Browser rendering, bulk campaigns, live providers and Telegram/email receipt-storm capacity are outside this evidence. See [implementation status](implementation-status.md) and Hub [release evidence](https://github.com/andrometiq/relay_hub/blob/develop/docs/simulation-validation.md).

Source: `relay_core/business_routing.py`, `relay_core/business_access.py`, `relay_core/business_references.py`, `relay_core/hooks.py`, `relay_core/ai/{tools,service,handoff}.py`, `relay_core/business_events.py`, `relay_core/channel_preferences.py`, `relay_core/email_templates.py` and `frontend/src/services/realtime.js`.
