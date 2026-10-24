# Backend review validation — 25 October 2026

Changes remain uncommitted on the approved `tmp/fix-be` worktree. No frontend
files, installed app sources, site configuration, fixtures, production data,
or Git state were changed. No migration, fixture export, build, push, or
production mutation was run.

## Independent review findings

| Finding | Result and evidence |
| --- | --- |
| DocShare bypass | Fixed. Independent business/assignment checks protect contact reads and recipient checks. Contact search adds its business condition outside Frappe's share override, before pagination. HTTP takeover and discovery deny after revocation while the share remains. |
| Shared Telegram administration | Fixed. Group/topic operations require all linked businesses to be readable because observed Telegram topics have no authoritative business mapping. Shared Customer/Supplier HTTP requests return 403 with zero Hub calls. |
| Notification permission exceptions | Fixed. Source access denial rolls back the event savepoint without aborting the business insert; deadlocks propagate to transaction retry. Real order inserts with a revoked execution user succeed without a delivery. |
| Handoff lost before journal creation | Fixed. Assigned ticket, automation pause and Handoff state commit before confirmation delivery. A 24-hour wait followed by a closed window and replay retains exactly one assigned business ticket without a send. Confirmation journals retain flow/version/generation checks. |
| Email intent starvation | Fixed. Attempts and next-attempt time are durable; recovery prioritizes fewer attempts; permission/missing-document denials are terminal and retryable failures stop after six attempts. A healthy new recipient sends after 30 denied intents. |
| Missing UI business context | **NOT FIXED in frontend:** frontend edits are explicitly assigned to another worktree and prohibited here. The APIs accept explicit business context and have HTTP success/deny coverage. Replies without selected messages inherit an authorized parent's business. New unreferenced notes, manual cases and empty topics still require the frontend job to pass its active pair. |
| Old collaboration imports | Fixed. Re-import backfills absent business fields only when an authoritative source baseline proves ownership, preserving local edits and existing explicit scopes. Unit and real old-baseline upgrade tests pass. |
| Old supplier-ledger contracts | Fixed. The reader obtains company from the same permission-checked documents, checks column permission, and preserves the persisted contract. A real persisted old contract returns company and non-zero totals; mixed/missing companies fail closed. |
| PostgreSQL drain | Fixed in code. Session advisory locks survive commits and release on success/failure; contention reschedules. Unit tests cover those paths. No PostgreSQL server was available for live verification; yrp.site uses MariaDB. |
| Missing fix verification | Fixed. Unit suite, populated site scenarios and authenticated HTTP success/deny tests were executed with this worktree first on PYTHONPATH. See results below. |

Frontend request contract:

- `relay_core.collaboration.add`: top-level `business_doctype`, `business_name`.
- `relay_core.cases.create_manual`: top-level `business_doctype`, `business_name`.
- `relay_core.topics.save`: the same pair inside `values`.

Never choose the only business readable by a user when the identity has several
linked businesses. The active UI selection must be explicit.

## Original findings-be.md disposition

