# Relay WhatsApp business messaging system

**Status:** draft  
**Updated:** 2026-09-28  
**Mode:** repository audit and evolution

Relay must give a Frappe user a realtime, permission-safe WhatsApp inbox centred on a business document that can have multiple contacts, while Relay Hub durably accepts provider and outbound traffic for up to 100 sites. The present split between Hub transport and Core business context is sound, but duplicate channel activation, scan-based callback dispatch, and a shared slow Core queue make setup ambiguous and the live path fail its stated latency and throughput goals.

## Decision under review

Recommend **Authoritative event-driven relay** (`a`).
- nfr-2 requires p99 inbound visibility under 1 second, but the current 100-account scan alone has a 3.25 second lower bound; due-work scheduling removes that empty-account scan.
- fr-6 requires usable Meta setup, and one Hub-owned activation state gives the invariant one enforcement authority instead of two editable records.
- nfr-4 requires bounded behavior during a million-intent burst; the existing durable PostgreSQL outbox plus explicit per-account/global admission is sufficient, while a new broker has no measured bottleneck to solve.
- Separating Core projection from AI/report work contains the named queue-starvation failure without changing the Hub/Core domain boundary.

A distributed event broker is deliberately rejected for this milestone. The durable PostgreSQL journal and outbox already enforce the required acknowledgement and replay invariants; current evidence points to scheduling, capacity isolation, provider quota, and configuration authority as the binding gaps.

## Scope

**Included**
- `fr-1` Open a WhatsApp conversation by business document and choose among its linked contacts and mobile endpoints. (core)
- `fr-2` Accept inbound messages immediately, persist them before provider acknowledgement, project them to Core and update open inboxes through Socket.IO. (core)
- `fr-3` Send text and WhatsApp media/template messages with optimistic Sending, then Sent, Delivered, Read or Failed states. (core)
- `fr-4` Load history with cursor-based reverse infinite scrolling, restore each user's position and track per-user read state. (core)
- `fr-5` Enforce Frappe business-document, Contact, group-claim and assignment permissions on every list, read and send API. (core)
- `fr-6` Manage Meta WhatsApp credentials, webhook verification, phone identity and templates through one activation lifecycle. (core)
- `fr-7` Support canned replies, AI summaries and configurable flows after the base message path is healthy. (stretch)

**Excluded**
- Telegram and email channels
- calls and groups
- legacy WhatsApp Core data migration
- multi-region active-active deployment
- AI model internals and general report generation

## Protected targets

- `nfr-1` **reliability** — Hub returns 200 to Meta only after the provider event is durably inserted; retries deduplicate by provider event id. _user-stated immediate relay behavior and existing implementation invariant._
- `nfr-2` **performance** — p99 inbound event visible in an already-open Core inbox within 1 second under admitted load. _assumed from user requirement for immediate realtime updates._
- `nfr-3` **performance** — p99 outbound admission within 500 ms; provider completion is asynchronous and visible live. _assumed interactive chat target._
- `nfr-4` **scalability** — Admit or explicitly reject a 1,000,000-intent burst across 100 sites without unbounded memory or database growth. _user-stated burst target interpreted as intents rather than concurrent TCP requests._
- `nfr-5` **scalability** — Drain up to 5,000 provider submissions/s aggregate when provider quotas and account eligibility permit. _100 sites × 50 messages/s user-stated._
- `nfr-6` **performance** — Compact status freshness p99 under 5 seconds, with batches up to 500 rows and 512 KiB. _assumed; status changes need not be immediate._
- `nfr-7` **reliability** — RPO 0 for process loss after an acknowledged database commit; database-disaster RPO/RTO must be proven by restore drill. _partly implemented, production target assumed._
- `nfr-8` **availability** — 99.9% monthly for the regional service pair. _assumed until production SLO is supplied._

## Capacity envelope

| Metric | Value | Derivation |
|---|---:|---|
| aggregate target drain rate | 5,000 messages/s | 100 sites × 50 messages/s |
| 1M burst drain time at target | 200 s (3.33 min) | 1,000,000 ÷ 5,000/s |
| 1M burst drain time at measured Hub rate | 30,769 s (8.55 h) | 1,000,000 ÷ 32.5/s from the checked 2,000-message Hub burst result |
| status callback calls for 200k updates | 400 calls | 200,000 ÷ 500 statuses/call |
| status callback calls for 1M updates | 2,000 calls | 1,000,000 ÷ 500 statuses/call |
| current callback scan lower bound | 3.25 s for 100 accounts | ceil(100 ÷ 8 workers) × 250 ms tick, before network and Core projection |
| eight-worker provider ceiling at 200 ms | 40 submissions/s | 8 workers ÷ 0.2 s/request; actual quotas may be lower |
| raw storage for 1M burst | 2–4 GB payload; roughly 6–12 GB with WAL and indexes | 1M × 2–4 KiB; operational amplification assumed at 3× |
| cache footprint | n/a | Redis carries ephemeral jobs and realtime fan-out; durable recovery comes from PostgreSQL and MariaDB, not a read-through cache |

