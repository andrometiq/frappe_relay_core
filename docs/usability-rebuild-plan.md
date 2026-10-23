# Relay usability and realtime plan — 24 September 2026

Migration remains on hold. This plan replaces piecemeal UI additions as the acceptance checklist. Implement on develop, retain user data, and distinguish fixture checks from installed and provider evidence. No deployment-readiness claim until the workflows below pass.

## Findings from the installed code

- The standalone Core entry does not initialize a Socket.IO client. Message refresh uses five-second polling. The inbound publisher targets the ingestion session, not the operators viewing a conversation. A working queue is not a realtime chat implementation.
- Shared search controls introduced hard-coded colors. Both app stylesheets also override Frappe semantic colors with light-only colors. Neither standalone entry initializes a theme preference.
- The chat composer exposes generic message-type selects. Its channel selector derives choices from loaded history, which does not cover all verified endpoints or multiple email addresses.
- Cases, topic management and delivery diagnostics sit directly above every conversation. These are not the primary one-to-one chat workflow.
- Campaign validation and channel options are WhatsApp-only. Simply adding Telegram/email labels would create unusable forms.
- Business-record lookup searches only `name`. Frappe's own desk search uses title_field, search_fields and show_title_field_in_link; Relay must honor that metadata with the same permission boundary.
- Background summaries exist, but the requested date-filtered, selected-record, summary/full-history, PDF/XLSX prepared-report workflow is not complete.

## Implementation order and acceptance

1. **Theme and navigation foundation.** Use Frappe semantic surface/ink/outline tokens everywhere touched, initialize light/dark/system preference, and match native field density. Compact desktop sidebar expands as an overlay on hover or keyboard focus; touch navigation remains explicit. Respect reduced motion. Check both apps, dialogs, option menus, disabled/error/selected states, narrow screens and reload persistence.
2. **Realtime transport and reliable message state.** Reuse the installed Frappe Socket.IO authentication/namespace and authorized subscriptions. Publish after committed changes; avoid leaking payloads across contacts/users/sites. Subscribe per active view and clean up on navigation. Coalesce event-triggered API refreshes, recover missed events on reconnect, keep bounded polling only as fallback. Show local Sending immediately, then real Sent/Delivered/Read or actionable failure without equating provider acceptance with delivery. Test two real browser sessions, reconnect, duplicate events, permissions and background job completion.
3. **Channel-aware chat.** Resolve all verified destinations through a bounded API; make recipient/channel explicit. WhatsApp: media menu, template-window handling and valid supported actions. Telegram: media, voice/sticker/reply/reaction/topic context when the underlying chat needs it. Email: To choice, CC/BCC, subject, attachments and thread continuity. Show typing through provider capability where supported; distinguish internal teammate typing. Preserve per-destination drafts and stable send identity. Put advanced case/topic/report history in contextual details; delivery diagnostics belong in operator tools. Unlinked inbound senders become an Inbox view with enrollment controls.
4. **Frappe-aware remote fields.** Debounced single/multiple selection with configured title/search fields and readable descriptions, permission-scoped results, cancellation and selected-label hydration. Replace manual Find buttons for search-driven pickers. Verify fields with titles that differ from names and records beyond the first page; benchmark actual indexed queries before claiming large-directory latency.
5. **Campaigns and templates.** Implement backend dispatch/recipient validation for WhatsApp, Telegram and email before exposing each channel. Select multiple business records via remote search; review recipients, duplicates and unavailable endpoints before queuing. Template editor: named type/category/language choices, header/media variants, parameter examples and live preview; validate names, required fields and provider constraints on client and server. Test errors and provider approval/rejection states without fabricated success.
6. **Prepared conversation reports.** Select one/many records, date range, full transcript or AI summary, and PDF or XLSX. Queue an authorized background job, show progress/completion through realtime, reuse valid summaries with provenance, render PDF through a maintained print format and export real XLSX. Files remain private and permission checked. Test empty/large ranges, retry, timeout, download access and reconciliation on reload. AI/provider configuration and ticket/automation setup stay in Desk/backend; frontend presents user actions/results only.
7. **Integrated acceptance.** Walk every workflow with ordinary operator and manager roles in light/dark modes, desktop/mobile and two concurrent sessions. Validate installed inbound/outbound receipts, attachments, channel switching, campaign progress and report completion. Keep live provider sends explicit and controlled. Update the evidence matrix with pass/fail/untested, never substitute a build or fixture for provider acceptance.

