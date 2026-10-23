# AI automation implementation checkpoint — 2026-09-22

> Historical checkpoint. For current behavior, use the [documentation index](README.md)
> and [support status](implementation-status.md). Counts and pending items below
> describe the original checkpoint, not the latest working tree.

This is a tested first backend slice of the reviewed plan, not completion of all six phases. Changes are local on develop and unpushed. Automation remains disabled on existing sites. No customer messages were sent.

## Implemented

- Durable Relay Automation Policy, Relay AI Provider, Relay Canned Reply, Relay Automation Run, Relay Automation Outbox and verified Relay Contact Endpoint records, with sequential names.
- Incoming WhatsApp Hub-event projection to deduplicated Relay Messages. Unknown endpoints remain Uncategorized; delivery-only callbacks do not trigger AI. Text automation only; unsupported media fails to handoff.
- Explicit manager enqueue and automatic after-insert hooks behind the `relay_automation_enabled` site switch. Site configuration alone is insufficient: channel, provider, endpoint verification, policy and least-privileged execution user must also be configured.
- Strict JSON action contract: ticket creation, selection from approved reply IDs and human handoff. No arbitrary tools, SQL, methods, reports or free-form AI-generated messages can execute.
- OpenRouter, Anthropic, Gemini and GLM adapters with fixed destinations, no redirects, bounded input/output, timeout, redacted errors and no automatic provider fallback. GLM uses the existing Z.ai Anthropic-compatible API shape.
- Default Shadow policy mode produces decisions without ticket/send effects. Automatic mode creates ticket and immutable outbound intent in one transaction. Stable keys and unique ticket/event constraints prevent duplicate replay effects.
- Two model slots per site, per-run Redis leases, database fencing, attempt and daily limits. Model calls occur outside write transactions; a fresh database snapshot rechecks policy after inference.
- Current contact/business-link permissions and verified endpoint checks. A Contact with several business links of the configured type hands off instead of guessing. Replies are blocked if the incoming number differs from the server-resolved primary recipient.
- Human takeover advances a conversation generation; older queued replies are cancelled. Revoked endpoint, changed reply, changed policy or newer incoming message also blocks queued dispatch.
- Outbox tracks Pending/Dispatching/Submitted/Uncertain/Cancelled/Conflict. Ambiguous sends are not blindly replayed. Expired Dispatching rows recover to Uncertain. Submitted means Hub acceptance, not confirmed delivery.
- Protected runtime records cannot be edited by injecting document flags. Core MCP exposes enqueue, bounded run search and takeover through the same permission-checked services.
- Lazy-loaded Automation view with database paging/search and separate decision/reply statuses. It displays an unavailable-backend message in the existing static preview instead of fabricated runs.

## Real integration validation

Created an isolated Frappe installation with a separate PostgreSQL database (`relay_ai_test_20260922`) and dedicated local Redis port 18089. Existing site databases and running bench services were not modified. The test database contains synthetic fixtures only. The temporary Redis service is stopped after validation; restart it before rerunning the fixture harness.

`tests/integration_automation_site.py` refuses a non-test database. Run it with the installed Frappe environment Python, repository on PYTHONPATH and RELAY_AUTOMATION_TEST_SITES pointing at the isolated sites directory. Models and Hub transport are stubbed in this harness; Frappe installation, DocTypes, permissions, inserts, commits, constraints, Redis locks and concurrent database workers are real.

Ten scenarios passed:
1. Ticket/outbox transaction, completed-run replay deduplication and single dispatch.
2. Invalid model-selected action cannot create a ticket or send.
3. Human takeover cancels queued output.
4. Ambiguous transport outcome becomes Uncertain and is not automatically replayed.
5. Forged document flags cannot bypass service-owned record protection.
6. Shadow decisions create neither tickets nor outbound intents.
7. Revoked endpoint cancels queued delivery.
8. Policy disabled during inference prevents action application.
9. Incoming-event projection is replay-safe.
10. Two concurrent workers produce one model decision and one ticket.

The concurrency test exposed a PostgreSQL serialization race; per-run admission locking was added and the test rerun successfully. Post-inference transaction refresh protects against stale PostgreSQL policy snapshots.

Unit suite: 44 tests run, 42 passed, 2 unrelated live Hub tests skipped. Frontend: 7 tests passed; production build passed. Playwright checked the Automation unavailable-backend state and no horizontal overflow at 375px.

A live GLM synthetic prompt was attempted through the production adapter and failed its bounded request/response contract. The adapter returned a redacted ProviderError. No live model quality or channel-delivery success is claimed.

## Not yet implemented / release blockers

- Full team assignment permissions and shared ticket assignment workflow. Policy/provider/reply editing remains System Manager-only in this first slice; manager publication workflows remain pending.
- Actual email/Telegram adapters, notification preferences and ticket-update delivery; report actions and artifact delivery are deliberately unavailable.
- Direct OpenAI/Codex production adapter, model fallback routing, voice/vision, learned guidance publication/evaluation and quality dashboards.
- Full external business-identity enrollment and expiring verification. Current endpoint verification is an explicit administrator-maintained allowlist, not automatic trust in a phone/email match.
- Secondary phone/email/Telegram endpoint routing beyond the guarded primary WhatsApp number.
- Automatic uncertain-send reconciliation, fine-grained Hub conflict mapping, delivery receipts surfaced in Core and a management UI for resolution. Uncertain rows require investigation; they are not called successful deliveries.
- Full input ordering, account fairness/global worker scaling, retention/deletion workflows, stale-attempt audit metrics and the plan's sustained load/canary gates.
- Scheduler recovery is currently once a minute, not the proposed 30 seconds. Existing public Core remains a static preview; the isolated integration site is not deployed there.

Do not enable this on production as a completed automation product. The tests establish the listed slice and failure boundaries only; the remaining plan is still outstanding.
