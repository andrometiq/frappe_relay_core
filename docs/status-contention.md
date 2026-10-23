# MariaDB callback contention investigation

Validated on yrp.site with Core based on `0b0c363`, Frappe 16.52.0 and
MariaDB 11.8.9. Changes remain uncommitted. No migration, DocType reload,
configuration change, service restart or production access was performed.

## Root cause

The failing transport is `relay_core.inbound.receive_statuses` (all 20 captured
failures), not `receive`. Both endpoints insert sequentially named Hub events.
They read before Frappe locks the shared `tabSeries` row `RELAY-EVT-`.
On this server, `REPEATABLE-READ` and `innodb_snapshot_isolation=ON` cause that
locking read to fail with MariaDB **1020** if another callback has advanced the
counter since the transaction's read snapshot. Frappe deliberately maps both
1020 and 1213 to `QueryDeadlockError`.

The focused reproduction captured 1020 on `tabSeries` from
`frappe.model.naming.getseries`, not a 1213 lock-order cycle. A deterministic
check establishes the first callback's snapshot, commits a second callback on
another connection, then resumes the first insert: the real database raises
1020 and the new callback boundary recovers it. This matches
[MariaDB's documented snapshot-isolation behavior](https://mariadb.com/resources/blog/isolation-level-violation-testing-and-debugging-in-mariadb/).

`SHOW ENGINE INNODB STATUS` was attempted on yrp.site; its DB user lacks PROCESS
privilege and no permitted admin connection was available. Therefore the retained
LATEST DETECTED DEADLOCK was not inspected. The server's `Innodb_deadlocks`
counter remained 1 while the focused runs repeatedly reproduced 1020 conflicts.

The `2b7efeb..HEAD` diff does not change `inbound.py`, `whatsapp_receipts.py`,
`message_updates.py` or `automation/projection.py`. The Telegram/email finish
changes are outside this WhatsApp delivery-receipt path. The automation drain
discovers Pending names with a nonlocking read, locks each message by its unique
primary key, and commits each message separately. There is no evidence here for
an automation-status-index gap-lock cycle, so removing that index or introducing
another pending table would not address the reproduced failure.

## Why the throughput number halved

The simulation's `status_projection_seconds` is elapsed time from the first job's
start to the last job's finish, including gaps between jobs. In the supplied run8
report, the storm's 24 projection jobs spent only **2.874 s** in projection,
**11.842 s** in worker setup, and **0.154 s** waiting in the queue. Their overall
span was **51.177 s**, with 20 failed status HTTP requests and Hub retries between
successful batches. This is a callback admission/retry problem, not doubled
per-receipt SQL work. The focused before/after runs each execute **312 projection
queries for 12,000 receipts**, with unchanged set-based updates.

The available evidence does not establish that either intervening commit caused
the conflict: the affected receiver and receipt SQL are unchanged. Increased
concurrency/timing exposes a transaction conflict already possible in that code.

## Fix and invariants

All three signed callback endpoints now retry their entire transaction on
`QueryDeadlockError`, at most five attempts with 10/20/30/40 ms backoff. MariaDB
aborts the transaction on a snapshot conflict; retrying an insert or savepoint
alone is insufficient. Frappe rollback refreshes the snapshot and discards
after-commit projection, automation wake and realtime callbacks. Successful
requests still commit through the normal Frappe POST boundary. Invalid requests
and other errors are not retried; exhausted retries still fail without an ACK.

Event identities, sequential names, receipt folding, endpoint/message locks,
modified timestamps and automation acknowledgement transactions are unchanged.
The benchmark verifies one committed wake after an injected failure *after*
inline insertion, event/message replay deduplication, a delayed Delivered receipt
preserving Read and modified, drain rollback/recovery, committed-hook replay
exclusion, and exclusion of a second drain connection.

## Focused measurements

| 12,000 receipts / 4,000 messages | Before | After |
| --- | ---: | ---: |
| Paced projection span | 35.900 s | 24.113 s |
| Receipts / projection-span second | 334.3 | 497.6 |
| Status callback errors | 8 | 0 |
| Inbound callback errors | 11 | 0 |
| Inbound p95, including retries | 184.85 ms | 110.21 ms |
| Successful inbound samples | 233 | 213 |
| Messages ending Read | 4,000 | 4,000 |

The additional unpaced after-run projected the storm over **2.411 s**
(4,977 receipts/s), completed in **2.719 s**, and had **zero escaped callback
errors**, despite 16 status and 10 inbound database conflicts. Inbound p95 was
**212.67 ms**, with 18 samples. All recovery assertions passed.

These are concurrent fresh-process site tests using real MariaDB, signed callback
functions, projection and drain handlers. RQ dispatch is replaced by an explicit
projection thread; realtime publication and external Hub calls are intercepted.
The paced run waits one second between status batches and one second after an
escaped conflict. These timings exclude live HTTP, Hub transport and RQ worker
startup; they are not a rerun of the full connected simulation. Existing web and
worker processes were not restarted or proven to have loaded the patch.

Run from Core with the actual bench interpreter:

```sh
../../env/bin/python -B tests/status_contention_site.py --receipts 12000 --output /tmp/relay-status-paced-after.json
../../env/bin/python -B tests/status_contention_site.py --receipts 12000 --pace 0 --verify --output /tmp/relay-status-burst-after.json
../../env/bin/python -B -m unittest discover -s tests
```

Reports: `/tmp/relay-status-paced-before.json`,
`/tmp/relay-status-paced-after.json`, `/tmp/relay-status-burst-after.json`.
The original report is
`/tmp/claude-1000/-home-sakthi-development-pilot/a8995608-2cdc-4735-9a21-e922e1a4db34/scratchpad/relay-p8/sim-run8-report.json`.
All local fixtures are retained with `local-status-` identities; no data was
deleted. The complete unit suite ran 288 tests: 283 passed, 3 skipped and the
2 known ffprobe/media errors remained in `test_multimodal`.

**RESTART NEEDED** for persistent web processes that have not automatically
reloaded Core before repeating the connected HTTP simulation. No worker logic
or DocType schema was changed.