## Current work

- Remote API search foundation deployed; two-million-account Hub fixture passed. Core per-DocType large-scale search remains unverified.
- Theme corrections are first in this plan. Realtime and channel-aware composition follow; the broader product is not complete.

## Hub authentication and information architecture follow-up

User reports automatic logout and requests manually revocable, non-expiring integration tokens. Current code enforces a 30-minute idle session limit and eight-hour absolute lifetime; API tokens require 1–90 days. Audit server-derived identity vs mutation target IDs, CSRF and session revocation; fix unexpected logout behavior with an explicit persistent-session policy. Add explicit No expiry for integration tokens while preserving existing expirations, revocation, scopes and account grants. Do not confuse Hub integration tokens with Meta provider access tokens. Separate login/security audit from provider message parsing diagnostics; prioritize Users & access in Hub navigation. Both apps need theme parity and hover/focus overlay navigation.

## Detailed chat-experience acceptance (voice message 11779)

- User chooses combined timeline or separate WhatsApp/Telegram/Email tabs. Persist this presentation preference; do not conflate it with routing permissions. Only the active tab fetches its messages; fetch bounded unread/count metadata separately.
- Each contact/channel tab owns draft, selected destination, quote, loaded keyset windows and pixel/message anchor. Switching tabs preserves its in-memory viewport. After destruction/reload, restore the server-side last actually viewed message for that user/contact/channel.
- Support bounded infinite paging in both directions. Retain viewport while prepending; evict bounded windows deliberately rather than fetching full history. New realtime messages never yank a reader away from older history.
- Floating animated new-message/jump-to-latest action with reduced-motion support. Jumping over 1,500 unread messages records only messages actually visible, not the skipped interval. Exact unread count and exact read evidence are distinct from the resume anchor. Current 100+ unread cap does not satisfy the requested exact count.
- Read evidence records user, message and view time. Compare the installed legacy app's actual viewport/read-position behavior and exercise it in two users/tabs, not merely backend unit tests.
- Canned messages support defined actions where appropriate to WhatsApp/Telegram; email is a separate composing/threading workflow, not forced into a chat-only canned-message model.
- Optional manager-controlled automatic voice transcription and text translation to English. Detect original language, preserve original text/media, store derived text with model/source/version provenance and failure state, and expose an explicit original/translated view. Translation is not a replacement for original evidence. Configure in Desk; do not enable or incur live AI use implicitly. Multilingual chatbot behavior remains downstream of a usable, verified chat.

## Report specification to implement and document

A report request identifies selected business records/contacts, channel filters, timezone-aware inclusive start/end dates, transcript vs summary, and PDF vs XLSX. Resolve record-to-contact links with permissions at request and download time. Date-wise summaries need source boundaries, source revision/hash, timezone, model provenance and invalidation/rebuild rules; selecting a range must not include messages from outside it through an overlapping cached summary.

Full transcripts retain chronological order, sender/channel, timestamps, reply references and recorded delivery state. Images use bounded authorized thumbnails/previews with captions; private attachments list filename/type/size and access-controlled references. Missing files remain explicitly unavailable. Do not fetch arbitrary remote attachment URLs while rendering. PDF uses a maintained print format with pagination, consistent timezones and readable images; XLSX preserves typed dates/text and neutralizes spreadsheet-formula injection. Voice/video/file items are represented honestly, including optional derived transcription text with its provenance.

Large jobs use prepared reports/background queues with durable request identity, progress/status, failure/retry, output expiration/retention and permission-checked downloads. Realtime completion updates the requesting user's report view; reconnect refetches status. Document range boundaries, media treatment, summaries vs original evidence, unread/read evidence inclusion and limits before acceptance. Test mixed records/channels/media, empty ranges, revoked access, missing attachments, duplicate requests and very large histories.