The target aggregate rate is 5,000 provider submissions/s. The repository evidence demonstrates 32.5/s in the checked 2,000-message burst. The design therefore treats 5,000/s as an acceptance target that must be proven against real Meta quotas; it is not a current capability claim.

## Ownership and consistency

### Transport Account

- **Representation:** Hub PostgreSQL account, encrypted credential rows and activation state
- **Identity:** stable Hub account slug; channel key is account plus provider
- **Ordering:** Hub control-plane transaction
- **Conflicts:** serialized state-machine transition; stale activation version is rejected
- **Durable at:** PostgreSQL commit of state and credential version
- **Retention:** disabled accounts retained for audit; secret versions retire after rotation and rollback window

### Provider Event

- **Representation:** append-only Hub webhook journal plus normalized inbound/status rows
- **Identity:** provider event id or deterministic payload digest scoped to account
- **Ordering:** provider timestamp is advisory; Hub event sequence is the replay cursor
- **Conflicts:** first durable identity wins; richer status advances monotonically
- **Durable at:** PostgreSQL commit before webhook HTTP 200
- **Retention:** raw acknowledged payloads retained 30 days by assumed policy; unresolved events retained until reconciled

### Message Intent

- **Representation:** Hub relay_outbox row with queued, submitting, submitted, uncertain, failed or cancelled state
- **Identity:** request_key unique within account
- **Ordering:** Hub database claim order per eligible account; no global message order promise
- **Conflicts:** idempotent insert; provider reconciliation resolves ambiguous timeout
- **Durable at:** PostgreSQL commit that returns accepted intent id
- **Retention:** resolved intents retained 90 days by assumed policy; uncertain rows retained until operator or provider reconciliation

### Business Message

- **Representation:** Core Relay Message plus Message Action and Delivery Receipt rows
- **Identity:** Core message name with unique Hub/provider correlation keys
- **Ordering:** Core projection cursor per Hub account and provider event order
- **Conflicts:** monotonic receipt precedence; business metadata follows Frappe document versioning
- **Durable at:** MariaDB commit of Hub event projection; browser Socket.IO is only an invalidation
- **Retention:** retained under site business-record policy; deletion cascades or anonymises linked content by configured policy

### Read State

- **Representation:** Core per-user Business Conversation State and Relay Message Read rows
- **Identity:** user plus business doctype/name plus contact endpoint
- **Ordering:** Core advances last-read cursor monotonically
- **Conflicts:** maximum visible message cursor wins
- **Durable at:** MariaDB commit before read acknowledgement
- **Retention:** removed with the user or business conversation according to site policy

Hub owns transport credentials, provider ingress, outbound intent state, and delivery cursors. Core owns Frappe business permissions, the conversation projection, user read state, and scroll state. Redis/RQ and Socket.IO carry work and invalidations; neither is a source of truth.

## Architecture 0: current split services

Hub durably relays transport events while Core projects them into Frappe business state, with scan-based callbacks and duplicated channel activation.

The current live inbound path is: Meta webhook → Hub PostgreSQL commit → fixed account scan → Core callback commit → shared `long` RQ projection → Core MariaDB → Socket.IO invalidation → permission-checked browser delta fetch. The durability choices are sound. The scan and shared queue prevent a latency guarantee.

**Strengths**
- Durable PostgreSQL outbox and webhook journal already isolate provider latency from admission
- Core keeps business permissions and message history inside the Frappe site
- Socket.IO invalidations avoid continuous message polling

**Limits**
- Two channel activation authorities allow configuration drift
- Scan-based callbacks miss the one-second live target at 100 accounts before network cost
- Realtime projection competes with AI, reports and campaigns on the long queue
- Eight global provider workers cannot approach the 5,000/s stated target

## Recommended architecture: authoritative event-driven relay

Keep Hub and Core, but centralize transport activation in Hub and schedule durable callback work by due account/lane into an isolated Core projection path.

The service boundary remains unchanged: Go Hub handles transport; Frappe Core handles business meaning and permission. Four changes make the contract enforceable:

