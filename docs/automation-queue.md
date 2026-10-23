# Inbound automation drain

`Relay Message.automation_status` is a hidden, read-only Select with an index.
The controller sets `Pending` during insertion for new incoming, non-legacy
messages. Outgoing/imported messages and pre-existing history remain blank.
There are no policy reads, Redis operations or automation hooks in this step.
The marker commits atomically with the message, covering death before the
post-commit callback. Only that callback signals the default queue.

A site-scoped Redis NX reservation coalesces signals into one waiting drain.
It expires after 120 seconds to recover a process lost during enqueue. Each
reservation has its own job ID: a fixed RQ ID deduplicated while STARTED would
lose a wake-up arriving after the drain's final empty read. The reservation is
released, with a token comparison, when its job starts. Arrivals can reserve one
successor while the current drain runs. An expired reservation can leave a
redundant job, but cannot duplicate committed hook effects.

A MariaDB connection-owned advisory lock serializes drains for the site. They
read 100 pending names at a time, ordered by creation and name, and commit each
message's intents and `Complete` marker together. Paused contacts skip AI before
skill lookup/contact locking; translation, flow and email retain their independent
guards. Hooks only create transactional intents or after-commit work; they must
not commit or perform external delivery themselves. Uncommitted work is retried
after worker death; committed work is never replayed. Actual downstream jobs
retain their existing journals and guards.

The drain yields after five seconds between messages so downstream AI jobs can
run during sustained ingress. This does not bound an individual slow hook.
The existing minutely automation recovery wakes pending message work even when
the AI gate is off. Redis outages leave SQL markers intact. A hook exception
rolls back that message and fails the drain; recovery retries the oldest pending
message, preserving ordering. A persistently failing hook therefore requires
repair before later messages can advance. No failure is silently acknowledged.
Existing per-message RQ jobs use a compatibility entry point to join this drain;
historical messages are not bulk backfilled.

## Local verification — 2026-10-24

On `yrp.site`, Frappe 16.52.0, with exactly one existing default worker separated
from short/long projection workers:

| Measurement | Result |
| --- | ---: |
| 300 incoming messages, half paused and half without a skill | 1.641 s, one RQ drain job |
| Old measured 0.46 s/job × 300 | 138 s (baseline estimate) |
| AI intent behind a separately committed 300-message backlog | 1.543 s |
| AI worker completes Shadow decision through loopback HTTP provider | 2.111 s |

These include queue pickup and worker startup. The benchmark inserts real
messages through normal DocType hooks. It uses linked local business/contact
fixtures, an enabled Shadow skill, meaningful quantity/amount text and a
loopback AI provider. It verifies outgoing/imported exclusions, no duplicate AI
run after replay, and concurrent-drain exclusion with a second process.
Another process exits after creating an AI intent and completion marker but
before commit: neither survives; recovery creates exactly one committed run and
one provider call for that message. Two provider calls total cover the normal
and recovered messages. Records are retained with prefix
`Local queue benchmark 1792796729740340992`; its skill was disabled afterwards.

Reproduce from the Core repository, with the existing isolated workers running:

```sh
../../env/bin/python -B tests/automation_queue_site.py
../../env/bin/python -B tests/test_automation_queue.py
../../env/bin/python -B -m unittest discover -s tests
```

The explicit site benchmark is intentionally excluded from unit discovery. It
only targets `yrp.site`, retains identifiable test records, and does not restart
services, change site configuration, migrate, export fixtures or send messages.

## Activation

Already executed on **yrp.site only**:

```python
frappe.reload_doc('relay_core', 'doctype', 'relay_message', force=True)
frappe.db.commit()
```

Verified the `automation_status` column and `automation_status_index`. No other
DocType was reloaded. The existing default worker successfully executed the new
drain and downstream AI job. **RESTART NEEDED** for web processes that cache the
old controller/decorator before full connected HTTP acceptance. No service was
restarted. The full WhatsApp simulation has not been rerun for this change;
its independent receipt-deadlock failure is documented in Hub's simulation log.