## Evidence checkpoint (local development, not release acceptance)

### Transport contract from message 11781

One Hub account routes to one Core site with WhatsApp, Telegram and Email channels. Acknowledge provider webhooks only after durable storage; promptly forward new messages independently of delayed status traffic. Persist outgoing requests before acknowledgement and use bounded workers, provider-aware rate limits and retry rules that do not duplicate uncertain sends.

Status traffic must use a separate durable lane, compact channel/message identity and provider-confirmed state, capped at 500 message updates and a bounded encoded byte size per request. Advance a cursor only after the site's durable acknowledgement; retain retryable batches and isolate slow sites. 200,000 updates require at least 400 requests at that count limit. Apply valid non-regressing transitions under row locks without changing message modified timestamps; coalesce realtime notifications per committed batch. Do not infer email delivery from SMTP submission or unsupported Telegram read receipts.

Current gap: WhatsApp already has separate realtime/status cursors but both still use 50-event batches. Bounded account scheduling now uses eight workers per WhatsApp lane and eight workers shared by Telegram/email, with per-key exclusion and database advisory locks across replicas. WhatsApp refreshes its account snapshot each scheduling tick; Telegram/email channels are scheduled independently. Telegram/email cursor advancement now requires the exact accepted count, not HTTP 200 alone. A provider event can contain several statuses, so increasing an event-count limit alone does not implement the requested 500-message contract. Compact status transport, cross-site fairness, prompt wake-up, recovery tests and sustained capacity measurements remain open. Go concurrency alone is not evidence for million-request capacity.

### Foundation checks

- Light/dark/system preference and Frappe-token fields are implemented in both apps. Core browser checked light/dark option surfaces, preference persistence and sidebar overlay without content shift. Hub security-page fixture checked both palettes. Whole-product theme acceptance remains open.
- Hub persistent sessions and explicit no-expiry integration tokens implemented; authentication race suite passed (including manual revocation and temporary-database-failure cookie preservation). Existing finite API token expirations are retained.
- Installed Core connects to `yrp.site:9002` over Socket.IO. A committed payload-free Relay event was observed in a second browser and triggered exactly one inbox directory refresh. Transaction/rollback invalidation test passed; 34 message-type projection scenarios passed. Full two-user permission/reconnect/load acceptance and all-view progress handling remain open.
- Inbox Unlinked view and compact conversation-tools menu implemented and browser checked without page errors. Advanced features remain accessible but no longer occupy a permanent toolbar row.
- Business link search now delegates to installed Frappe `search_link`, preserving configured title/search fields and label/description. Isolated database test passed title search, extra-field search, ID lookup and role denial. Business directory typing is debounced; full text/index performance remains unverified.
- Per-channel view preference, independent persisted anchors, precise unread counts, prepared reports, daily summaries, translation view, full channel-specific composers and multi-provider campaigns remain required work, not completed by the foundation changes above.

Transport checkpoint: delivery-receipt writes preserve modified; the real Core database integration passed 35 message-type scenarios including this invariant. Core unit suite passed 106 tests (two skips). Hub race tests passed callback-worker, channel and WhatsApp suites against the isolated database; 100 synthetic accounts with a blocked account verified bounded concurrency and progress. These are correctness checks, not sustained throughput or end-to-end deployment acceptance.

## Chat UX implementation checkpoint

The installed preview now has Combined and channel tabs, channel metadata independent of the current history page, separate in-memory chat/email drafts, bounded per-tab history windows, and per-user persisted channel/message/pixel positions. Positions can move backwards independently of read evidence. The existing Conversation State gained a service-owned JSON field; schema was reloaded on yrp.site without migrating historical data. Unread counts use database aggregation and are no longer capped at 100.

The composer uses provider-specific attachment menus, emoji insertion, searchable published saved replies, the WhatsApp template-window guard and a separate email form. Enter submits chat text exactly once; Shift+Enter inserts a newline. Pending sends appear immediately, uncertain outcomes remain explicit, and queued actions reconcile by their existing durable action identity. Both-direction paging retains the visible anchor even when the 150-message window evicts rows. A floating latest-message action does not mark intervening messages read. Conversation search is debounced and follows the active theme.