1. Hub owns one activation state machine: `DRAFT → CREDENTIALS_VALIDATED → WEBHOOK_VERIFIED → CALLBACK_VERIFIED → ACTIVE`, with explicit `FAILED` and `DISABLED` states. Core receives a read-only capability projection.
2. A webhook transaction inserts the event and upserts the account/lane due row. Callback workers claim due work fairly with `SKIP LOCKED`; they do not scan inactive accounts.
3. Core persists the callback event before replying and projects it on a dedicated high-priority queue. AI, reports, campaigns, and translations cannot consume this capacity.
4. Ingress, callbacks, and provider submissions have separate worker pools, per-account fairness, finite backlog limits, and circuit breakers.

**Trade-offs**
- Adds lifecycle and scheduling state that operators must observe
- The 5,000/s drain goal still depends on Meta quota and measured horizontal worker capacity
- PostgreSQL remains a regional failure domain until standby and restore drills are operated

## Critical contracts

### Meta webhook

- **Transport:** HTTPS GET verification and POST events
- **Idempotency:** provider event id or deterministic account-scoped digest
- **Deadline:** persist and respond within 250 ms target
- **Retry:** Meta retries; Hub never retries the HTTP response
- **Backpressure:** bounded request body and four current ingress workers; return 429/5xx before commit when saturated
- **Compatibility:** additive provider fields accepted; unknown event types journaled but not projected
- **Failure result:** 200 only after durable insert; 403 for unknown account, bad verify token or bad signature; 5xx/429 before commit

### Core outbound admission

- **Transport:** authenticated HTTP/RPC from Core to Hub
- **Idempotency:** stable request_key scoped to Hub account
- **Deadline:** 500 ms to accepted or rejected
- **Retry:** Core retries ambiguous admission with the same request_key
- **Backpressure:** maximum 50 intents/request and 10,000 active intents/account; Hub returns explicit overload
- **Compatibility:** versioned envelope; additive fields first and old readers deployed before new writers
- **Failure result:** ACCEPTED with intent id; REJECTED before commit; caller-observed UNKNOWN reconciled by request_key lookup

### Hub realtime callback

- **Transport:** authenticated HTTPS batch from Hub to Core
- **Idempotency:** Hub event id unique in Core
- **Deadline:** 1 s maximum event age target; 3 s HTTP timeout
- **Retry:** Hub owns retry with exponential jitter and durable cursor
- **Backpressure:** at most 50 events/call; per-site circuit breaker and bounded unacknowledged retention
- **Compatibility:** version field; reader-first rollout and unknown additive fields ignored
- **Failure result:** Core returns highest contiguous acknowledged cursor; timeout leaves events pending

### Hub status callback

- **Transport:** authenticated HTTPS compact batch from Hub to Core
- **Idempotency:** message id plus receipt state/version
- **Deadline:** 5 s maximum status age target; 5 s HTTP timeout
- **Retry:** Hub owns retry from status cursor
- **Backpressure:** 500 statuses and 512 KiB per call; backlog retained and chunked
- **Compatibility:** versioned compact schema; Core accepts old and new fields during rolling deploy
- **Failure result:** partial batches are rejected atomically and retried; monotonic older states are harmless

### Browser realtime invalidation

- **Transport:** Frappe Socket.IO event plus authenticated delta fetch
- **Idempotency:** highest message/event cursor wins
- **Deadline:** 1 s callback-to-visible target
- **Retry:** browser reconnect performs cursor resync; server does not replay socket frames
- **Backpressure:** coalesce invalidations per conversation; delta page maximum 50 and DOM window 150
- **Compatibility:** event names versioned; delta endpoint tolerates additive fields
- **Failure result:** missed socket event is repaired by reconnect resync without polling

## Deep decisions

### One authority for WhatsApp activation

**Pressure:** A channel can be configured in Hub while Core Relay Channel remains disabled or points elsewhere, producing ambiguous 403/404 and uncategorized events.

**Decision:** Hub owns credentials and the DRAFT-to-ACTIVE state machine. Core stores only its account binding and a derived capability projection returned by Hub.

**Failure contained:** Hub accepts a webhook for an account that Core cannot route, or Core offers send for a channel Hub has not activated.

**Rejected:** Keep manual configuration in both applications; Move provider secrets into every Core site.

### Event-driven callback scheduling and isolated projection

**Pressure:** The current eight-worker 250 ms account scan has a 3.25 s lower bound across 100 accounts, and Core projection shares the long queue with AI and reports.

