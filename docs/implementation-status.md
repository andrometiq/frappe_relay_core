# Current support and evidence

The source checked on 2026-10-24 implements WhatsApp v1 and Telegram/email v1.5 business communication. The connected local reports pass 10/10 WhatsApp, 11/11 Telegram and 13/13 email cases. This is local release evidence, not live-provider certification.

| Area | Current behavior |
| --- | --- |
| Identity | Verified channel endpoints can share one Contact linked to Supplier and Customer. Reply context, sender choice and triage resolve business ownership. |
| Permissions | Frappe authentication and business-scoped message queries, reads, actions and attachments. Shared identity does not merge business access. |
| Business lifecycle | Relay history does not block business update, cancel or delete. It does not impose a business record lock. |
| Delivery | Core actions and Hub outboxes persist requests before I/O. Reconciliation uses provider evidence. Confirmed missing intents can resume; uncertain sends are not blindly repeated. |
| WhatsApp | Messaging, provider receipts and template lifecycle. Provider eligibility and capability gates apply. |
| Telegram | Plain text, supported media, chat/topic replies, 429 recovery and honest Bot accepted status. No recipient delivery/read stream. |
| Email | TLS SMTP/IMAP, IMAP IDLE wakeups in Hub, thread ownership, verified To/CC/BCC, bounded attachments and trusted recipient DSNs. SMTP acceptance does not mean read. |
| Composers | Telegram reply/media controls and email Reply, Reply all, Forward, signatures and saved drafts. |
| AI | Channel/business-scoped text skills with `get_doc`/`get_list` only, permission rechecks, paused-contact suppression and one-ticket handoff per conversation/business/generation. |
| Business events | Durable content snapshots and provider dispatch after commit; scoped channel preferences and consent. |
| Realtime | Socket.IO over WebSocket, payload-free invalidations and bounded reconnect/visibility refresh. No periodic HTTP polling fallback. |

The installed `/relay` workspace uses Frappe login and same-origin APIs. `npm run build:site` builds the installed UI. The separate preview does not supply an authenticated Frappe site.

## WhatsApp inbound types

| Type | Core behavior |
| --- | --- |
| Text | Text message. |
| Image, audio, video, document | Attachment viewer and account-scoped download, up to 16 MiB for received WhatsApp media. Uploads and AI inputs retain their separate 4 MiB limits. Documents retain filename, MIME, optional caption and file_size when supplied. If the webhook omits size, the download response supplies Content-Length; no size is invented during projection. Document previews use caption, then filename. |
| Sticker | Sticker viewer with a separate 2 MiB WebP proxy. |
| Location, contacts | Coordinates/address and contact cards. |
| Reaction | Updates the original message, including reaction removal; no new conversation turn. |
| Interactive button/list replies, template button replies | Text with selection identity. |
| Interactive form reply | Text and form fields; flow correlation token excluded from display. |
| Interactive call-permission reply | Text acknowledgement; does not enable calling. |
| Order, system, unknown interactive replies, unknown types | Unsupported display; no commerce or identity-change behavior. |
| Meta `unsupported`, including `poll_creation` | Remains unsupported. Raw provider evidence is retained in the Hub event. |

An additional `from_user_id` does not replace the verified `from` endpoint or
change routing. Payloads without `from` cannot yet resolve a verified endpoint;
business-scoped-ID-only routing is not implemented.

`HubClient.media('WhatsApp', id)` uses `whatsapp.attachment` and requires the
existing `messages:read` scope. Sticker callers explicitly select the narrower
`whatsapp.media` tool. Both enforce received-media ownership before any Meta GET.
Failures report a safe check identifier (scope, ownership, provider metadata,
MIME, size, destination or integrity), never provider URLs or credentials.

## Measured checkpoint

| Channel | Single inbound p50/p95 | Additional connected evidence |
| --- | ---: | --- |
| WhatsApp | About 270/295 ms | 12,000 receipts at about 519 receipts/s; overlapping inbound p95 about 293 ms |
| Telegram | 105/123 ms | 429 backoff, restart recovery and uncertain acceptance without resend |
| Email webhook | 107/119 ms | TLS SMTP/IMAP round trip, independent business threads and bounce DSN projection |

All three drivers test scoped Supplier ledger reads, replay, one assigned handoff ticket, paused automation and Sales Order delivery with Hub-outage intent retention. Hub [release evidence](https://github.com/andrometiq/relay_hub/blob/develop/docs/simulation-validation.md) records exact report fields, timing boundaries and rerun commands. WhatsApp single inbound figures come from the supplied checkpoint; its retained report combines inbound samples. Telegram/email use ten dedicated sequential probes.

## Capability boundaries

| Area | Not established or not supported |
| --- | --- |
| Browser | Connected drivers do not render the installed UI or measure paint. API and Socket.IO success do not establish composer or viewer acceptance. |
| Live providers | Credentials, account eligibility, public webhook delivery, real recipient rendering and production capacity are not proven by local fakes. |
| Load | Telegram/email 12,000-status load acceptance is not established. Bulk campaigns are outside this release evidence. |
| Telegram | No recipient delivery/read stream, arbitrary Bot API calls, polls or inline-keyboard composer. The connected driver does not cover every group/topic operation. |
| Email | No recipient read receipt. Connected coverage excludes BCC, forwarding, attachments and the complete SMTP/IMAP failure matrix. Those features need evidence from their focused tests or separate acceptance. |
| AI and flows | AI skill tools cannot write documents or execute arbitrary reports. Published conversational flows are private WhatsApp only. |

See [business communication](communication-expansion.md), [email composition](chat-email-recipients.md), [Telegram recovery](telegram-connection-repair.md) and Hub [provider support](https://github.com/andrometiq/relay_hub/blob/develop/docs/provider-support.md) for source references and precise limits.