Evidence: 106 unit tests passed (two skips); guarded inbox integration passed user isolation, independent/backward positions, exact 1,503-message unread counts and skipped-message read evidence; 36 message-type scenarios passed including published/channel-scoped saved replies. Browser fixture verified a 1,808-pixel scroll position restored exactly, separate chat/email drafts, one intercepted Enter submission with immediate Sending, no WhatsApp-only-incompatible voice option, older/newer pages capped at 150, dark palette and 390px mobile layout without horizontal overflow. The reusable browser acceptance script is `frontend/tests/browser/chatUxAcceptance.js`. No external provider message was sent for these checks.

Still separate acceptance/work: live multi-provider receipt/attachment verification, provider-side typing capability, canned-reply actions beyond text insertion, manager-enabled translation/transcription display, prepared reports and campaign expansion. Browser drafts intentionally survive tab switches only, not browser reload; server-side resume positions survive reload. The broader product remains under development.

### Source-linked voice transcript view

Voice/audio bubbles now offer View transcript / Hide transcript. This reads an already generated, policy-authorized transcript; opening the UI never starts a provider call or incurs an AI attempt. The original audio remains available. New transcripts record provider/model/time/source hash; historical rows without that metadata do not invent provenance. The read API requires current message, channel and business/contact access, returns no automation decisions or credentials, and refuses stale source hashes after an edit. Expanded views refresh on committed message invalidation. English translation remains separate and is not falsely labeled as completed by this transcript feature.

Guarded multimodal integration passed transcript access, provenance, stale-source rejection, unrelated-business denial, existing replay/budget/media gates and PDF report permission checks. The yrp.site schema and UI have been updated without enabling AI policies or invoking a live provider.

### Independent English translation queue

Desk's Relay Automation Policy now has an opt-in **Automatically translate incoming messages to English** setting. It uses the configured provider/fallback and shared daily attempt budget; voice also requires voice transcription permission. The independent `Relay Message Translation` journal processes every eligible incoming message, including older messages in a burst, rather than inheriting reply inference's latest-turn cancellation. Original source text/audio is never replaced in storage.

Jobs preserve source hash, policy revision, lease/attempt state, detected language, English text, provider/model/time and segment provenance. Inputs up to 12,000 characters are split into at most 2,000-character segments; each provider attempt consumes budget. Failed or malformed output remains explicitly failed. Reply inference and translation share a source-locked, durable voice transcript to avoid transcribing the same audio twice. Access, source hash, policy and endpoint are rechecked; stale job attempts cannot overwrite newer ownership. Recovery requeues pending/expired work, with at most two claimed attempts; explicit failed jobs remain for manager review.

The chat shows View in English only for opted-in connected channels. Switching back restores original rendering; this view does not make an AI call. English sources remain original. Model output is rendered as text, including literal HTML-like input. Existing voice transcripts remain separately viewable even if translation fails.

Evidence: guarded translation integration passed older-message processing, replay deduplication, original/provenance retention, long-message segment coverage, already-English behavior, changed-source denial, malformed output failure, both directions of voice reuse, lease exclusion/recovery, daily budget and business/manager-opt-out boundaries. Existing multimodal, unit and scoped-recovery tests passed. `frontend/tests/browser/translationAcceptance.js` verified translated/original toggling and safe rendering. The schema and recovery job are installed on yrp.site; scoped recovery reports nine methods with no missing/stopped/errors. No live AI policy was enabled and no provider translation-quality claim follows from fixture responses.

Translation follow-up: System Managers can explicitly retry failed jobs from Desk. Retrying is permission-checked and auditable; source/policy changes queue a new version rather than reusing an obsolete job. The isolated database test passed denial for non-managers and successful reprocessing. The installed translation recovery RQ job was observed FINISHED (no live translation policies enabled).