| Number | Finding | Result |
| --- | --- | --- |
| 1 | Unresolved quoted parent | Fixed: triage instead of previous/single-business fallback. |
| 2 | Poison receipt batch | Fixed: per-row rollback and deadlock propagation. |
| 3 | Provider-ID length | Fixed: full 300-character storage. |
| 4 | Early projection invalidation | Fixed: Socket.IO invalidation after failure/triage transitions. |
| 5 | Swallowed business-event database errors | Fixed: savepoint isolation, propagated deadlocks, whole delivery transaction retries, event-key names without a shared delivery series. |
| 6 | Standard ticket reads | Fixed: business and message scope for owners, assignees and managers. |
| 7 | Flow business scope | Fixed: scoped read/list/cancel/responses. |
| 8 | Assigned handoff ticket | Fixed: one assigned business ticket, durable before notification. |
| 9 | Automatic email scheduling | Fixed: durable intent and bounded retry schedule. |
| 10 | Cancelled flow delivery recovery | Fixed: persisted flow/version/generation checks, including handoff confirmations. |
| 11 | Concurrent skill activation | Fixed: unique active scope; concurrent stale-snapshot test permits one owner. |
| 12 | PostgreSQL drain | Fixed; session-lock unit tests pass, no live PostgreSQL validation. |
| 13 | Follow-up ahead of flow worker | Fixed: pending flow events claim follow-up input. |
| 14 | Stale event-rule cache | Fixed: bounded cache lifetime. |
| 15 | Cross-company ledger totals | Fixed: company validation, including old contracts. |
| 16 | Model discovery identifiers | Fixed: enabled AI Models/accounts; discovered identifier used in HTTP draft request. |
| 17 | Account-wide delivery administration | Fixed: Administrator-only before Hub calls. |
| 18 | Telegram administration | Fixed: verified binding and every affected linked business. |
| 19 | Native ticket read bypass | Fixed; native HTTP read/list denial verified. |
| 20 | Native auxiliary record access | Fixed: Administrator-only internal records. |
| 21 | Notification note leakage | Fixed: preview and recipients use full note authorization. |
| 22 | Flow answers/cancellation | Fixed; shared-business HTTP denial verified. |
| 23 | Case business ownership | Fixed: persisted business pair or authorized source-flow fallback. |
| 24 | Contact discovery/takeover | Fixed, including existing DocShare revocation. |
| 25 | Business directory previews | Fixed: permitted message queries and validated summaries. |
| 26 | Stale legacy sends | Fixed: import revision ordering/conflict retention. |
| 27 | Imported collaboration ownership | Fixed in backend and re-import upgrades; new UI creation wiring remains with the frontend job. |
| 28 | Native outbox reads | Fixed: internal-record hooks and removed manager grant. |
| 29 | Long email identities | Fixed: full provider IDs/endpoints insert successfully. |
| 30 | Source-local timestamps | Fixed: source-to-target timezone conversion, including related history. |
| 31 | Obsolete integration mocks | Fixed: current adapter/skill/journal scenarios replace retired policy-runner entrypoints. |

## Execution and results

Environment: Frappe 16.52.0, MariaDB, developer mode enabled, `yrp.site`.
Python: `/home/sakthi/development/pilot/benches/version_16/env/bin/python`.
Sites: `/home/sakthi/development/pilot/benches/version_16/sites`.
Site tests use the worktree followed by its `tests/` directory on `PYTHONPATH`,
`RELAY_TEST_SITE=yrp.site`, and `RELAY_AUTOMATION_TEST_SITES` set to the sites path.
Delivery, model calls, email and background enqueueing are intercepted locally.
Fixtures use identifiable local-only records and real permission checks.

The requested `python -B -m unittest discover -s tests` ran 388 tests:
383 passed, 3 skipped, 2 pre-existing ffprobe errors in
`test_audio_duration_and_malformed_media` and
`test_transcription_fixed_host_bounded_json_and_redaction`. No new unit failures.

Passed site suites: `integration_backend_findings_site.py`,
`integration_business_events_site.py`, `integration_ai_permissions_site.py`,
`integration_legacy_site.py`, `integration_multimodal_site.py`,
`integration_channel_identity_site.py`, `integration_channel_routing_site.py`,
`integration_channel_start_site.py`, `integration_channel_permissions_site.py`,
`integration_telegram_recovery_site.py`, `integration_ticket_notifications_site.py`.
The compatibility entrypoints `integration_automation_site.py`,
`integration_channels_site.py`, `integration_groups_site.py`, and
`integration_message_types_site.py` also completed successfully.

The older `integration_collaboration_site.py`, `integration_topics_site.py`,
`integration_cases_site.py`, `integration_flows_site.py`,
`integration_business_groups_site.py`, and `integration_telegram_topics_site.py`
refused yrp.site at their existing sandbox-site guards. Those guards were not
weakened. The affected business-scope, flow, case, note and topic scenarios are
exercised by the populated backend HTTP suite on the authorized site.

Shared-site snapshot conflicts on `tabSeries` occurred during some initial runs.
The event delivery path now retries whole transactions on deadlocks. Callback
fixtures use the actual retrying projection worker and fresh request transactions.
Affected suites were rerun; successful results above are from completed runs.

## Schema activation and process reload

Reloaded from this worktree with `frappe.reload_doc` on yrp.site:

- Relay AI Skill
- Relay Automation Outbox
- Relay Business Event Delivery
- Relay Business Routing
- Relay Campaign Recipient
- Relay Case
- Relay Contact Endpoint
- Relay Conversation Topic
- Relay Internal Comment
- Relay Message

All changed DocType JSON files have increased `modified` timestamps.
`git diff --check` passes.

**RESTART NEEDED:** web and worker processes must load the integrated backend
changes after the orchestrator applies them. Verification used fresh Python
processes and an authenticated local WSGI server loading this worktree; it does
not imply that the existing bench web/worker processes have switched source.
