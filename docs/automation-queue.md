# Inbound automation drain

Relay Message stores a hidden `automation_status` marker. Insertion marks new incoming messages Pending. Outgoing messages and imported history remain unmarked. The marker commits with the message. The callback after commit signals the default queue. Model work does not run in the ingress callback.

A site reservation in queue Redis combines the wake token, RQ job, and queue entry in one WATCH/MULTI/EXEC transaction. Read diagnostics from the default queue connection, not cache Redis. The reservation expires after 120 seconds. Each reservation uses its own job ID. A drain releases only its own token when it starts, so a new arrival can reserve a successor while that drain runs.

A connection-owned database lock serializes drains. A contender that cannot acquire the lock signals a successor before it returns. The drain reads up to 100 Pending messages in creation and name order. It commits each message's intents and Complete marker together. Death before commit rolls both back. Recovery can then create one committed run and episode.

The drain creates transactional intents through the existing hooks. Matching, model work, searches, and execution run outside the site drain lock. The shared admission path prevents a flow and an event from answering the same message. It creates the ticket before event tools run. Staff ownership cancels AI work for the held episode.

The drain yields after five seconds between messages so downstream jobs can run during sustained ingress. This limit does not bound one slow hook. A configuration validation error rolls back the partial intents, records triage or a recoverable ticket intent, and acknowledges the source. Other hook errors roll back the message and fail the drain. Recovery retries the oldest pending work. A persistent unexpected hook error requires repair before later messages can advance.

The existing scheduler calls recovery. Redis failure leaves SQL markers intact. A lost connection after Redis EXEC can leave an uncertain acknowledgement, but it cannot publish only the reservation. Do not remove that reservation on an ambiguous error. Message journals retain their own stable keys, permission checks, generation checks, and receipt recovery. Existing per-message jobs join this drain through a compatibility entry point. Historical messages are not bulk backfilled.

## Local acceptance commands

Use the bench Python with this worktree first on PYTHONPATH. These commands target only `yrp.site`:

```sh
cd /home/sakthi/development/relay-wt/core-aiev3
export PYTHONPATH=/home/sakthi/development/relay-wt/core-aiev3
/home/sakthi/development/pilot/benches/version_16/env/bin/python -B -m unittest discover -s tests
/home/sakthi/development/pilot/benches/version_16/env/bin/python -B tests/integration_ai_permissions_site.py
/home/sakthi/development/pilot/benches/version_16/env/bin/python -B tests/integration_ai_events_site.py
/home/sakthi/development/pilot/benches/version_16/env/bin/python -B tests/automation_queue_site.py
```

Run these commands in sequence. A queue run concurrent with schema reload checks encountered MariaDB error 1020 on the shared naming series and failed. The run after those checks passed. Concurrent schema activation is not covered by this acceptance result.

The queue test uses a separate RQ queue and fresh local workers. It restricts drain queries to its own channels. It creates readable Sim fixtures with a run label, an authenticated email endpoint, a linked Supplier, a Company, and an enabled Ticket only event. The messages contain amount 1250. It deletes all inserted fixtures, including child-process records, and removes its own queue jobs. It does not depend on retained simulation companies or accounts.

The test covers 80 independent event episodes, atomic wake publication, a queue Redis outage during the message commit callback, competing drains, replay, and process death after ticket/run/ack writes but before commit. Recovery must leave exactly one run and ticket per source. Ticket only events must create no outbound action. The test injects Redis errors at the queue boundary; it does not stop the shared Redis service. It kills only its own child process.

The event acceptance script also runs the existing populated matching, search, draft, takeover, and delivery suites. They use the real Frappe HTTP application and database. External model and transport responses are controlled. The draft checks create normal Payment Entry drafts with linked accounts, verify `docstatus = 0`, and delete them after the test. Permission probes include two companies, shared party names, changed bindings, changed fields, and query denial. Delivery races use independent database connections.

## Activation evidence

The review run completed 80 independent episodes in 18.101 seconds. Ticket creation took 7791.53 ms at p95, including backlog wait. Run completion took 17360.45 ms at p95. A staff claim took 25.84 ms. All runs completed with one ticket per source and no outbound actions. No model call occurred in this Ticket only load run. Redis failure, process death, drain contention, and replay checks passed. The permission and event acceptance suites passed, including real non-zero drafts and delivery races. Cleanup assertions confirmed removal of inserted fixtures.

The checks use `yrp.site` on Frappe 16.52.0 with developer mode enabled. Relay Core resolves to this worktree. Core unit discovery ran 550 tests with three skips: a separately initialized site test class and two opt-in live Hub tests. The audio tests passed using ffprobe and its required libraries extracted under this worktree's ignored `.runtime` directory, with PATH and LD_LIBRARY_PATH set only for the test process. Frontend unit tests passed 113 checks. Fourteen existing Hub simulation contract tests passed with the Hub scripts read-only. The populated Core search suite also passed the existing single-event supplier-ledger offer/yes/reference-tool protocol.

The takeover, delivery, event editor and ticket history suites pass through actual local Frappe HTTP and worker paths. They cover retained holds after ordinary closure, explicit release, manual business-composer takeover and journal rollback, a claim during image observation, unresolved routing-prompt suppression, delayed chat/email receipts, suppressed lifecycle notices, paginated delivery permission checks, and saved reply style in preview and live model prompts. The browser checks retain 60 real transcript messages and multiple history pages through Socket.IO invalidation and reconnect, verify permission-revocation clearing, and check that the UI does not poll. Both browser acceptance fixtures pass with the actual paginated API shapes.

Relay Core frontend assets were built in this worktree and served by the local site harness. The event suite reloads Relay Channel, Relay Ticket, Relay Message, and Relay Automation Run from this worktree. The delivery suite also reloads Relay Business Event Delivery. The three uncommitted DocType JSON revisions have newer modified values and were reloaded again after the final revision. No migration, fixture export, site configuration change, other-app edit, production write, service restart, commit, or push was performed.

RESTART NEEDED for existing web and worker processes before connected Hub acceptance. Fresh WSGI processes and isolated RQ workers prove this checkout's local behavior; they do not prove that installed services use it. The orchestrator must activate the reviewed changes and affected Relay Core assets, then verify the installed target UI and Socket.IO updates. The full connected Hub supplier-ledger simulation and real-provider latency remain separate acceptance checks. The isolated load result measures ticket admission and processing, not model inference or provider delivery latency.
