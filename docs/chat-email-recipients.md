# Email composition and recipients

The installed inbox has an email composer with Reply, Reply all and Forward. It sends through `relay_core.email.send`. The From address comes from the configured Hub email account.

## Compose

| Field or action | Current behavior |
| --- | --- |
| To, CC and BCC | Enter plain addresses separated by commas, semicolons or newlines. The composer normalizes and deduplicates each list. The total limit is 50 addresses. |
| Recipient access | Every address needs a verified endpoint on the selected email channel and a readable business contact. Core checks access again before submission and recovery. |
| Reply | Includes the original sender or another verified address for the same contact. Core retains In-Reply-To and References. |
| Reply all | Fills CC from the source To/CC lists. Review those addresses before sending; the server applies the same verification rules. |
| Forward | Starts a new email thread for the destination contact and selected business context. It does not reuse the source reply headers. |
| Subject and body | A single-line subject of at most 998 characters and a text body of at most 100,000 characters, including the signature. |
| Signature | A per-user signature can be saved and included in the body. |
| Attachments | Up to eight files and 10 MB combined, or less when the site file size limit is lower. Upload and download require source-conversation access. |
| BCC | Sent in the SMTP envelope and retained in the private action audit. It is omitted from normal message history and the MIME BCC header. |

`email.recipient_options` provides bounded suggestions for API callers. The current composer uses address fields, not suggestion multi-selects.

Drafts and request keys are stored by user, business, contact, channel, thread and source message. A saved unresolved attempt remains available after a reload. A reply in one email thread does not assign another thread from the same person to that business.

## Delivery and recovery

Every email send creates a durable Relay Message Action before provider I/O. This includes new conversations, automatic replies and ticket notifications. The Hub also stores a durable outbox intent. Reusing a request key returns or reconciles that action; changed content with the same key is rejected.

Check status reconciles Core and Hub evidence. An uncertain admitted send is not sent again. A Dispatching action can resume submission only after a successful Hub lookup proves that no intent exists and Core rechecks the saved destination, business, content and access. Recover saved attempt reuses the stored request fields and key.

| State | Meaning |
| --- | --- |
| Queued | Delivery is pending. |
| SMTP accepted | The SMTP server accepted the message. This does not prove inbox delivery. |
| Uncertain | Acceptance is unknown. Do not create a replacement send to resolve it. |
| Rejected | Non-acceptance is confirmed. The owner can review a retry; Core checks current access and recipients. |
| Bounced | Trusted DSN evidence reports a recipient failure. |
| Delivered | Delivery evidence exists for every envelope recipient. This does not mean read. |
| Read by agent | A Relay agent read state, not a recipient email read receipt. |

Core checks DSN Message-ID and recipient against the saved action. Recipient evidence cannot regress from delivered to bounced or delayed. A bounce sets the message to Failed; all recipients must have delivered evidence before the message becomes Delivered.

HTML email opens in a sandboxed iframe with a restrictive content policy. Attachment bytes load through permission-checked APIs. Incoming From alone is not identity evidence: automatic routing requires trusted sender authentication. Automatic replies are suppressed for automatic mail, bulk/list mail and reports.

## Connected evidence

The 2026-10-24 email report passes 13/13 cases. It proves TLS SMTP/IMAP round trips, separate Customer/Supplier threads, To/CC and reply headers, send replay, permission denial, sender-authentication rejection, bounce DSN projection, sender choice, scoped AI/handoff, business events and preserved Message-ID. Ten single inbound webhook probes have p50/p95 107/119 ms.

The driver uses real Core APIs and Socket.IO. It does not test browser rendering, BCC, forwarding, attachments or every SMTP failure stage. These are source-backed capabilities, not claims of connected coverage. See Hub [release evidence](https://github.com/andrometiq/relay_hub/blob/develop/docs/simulation-validation.md) for report paths and rerun commands.

Source: `relay_core/email.py`, `relay_core/channel_statuses.py`, `relay_core/email_preferences.py`, `relay_core/business_access.py`, `frontend/src/components/messages/EmailComposer.vue`, `frontend/src/components/EmailContent.vue` and `frontend/src/services/channelComposition.js`.