Regression evidence for this change: the broad simulation run passed all Core integrations, unit contracts, frontend data checks and whitespace checks (35 of 36 top-level checks). The Hub round-trip fixture failed because it rejected whichever concurrent account arrived first while asserting a retry for sim-a specifically. The fixture now rejects sim-a explicitly, preserving exact batch/cursor/account assertions. That focused race test then passed three consecutive runs. Original failure and follow-up remain separately recorded in Hub `.runtime/translation-regression.json` and `.runtime/translation-regression-followup.json`; this is not represented as a fresh all-green broad run.

### Chat interaction follow-up — 24 September 2026

The chat and email composers now share a channel selector based on verified contact channel metadata, rather than only the loaded history window. Selecting a channel restores its draft/view through the existing tab path. File picker cancellation retains the text composer and draft; replacing an attachment only changes its type after successful upload. Draft height follows restored/cleared text. Exact zero viewport offsets are retained, focus/visibility restoration resumes read tracking, directory queries immediately invalidate older responses during debounce, and queued action reconciliation uses the full conversation scope.

Validation: site build and extended browser chat acceptance passed (fixture APIs, no provider sends): email-to-Telegram selection, cancelled picker preserves draft, Enter exactly one send, Shift+Enter newline, saved reply insertion, chat/email drafts, exact 1808px viewport restoration, both paging directions with a 150-row bound, dark theme and 390px layout without horizontal overflow. This does not certify live provider delivery or complete all remaining chat requirements.

### Durable chat sends — 24 September 2026

Conversation opening restores the current sender's queued/uncertain/rejected journal entries. The API rechecks contact, source, channel and action permissions, excludes reactions, exposes preview/status only, and uses keyset pages of 50 with a load-earlier control. The thread offers receipt lookup for pending/unconfirmed sends without another submission. Provider/account secrets and journal payloads are not exposed. A sender/status/name index supports pending scans.

Evidence: isolated Frappe typed-message suite passes 37 scenarios with 39 loopback HTTP submissions, including owner isolation and safe pending preview recovery. Extended browser acceptance restores an uncertain bubble and checks its receipt without calling send, then passes chat draft/paging/theme checks. External provider delivery remains unverified in this pass.

### Structured saved replies — 24 September 2026

Relay Canned Reply now offers Text, Location and Contact types with conditional Desk fields and coordinate/phone validation. The channel-scoped, debounced picker labels each type and prepares the appropriate composer fields without sending. Structured replies are rejected as AI text replies; WhatsApp group pickers remain text-only because the provider path does not support location/contact there. Existing text replies retain their behavior.

Validation: isolated Frappe message suite passed 38 scenarios (39 loopback HTTP calls); browser acceptance verifies location/contact population and no send before operator confirmation, as well as existing drafts, paging, pending recovery, light/dark/mobile checks. Schema installed on yrp.site. Arbitrary business actions attached to canned replies remain a separate unfinished item; structured message types do not establish that requirement as complete.

### Compact status transport foundation — 24 September 2026

Implemented Hub's deterministic compact-status batch builder (500 receipts, 512 KiB array bound, event/offset resume cursor, malformed-receipt rejection, replay stability). The Core receive_statuses endpoint verifies HMAC/account, strictly validates up to 500 ordered event/position records, stores one durable projection event keyed by the canonical batch digest, and acknowledges only after insertion. Existing projection applies verified binding, monotonic receipt rules and update_modified=False. Delivery realtime invalidation is now coalesced once per batch globally and once per affected contact.

Evidence: Hub race tests cover a 1253-status sequence split 500/500/253, byte limits, malformed receipts and missing partial-event rejection. Core callback/receipt unit checks pass; isolated Frappe suite passes 39 scenarios, including authenticated 500-receipt persistence, replay deduplication, one realtime invalidation and unchanged modified timestamps.

NOT COMPLETE: Hub dispatcher still uses the existing raw-event callback. Next implement persistent cursor offsets and wire the compact sender/ack path, update transport fixtures, run real HTTP Hub/Core simulation including failures, then deploy/restart the Hub. No claim that live traffic uses 500-status callbacks yet.

### Compact status dispatcher wired — 24 September 2026

