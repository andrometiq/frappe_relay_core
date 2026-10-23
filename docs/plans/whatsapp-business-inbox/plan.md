# WhatsApp business inbox — reviewed design plan

Status: planning only. No implementation approval implied. Reviewed using Z.ai GLM 5.3 in two API requests; requested and returned model IDs are recorded alongside the critiques. Reviews received requirements, proposed workflows and unresolved decisions, not code or customer data. Their claims are design critiques, not findings about installed code.

## Product contract

Open a business record, not a contact-first workspace. Multiple contacts' associated messages form its internal timeline; real WhatsApp delivery stays individual. Group records by one configured field and let authorised staff take/handle a group. Group responsibility never grants document access. A user without business read access cannot see or reply to its messages. Sending additionally requires a Relay messaging capability. Start with one configured DocType and field, editable by an administrator in Desk; do not hardcode an install-time choice.

Other channels, migration and broad platform rebuilding remain deferred. Summaries, bulk sends and template/Meta management remain planned subsequent features. Technical configuration stays in Desk; business operations belong in the custom UI.

## First coherent milestone

A staff member takes or receives a group, sees only permitted business records, opens a business with multiple contacts, reads attributed messages, selects an explicit recipient and replies safely. Include the necessary Hub provider APIs in this milestone. Do not finish a disconnected inbox shell and postpone the conversation permissions.

Include group ownership/claim workflow after its exclusive/shared semantics are agreed. Include server-side debounced search/pagination, message history around saved position, safe draft persistence, attachments, incoming and outgoing realtime, unread navigation, customer delivery/read states, separate staff read-by avatars, and template selection/send when normal replies are unavailable. Full template authoring follows later.

## Screen flow and invariants

Group selector/panel -> permission-filtered business list -> business timeline -> optional details panel. All contacts is the default; contact dropdown filters without changing an active draft recipient. Composer always identifies recipient and sending number. Reply selects the message's source endpoint. New arrivals never switch recipient or scroll a user away from older history. Draft identity includes user, business, recipient and sending identity. Do not expose inaccessible persisted drafts after revocation; retention/deletion is a separate policy.

Incoming bubbles identify contact; outgoing identify recipient and agent. Internal notes are distinct. Details contain business fields, contacts, related records and later scoped summaries. Mobile uses sequential list/chat/details views; both themes and keyboard behavior are part of each feature.

## Association and permissions

Provider identity includes tenant/account, sending phone-number identity and recipient endpoint. Message provider IDs remain account-scoped. Sharing a contact/phone never merges document permissions. Proposed default: each message has one primary business association; associated business references do not grant conversation access. Multi-business views require a separate explicit design decision.

Quoted reply references can assist association when valid; retrieving the referenced content still requires access. Mask inaccessible referenced messages. Customer-supplied text already present in a newly received message cannot reliably be stripped of all cross-business information; this limitation must not be confused with leaking fetched history.

Ambiguous/unmatched inbound messages need a dedicated, explicitly authorised triage queue. Permission to one candidate business alone does not grant access to an entire ambiguous phone history. Associating/moving messages requires source/triage authority plus target-business permission and an audit entry. Do not automatically use last outbound business without user agreement. Group changes move record placement, not the message's business identity.

Enforce access on lists, counts, search, attachments/thumbnails, quotes, summaries, notifications, exports and mutations. Group claim grants no access. Realtime must not carry payloads or metadata for forbidden businesses; use permission-authorised delivery or minimal invalidation with authorised refetch. Account administrators do not implicitly inherit Frappe document access.

## Core / Hub responsibilities

Core owns Frappe document permission checks, grouping/claiming, business association, UI history/search, drafts, read tracking, summaries and recipient selection. Hub owns tenant/account/scoped credentials, provider transport, durable send state, verified webhooks, media transport, provider templates/health, callback delivery and replay. Browser calls Core for business operations; never trusts browser-supplied role/user/enabled flags as authority and never receives provider secrets. Hub authenticates scoped Core service credentials; it cannot infer Frappe permissions from an actor ID.

### Required API capabilities (names are conceptual, not new route commitments)

