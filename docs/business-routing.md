# Business references and inbound routing

Relay business names are historical Data references. Deleting, cancelling,
renaming or updating a business must not depend on Relay history. Every packaged
Relay DocType is exempt from Frappe delete checks; cancel hooks extend the
business document's existing exemptions before and after its controller runs.
Other business backlinks still apply. Messages and tickets remain stored; normal
business access checks still govern reads. Historical names do not follow renames.

`business_routing.resolve` owns inbound decisions. Authenticated reply context is
scoped to the contact, channel, endpoint and conversation. A single current link
is unambiguous. Otherwise a validated sender selection or the conversation's
saved selection applies. Manager assignments go through the existing triage API
and the same resolver. Each projected message records `business_rule` in its
provider context; unresolved events retain per-message `routing_decisions`.
Sender-choice tokens are validated before single-link fallback, so removing a
choice cannot silently route its reply to another business.

The channel-neutral Relay Business Routing record stores explicit selection and
prompt state. A database lock on the verified Relay endpoint serializes decisions
without locking business documents. Selection is revalidated against current
contact links. Earlier unresolved messages stay in triage, except the specific
message that prompted the sender's choice. Following events use the selection.
Routing state uses locking reads after the endpoint lock to see committed choices
even when a worker already has a database snapshot. The selection's event and
position also route later messages within that batch without reassigning earlier
messages when the batch is replayed.

Private WhatsApp conversations with 2–10 businesses and fresh provider timestamp
evidence get one list prompt. The window is capped by local event arrival time.
Choices contain only that contact's current enabled business links and opaque IDs.
Forged, revoked, cross-conversation and consumed selections cannot select a business.
Groups, unsupported prompt channels, oversized lists and expired/missing window
evidence remain in manager triage. Sender choices retain their interactive type
so they do not act as text replies to a business flow.

Prompts use Relay Message Action with an immutable request key. The prompt and
its result remain in the manager-only journal because it has no selected business.
The worker runs only this internally created action as Administrator and restores
its original identity. Existing delivery lookup, callbacks and recovery apply;
expired or revoked prompts are rejected, uncertain attempts are never blindly
resent, and rejected prompts cannot be manually retried. Browser updates continue
to use existing Socket.IO invalidations.

## Validation boundary

The Core adapter currently assumes `whatsapp.execute` accepts
`operation=messages.interactive` with a Meta-shaped `interactive` list object.
This Hub contract has **not been verified**; Core's existing public send interface
does not expose it. Confirm the operation and argument shape against the owning
Hub implementation before enabling this feature. Local tests mock that boundary
and do not establish provider delivery.

Schema activation requires migration of the target development site. No migration,
fixture export or site configuration change was run for this work. `yrp.site` has
`allow_tests=False`, so the lifecycle database tests were skipped. Those tests
require an initialized local test site with tests already enabled and create a
reusable custom `Relay Reference Test Business` fixture; individual test records
are rolled back. Runtime activation, database concurrency, actual UI/API/background
job integration and provider delivery remain unverified.

Review validation: 85 focused Python tests passed with the site lifecycle class
skipped; all 55 Node tests and `npm run build` passed. Full Python discovery
reported 172 tests, two audio-test errors because `ffprobe` is unavailable, and
three skips (the site lifecycle class and two opt-in Hub tests). Unit regressions
cover revoked choices after link removal, committed-state reads and ordering
within a multi-message webhook batch; they do not prove database concurrency.