The prior transport-foundation blocker is resolved: Hub migration 0026 persists partial-event status offsets; status callbacks now use receive_statuses and acknowledge the exact compact receipt count. Failure keeps both cursor fields unchanged, restart resumes partial batches, completion clears the offset. Incoming realtime callbacks retain the original path. PostgreSQL race tests and authenticated HTTP roundtrip simulation pass, including a 1251-receipt event and a failed middle batch. All Go packages pass their standard test suite (DB-specific evidence comes from the explicit database tests). Local Hub migration/restart completed and readiness is HTTP 200. External-provider acceptance and high-load capacity remain unproven. Telegram/email continue on their existing event transport.

### Native prepared report foundation — 24 September 2026

Added the standard Relay Communication History Script Report with prepared_report enabled. Its date range uses provider sent_at with creation fallback, inclusive start/end days, permission-filtered keyset pages, untruncated message text, and chronological output. Above 20,000 accessible messages it fails clearly instead of producing an incomplete report. Requests use Frappe Prepared Report's long queue; status access rechecks record scope and owner. Completed/error updates publish a payload-free user-specific reports invalidation.

Isolated integration evidence: native Prepared Report insertion queues its generator (enqueue mocked), native generation was then executed directly, compressed private prepared data matched the selected scope, day filtering excluded old provider timestamps, invalid date ranges failed and another user could not read status. This proves generation and lifecycle logic, not live queue scheduling or PDF/XLSX export UX. Remaining: background export artifacts, refreshed Reports UI, media handling, summary/date cache integration and actual worker acceptance.

### Prepared PDF/Excel workflow installed acceptance — 24 September 2026

Report UI now submits dates/format to the native Prepared Report queue, follows queued/started/completed/error states, refreshes via owner realtime invalidation with a five-second fallback, and downloads the generated file. Recent reports survive reload. Export files are rendered in the worker, stored outside public file routes with restricted filesystem permissions, and deleted with their Prepared Report. Download and Prepared Report/File permission hooks recheck scope and source access. Excel writes literal text cells rather than formulas; PDF escapes text and denies external resources.

Actual yrp.site acceptance (no API interception): UI requested PDF en9g8o4653 and Excel 1o0ri0vmij; native workers completed both. Authenticated downloads returned 200, PDF 8652 bytes with %PDF- signature and XLSX 4888 bytes with ZIP signature. Page reload recovered recent reports and download readiness; 390px mobile had no horizontal overflow or JavaScript errors. These installed reports contained zero messages; populated PDF/XLSX generation, row counts, private artifacts, cleanup and owner isolation passed the isolated Frappe suite. Do not claim installed nonempty-content acceptance from the empty reports.

Still open: summary/date-cache integration, embedded media/attachment documentation, multiple business-record selection, large-range capacity and richer progress/cancellation. The full report requirement is not complete.

### Report image previews and attachment inventory — 24 September 2026

Optional previews now render in PDF and an Excel Images worksheet with preserved aspect ratio. Report rows include media/email attachment names/types. Preview reads reuse attachment authorization; decoding is bounded to 4 MiB source, 10 MP, 900px thumbnails, 50 images and 20 MiB processed bytes. Missing/unsupported media is labelled, not silently discarded and not fatal to text export. No external HTML/image URL fetching is allowed.

Validation: populated isolated native report generation produced PDF image objects and XLSX embedded media; lifecycle tests still pass. Focused tests verify opt-in, image-count/total-byte bounds and missing-media labels. Site UI build passed. Documentation is in docs/reporting.md. Summary mode and multiple records remain open.

### Multi-record reports — 24 September 2026

Report scopes now accept 1–20 unique records of a configured business type, checking each record before queueing and on later reads. The UI uses the existing debounced remote multiselect. Message rows are deduplicated across shared contacts and retain the matching business record names. PDF and Excel show those associations. The total export row bound applies across the combined scope. Legacy single-record prepared reports remain readable.

Populated isolated integration covers shared-contact deduplication, empty/duplicate/oversized selections, native PDF/XLSX generation and owner checks. The actual yrp.site UI selected two records through remote search and submitted job 9sjro4b7aj; the real worker completed it and the PDF download returned HTTP 200. The installed scope is still empty of messages; populated evidence is isolated. Date-wise AI summary reports remain unfinished.
