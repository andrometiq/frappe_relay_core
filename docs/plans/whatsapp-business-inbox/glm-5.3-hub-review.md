# Second Review: Corrections, Core/Hub Contract, Revised Milestone

## Corrections to the first review

1. **Service window semantics were wrong.** Only a **customer inbound** message opens the 24-hour window, scoped to (tenant account, business sending number, phone). Business outbound never opens or extends it. Scenario 3 corrected: customer replies to Business A → window opens for that phone/number pair → authorized agents for any business on that phone may send free-text until expiry; after expiry all see "template required" and the server rejects free-text. Composer state derives from last inbound, not last outbound.
2. **Thread identity under-specified.** The provider thread is keyed by (tenant account, sending number, phone) — not phone alone. Same phone across sending numbers or accounts is a distinct provider thread. Same phone across businesses justifies neither merging access nor duplicating history: one dispatch per destination, one message row, N authorized views via association. Phone-level dedupe applies only within one sending identity.
3. **Realtime leakage** was a design risk to engineer out (per-user filtered events, server-side recomputed counts), not a statement about current code. Restated as an M1 requirement.
4. **Claiming must not be silently dropped.** M1 below includes manual responsible-agent assignment; basic claiming enters M1 *only if* the user picks exclusive-vs-shared semantics now. If not decided, deferral is recorded as an explicit proposal awaiting sign-off, not an omission.
5. **No implicit routing.** My earlier "last outbound business within 24h" default is withdrawn. Ambiguous inbound from a shared contact defaults to a **linking queue** visible only to users with Read on the linked businesses; they associate it to one business with an audit entry. Any automatic rule requires user ratification.

## Core/Hub boundary

**Core (Frappe):** document permissions, grouping, assignment/claiming, message association and history presentation, drafts, read-by, search, summaries (later), user-facing realtime. **Hub (Go):** WABA/account isolation, credential custody, provider transport, webhook receipt/verification, media proxying, delivery-state normalization, replay. Hub never evaluates Frappe user permissions; Core never holds provider credentials (Desk stores only account references).

## API capability matrix

| Capability | Direction | Auth | Notes |
|---|---|---|---|
| `send.message` (1:1) | Core→Hub | service, tenant+account scope | Client idempotency key required; durable queue; text/template/media ref; returns hub message id |
| `send.status` lookup | Core→Hub | service | By key or id; states sent/delivered/read/failed/**unknown**; authoritative |
| `send.cancel` | Core→Hub | service | Only while queued; returns final state (revoked \| already-sent); WhatsApp has no recall |
| `channel.window` | Core→Hub | service | Per account+number+phone: last inbound, open/until, template_required |
| `template.list` / `template.send` | Core→Hub | service | Read + send-now; creation/approval/management is a later, versioned API group |
| `media.upload` / `media.download` | Core↔Hub | service + per-request user check in Core | Short-lived signed refs scoped to message; never expose provider URLs; downloads logged |
| `inbound.message` callback | Hub→Core | signed internal (secret/mTLS) | Idempotent by provider message id; includes quoted-message ref; replayable by bounded range |
| `inbound.status` callback | Hub→Core | signed | Delivered/read/failed upserts; replayable |
| `webhook.verify` | Hub (external) | Meta signature per app | Invalid → reject + log; Core independently verifies Hub-originated calls |
| `account.health` | Core→Hub | service; surfaced Desk-admin only | Credential validity, app mode, quality/rate signals, quota |
| `bulk.submit` / `bulk.status` *(later)* | Core→Hub | service | Bounded chunks, per-chunk ack/status/cancel; per-record permission re-check at dispatch |

This matrix is the *contract*; whether existing endpoints satisfy it is unverified — no code audit performed.

## Cross-cutting: credentials vs end-user authorization; revocation

Two distinct planes. **Plane 1 (Core↔Hub):** service identity, tenant-scoped; Hub enforces only that a tenant uses its own accounts. **Plane 2 (user→Core):** every capability — view, send, media, summary, bulk — re-checked against document permissions at request time *and again at actual dispatch*, including delayed jobs. Hub logs the actor and message reference Core asserts, giving an audit trail without making authorization decisions. **Revocation limits:** queued sends revocable only pre-dispatch; dispatch must be single-flight with a state check so cancel-vs-send races resolve to one final state; "sent" is terminal and the UI must say recall is impossible. Bulk cancellation (per chunk, pre-submission) is later scope.

## Revised cohesive first milestone (M1)

One agent safely holds a real conversation with one contact of a permitted business — **merging inbox, permissions, and conversation** (splitting them tests nothing hard):

- Grouped inbox, permission-filtered lists/counts/search; per-user filtered realtime (designed in, not retrofitted).
- Combined business timeline under a user-ratified association policy; contact filter; per-recipient+sending-identity drafts; masked quotes for unauthorized originals.
- Send pipeline: optimistic send with durable idempotency key, first-class "unknown" state surviving refresh, retry-safe lookup, pre-dispatch cancel.
- Window/template block computed from phone-level inbound state per corrected semantics; enforced server-side.
- Media upload/download via authorized short-lived refs.
- Ambiguous/shared-contact inbound → linking queue; unknown numbers → admin unmatched queue; no auto-association, no auto-contact creation.
- Manual responsible-agent assignment. **Claiming:** included if the user decides exclusive-vs-shared now; otherwise an explicitly flagged deferral proposal.
- Excluded, unchanged: bulk, summaries, template/Meta management UI, automated reassignment.

## User decisions vs sane defaults

**Need user input:** initial DocType; grouping field; exclusive claim vs shared team (and claiming in/out of M1); ambiguous-inbound policy (linking queue proposed as default, alternatives require ratification); reply-permission model ratification; reassignment scope/history; per-user read vs team work status.

**Sane defaults, not questions:** thread key = (account, sending number, phone); window opened by inbound only; linking/unmatched queues over implicit routing; short-lived signed media refs; pre-dispatch-only cancellation; template block-only in M1; Core owns all authorization, Hub owns isolation and transport.