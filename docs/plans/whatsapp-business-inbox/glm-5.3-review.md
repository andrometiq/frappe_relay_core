> External model critique, not an audit of current code. Read the reviewed plan for adopted recommendations. Corrections: only customer inbound messages open/refresh the service window; thread identity also includes tenant/account and sending number. Group-room leakage is a hypothetical risk, not an observed finding. Group claiming remains required; any deferral needs a product decision.

# Review: Relay Core Plan

**Verdict.** Direction is sound: business-first aggregate, explicit permission boundary, deferral of channels/AI. Two structural problems remain: the UI plan (item 3–4) is built on the undecided foundation (item 5, message→business association), and implementation gate 1 separates inbox+permissions from the conversation — deferring exactly the flows where leaks occur. Several transport realities (phone-thread identity, shared 24-hour window) are implicitly modeled as business attributes; they are not.

## Concrete issues

1. **Realtime is the biggest leak.** Group-scoped socket rooms broadcast message payloads, counts and previews for every business in the group, including ones the user cannot read. Realtime must be per-user filtered events over authorized records, not group rooms; recompute counts server-side per recipient.
2. **Thread identity mismatch.** WhatsApp's real object is a thread keyed by (sending number, customer phone) — not contact, not business. Two contact records sharing one phone are one thread; a contact with several phones is several destinations. Key threads by phone; contacts resolve to phones; dedupe timelines and bulk sends at phone level. The plan never states this.
3. **Association is undecided but the timeline design depends on it.** Whether Business B's timeline shows contact C's messages sent under Business A determines filter logic, unread counts, and summary scope. This must be settled before wireframes freeze (default below).
4. **Quote leakage.** A customer quoting an earlier message carries the original business's content into whichever view the reply lands in. Render quoted content only if the viewer can access the original message's business; otherwise show a masked placeholder ("quoted message — restricted").
5. **Shared session window.** The Meta 24-hour window and template requirement are per (WABA number, phone), shared across *all* businesses messaging that phone. Business B's free-text send can fail because of Business A's activity (or lack of it). Composer state must be computed from the phone-level window and enforced at dispatch server-side, not just in the UI — even though template *management* UI is deferred, a hard "template required" block state is in M1.
6. **Group responsibility reads as access in three places.** Claiming, "group owner" and the queue all risk being treated as implicit grants. State once: responsibility is queue metadata only; every view, socket, count and dispatch rechecks document permissions. Reassignment must not be possible into groups/targets the reassigner can't see.
7. **Unknown senders undefined.** Inbound from a number matching no linked contact will happen. Default: admin-visible "unmatched" queue; never auto-create contacts; never drop silently.
8. **Optimistic sends need an idempotency mechanism** (client-generated key reused on retry) and a persistent "unknown" state that survives refresh — otherwise duplicate sends or invisible losses. Revocation mid-draft should mark drafts blocked, not delete them.
9. **Configurability creep.** Runtime-selectable DocType + grouping + roles edges toward the builder the user rejected. Pick the DocType at install time; v1 supports one, reconfigurable only by admin.
10. **Timeline ordering** assumes webhook timestamps arrive in order; delayed events reorder. Accept reordering with a stable sort and an "updated" indicator rather than fighting it.

## Shared phone vs business association (summary of conflicts)

Business association is *our metadata*; the phone thread is *Meta's reality*. Consequences: (a) one phone = one thread regardless of contacts/businesses — dedupe display and sends by phone; (b) the 24h window is shared, so one business's sends change another's sendability — show one live channel-state indicator per recipient phone in every authorized view; (c) delivery/read receipts arrive per phone message id — map once, display in all authorized business views of the same row; (d) quote replies bind to the original message's association, with masked rendering for unauthorized viewers; (e) never re-send a message per business — one dispatch, N authorized views.

## Smallest coherent first milestone (M1)