**Decision:** Upsert a due account/lane row when the webhook transaction commits; claim due rows fairly with SKIP LOCKED, and hand Core events to a dedicated high-priority projector queue.

**Failure contained:** An admitted inbound message remains durable but invisible while empty accounts are scanned or slow AI work occupies every Core long worker.

**Rejected:** Increase polling frequency and worker count; Add Kafka between Hub and Core.

### Bound the million-intent burst

**Pressure:** One million 2–4 KiB intents create 2–4 GB raw writes and take 8.55 hours at the measured 32.5/s versus 3.33 minutes at the stated target.

**Decision:** Preserve the PostgreSQL outbox, enforce per-account and global admission bounds, schedule fairly by account, and scale Hub workers horizontally only after Meta quota and provider-latency measurements justify it.

**Failure contained:** Retries amplify offered load while the provider slows, exhausting connections, WAL or disk and starving small accounts behind one hot tenant.

**Rejected:** Buffer the burst in process memory; Introduce a distributed log immediately.

## Migration

- Add activation_version/state and due schedule rows additively in Hub; old scan workers continue reading existing cursors.
- Deploy Core callback readers and dedicated projector workers before Hub writes the versioned callback envelope.
- Backfill due rows from unacknowledged cursors, compare shadow lag, then disable fixed account scans.
- Project Hub capability state into Core, stop manual Relay Channel writes, and retain rollback until every site reports ACTIVE through Hub.

Rollback remains available until the old scanner is disabled and Core channel writes are stopped. Schema additions and callback readers land before writers; no one-way message data migration is required.

## Architecture debt register

This audit is a survey of structural gaps, not an authorization to rewrite the system. Findings passed evidence checks and explicit attempts to refute them. Severity follows consequence × exposure.

| Severity | Finding | Remedy | Candidate A |
|---|---|---|---|
| blocking | Core and Hub can disagree about whether the WhatsApp channel is active | Make Hub the only activation authority and project a read-only capability state into Core. | resolves |
| blocking | Realtime message projection shares the slow queue with AI and reporting work | Create a dedicated high-priority projection queue and workers, with lag alerts and a durable Relay Hub Event recovery scan. | resolves |
| blocking | Account scanning cannot meet the realtime target at the stated tenant count | Replace full-account ticks with a transactional due account/lane index claimed fairly using SKIP LOCKED. | resolves |
| blocking | Measured provider drain is two orders below the stated aggregate target | Partition fair worker capacity by account, add horizontal Hub process scaling and admit only measured Meta quota; retain the PostgreSQL outbox. | resolves |
| blocking | Cross-repository callback changes have no explicit version and rollout contract | Version the callback envelope, require additive reader-first changes, and run cross-version contract tests before deployment. | resolves |
| medium | Durable event and message tables have no enforced retention steady state | Define and implement retention by state: raw acknowledged events, resolved outbox, uncertain work and business messages each need separate policy and deletion proof. | resolves |
| blocking | Database-disaster recovery targets are claimed without restore evidence | Automate backups and run a timed restore drill that replays Hub callbacks from durable cursors without duplicate business messages. | still requires operational work |

The audit checked: boundaries, data-ownership, coupling, dependency-contracts, failure-containment, over-engineering, obsolescence.

**Could not verify**
- change history before the visible September 2026 working tree: the material implementation is largely uncommitted and available git history does not establish when each decision changed
- live Meta provider quota, latency and account eligibility: production WhatsApp credentials are not configured for a measured end-to-end run
- production database backup and restore guarantees: no completed restore-drill evidence was found for Hub PostgreSQL or the Core site database

A repeated audit may find a different set of leads. Stable finding identities preserve human decisions when a finding returns; they do not claim the set is complete or convergent.

## Acceptance sequence

1. Implement and contract-test the Hub-owned WhatsApp activation state machine; make Core Relay Channel a derived read-only capability.
2. Add transactional due callback scheduling and benchmark 100 active plus 900 idle accounts against the p99 one-second inbound target.
3. Create a dedicated Core realtime projection queue/worker and measure callback commit-to-Socket.IO-visible latency under simultaneous AI/report load.
4. Version Hub callback envelopes and add reader-first cross-version tests spanning both repositories.
5. Run provider-backed outbound load tests to discover Meta quota and worker saturation; revise or prove the 5,000/s target before scaling infrastructure.
6. Define retention and execute PostgreSQL and MariaDB restore drills with callback replay and duplicate checks.

The WhatsApp feature is ready for live testing only after activation reaches `ACTIVE`. It is ready for performance acceptance only after the realtime latency, provider drain, saturation behavior, and restore tests above pass.