| User need | Core requirement | Hub capability |
|---|---|---|
| Send/reply | Business and sender permission; validated destination and quote | Durable idempotent text/template/media send; stable request and provider IDs |
| Sending/unknown/failure | Restore action state; do not silently resend | Account-scoped lookup by request key; queued/submitting/accepted/rejected/unknown outcomes; separate delivery state |
| Cancel before dispatch | Authorised cancel and honest result | Atomic claim/cancel handling; already-dispatching/accepted may be too late |
| Attach/view media | Recheck message/business access including previews | Scoped bounded upload and authenticated download; no public provider-token URLs |
| Reply eligibility | Show state for selected recipient | Last customer inbound/window expiry for account + sending number + recipient; enforce actual send eligibility |
| Templates | Permission-checked picker and preview now | Paginated approved templates and validated template send |
| Incoming messages | Idempotent storage; association/triage; authorised realtime | Verify Meta challenge/signature appropriately; persist before acknowledge; immediate bounded callback and replay |
| Status changes | Idempotent state transitions, coalesced authorised realtime | Separate status batches of at most 500 and byte limit; durable retry/acknowledgement; incoming traffic independent |
| Reconnect/recovery | Resume without duplicate messages | Stable event identities, bounded cursors/replay and retained failure diagnostics |
| Business account management | Role-appropriate connection/capability display | Available provider account/number health, capabilities and quality state; unknown/unavailable explicit |
| Later template management | Human-readable editor/preview/approval feedback | Supported create/update/delete/sync and approval-status events |
| Later bulk sends | Authorised audience, consent/exclusion checks, destination dedupe and preview | Bounded idempotent admission, item outcomes, status lookup and pre-dispatch cancellation |

For each capability, specify request/response schema, account scope, auth, errors, limits, pagination, idempotency, timeouts and retry behavior. Inventory existing Hub/Core endpoints first and map them to these contracts; do not rebuild existing operations or claim gaps without inspection. Provider operations unsupported by Meta must be explicitly unavailable, not invented.

### Queued-send permission boundary

Recheck user/business access before Core dispatch. If Hub retains a job before provider execution, claiming 'permissions checked at actual dispatch' requires an explicit Core authorisation handshake or equivalent coordinated revocation protocol. A Core check followed by an arbitrarily delayed Hub job is insufficient. Design a bounded per-dispatch authorisation/claim step with Core outage failing closed for unsent work, plus cancellation and documented in-flight race boundaries. Reuse existing mechanisms if they meet this contract. Once a provider request is in flight, revocation cannot promise recall; unknown outcomes must be reconciled before retry. Provider acceptance is not delivery/read completion.

## Review corrections and adopted decisions

Adopted: settle association before freezing wireframes; combine inbox/security/chat into one acceptance milestone; protect quote/media/realtime paths; distinguish provider thread from business context; preserve stable send identities and unknown outcomes; specify full Core/Hub contract.

Corrected GLM: outbound agent messages do not open/refresh the service window. Meta states it opens/resets with customer messages: https://whatsappbusiness.com/policy/ . Realtime leaks were hypothetical risks, not code findings. Group claiming remains in scope. Do not infer access from group membership or one candidate business. Do not silently introduce multi-business message sharing. Admin-configurable does not mean install-time hardcoding.

## Acceptance scenarios

1. Group with 30 records, user can read 20: rows, counts, search and events reflect only authorised data.
2. Two staff claim the same exclusive group: one succeeds and other sees the current owner; shared mode uses agreed handler rules.
3. Business with three contacts: all shown in one timeline; replies reach explicit intended endpoint.
4. Filter change/new arrival while drafting: recipient and draft remain unchanged.
5. Same phone represents two businesses: restricted history and quotes do not leak; ambiguous inbound follows triage policy.
6. Access revoked: future reads/media/sends denied; UI clears; queued/in-flight behavior follows documented boundary.
7. Lost response: action restored after refresh, lookup reconciles, no second provider send from blind retry.
8. Unread/old history: bounded paging in both directions, stable viewport, new-message button and saved position.
9. Group field changed: placement/ownership follows agreed rule, history retained and access re-evaluated.
10. Service window expired: template selection offered; stale free-text eligibility cannot bypass server checks.
11. Callback replay/out-of-order statuses: no duplicate messages or status regression.
12. Two agents collaborate: realtime messages and staff seen-by remain distinct from customer receipts.
13. Direct attachment/API requests bypassing UI still enforce document/account boundaries.
14. All above key UI states reviewed on mobile and in both themes.

## Decisions needed before implementation

Initial business DocType and single-value grouping field; exclusive group claiming vs shared team handling; how responsibility interacts with the right to send among otherwise permitted users; approved association rule for shared contacts; scope of reassignment and triage role. Recommended default permission model is business Read plus explicit Relay Send capability. Read position is per-user; team work status is separate.

## Delivery order

First annotated wireframes and agreed ownership/association rules, then map existing APIs and write contract gaps, then implement and accept the coherent first milestone. Follow with business/date-scoped AI summaries, reviewed bulk messaging, and template/Meta business management, each completed before starting the next. No application code or deployment changes made for this review.