**"One agent safely holds a real conversation with one contact of a permitted business."** Includes: grouped inbox with permission-filtered counts/search; business timeline (read) under a settled v1 association policy; send/receive 1:1 with explicit recipient, per-recipient+identity drafts, phone-level channel state, template-required block; attachments behind per-request checks; delivered/read + team read-by; revoke handling; per-user filtered realtime. **Excludes:** bulk, AI summaries, template/Meta management, claiming semantics (single responsible field only), automated reassignment. This merges the plan's gates 1–3 because an inbox without conversations tests none of the hard parts.

## Revised screen flow

1. **Desk (admin):** install config — business DocType, grouping field, contact link, sending identity, association policy.
2. **Group rail (left):** selector + collapsible groups → business list (server-side, debounced search, filtered counts).
3. **Conversation (center):** header (business, group, responsible) · contact filter dropdown · combined timeline (consecutive-bubble compression, internal notes distinct) · composer with explicit recipient selector and live channel state.
4. **Context panel (right, collapsible):** business/contact details; association dialog for ambiguous inbound; summary later.
5. Keyboard: list navigation, Enter→composer, Esc→panel; mobile: rail collapses to sheet, sticky composer.

## Permission / ownership matrix

| Action | Business Read | Read + Relay Sender | Group Responsible | Supervisor | Desk Admin |
|---|---|---|---|---|---|
| See business in list/counts/realtime | ✔ | ✔ | only if also Read | only if also Read | ✔ (config) |
| View timeline, attachments, search | ✔ (checked per request) | ✔ | — | — | — |
| Send message | ✖ | ✔ | ✖ | ✖ | ✖ |
| Link/associate ambiguous inbound | ✖ | ✔ on that business | ✖ | ✔ if Sender | ✔ |
| Reassign responsible | ✖ | ✖ | ✖ | within authorized groups | ✔ |
| Configure DocType/grouping/credentials | ✖ | ✖ | ✖ | ✖ | ✔ |

Responsibility and claiming grant nothing; every cell is additionally gated by document permission at the server, including delayed/bulk jobs and AI inputs.

## Acceptance scenarios (M1)

1. Shared contact replies; message associates per policy; an agent without permission on that business never sees it in list, counts, realtime, or search.
2. Customer quotes a Business A message while viewing under B; B-only agent sees masked quote, not content.
3. A's reply opens the 24h window; B's composer for the same phone shows window-open; after expiry both show "template required" and the server rejects free-text.
4. Optimistic send loses its webhook: shows "unknown"; retry reuses the idempotency key; no duplicate; refresh preserves state.
5. User reading history: new message doesn't move scroll; floating button appears; returning to the view restores position.
6. Draft to Contact 1; switch to Contact 2; switch back — draft restored; empty recipient blocks send; no silent inference.
7. Access revoked mid-view: UI clears, socket/API denied, open draft marked blocked.
8. Group has 30 businesses; agent reads 20 — all counts, previews and realtime reflect 20 only.
9. Two agents on one business see each other's messages live; read-by avatars update separately from provider ticks.
10. Inbound from unknown number → admin unmatched queue; timeline unaffected.
11. Group field changed: business moves queue per policy; message associations and audit trail unchanged.
12. Direct attachment URL without permission → denied; thumbnail loads only after check.

## User decisions vs sane defaults

**Genuinely need the user:** initial DocType; grouping field; exclusive claim vs shared team; inbound association policy for shared contacts (I propose: last outbound business within 24h, else linking queue — but it shapes the product and needs ratification); reply-permission model (I propose the Read + separate Sender role above); reassignment/history semantics; per-user read vs team work status.

**Sane defaults (recommend, don't ask):** thread identity = (sending number, phone); single-value grouping in v1; drafts keyed business+recipient+sending identity; unmatched inbound to admin queue; template-required as block-only in M1; install-time DocType choice; masked quotes; masked-then-blocked revocation behavior; phone-level dedupe in timelines.

No claims about existing code — all findings concern the plan's assumptions and unspecified behaviors.