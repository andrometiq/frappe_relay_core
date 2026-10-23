# Test Relay Core

Run simulations before using provider credentials. These tests use synthetic
contacts, provider fixtures, and a separate database; they do not send customer
messages.

## Fast contracts

From the Core repository, using a Python environment with the required packages:

```sh
python3 -B -m unittest discover -s tests -v
node --test frontend/tests/*.test.mjs
```

Two opt-in live-Hub smoke tests are normally skipped unless `RELAY_LIVE_TEST=1`.
Do not treat those skips as provider validation. Unit tests alone do not exercise
Frappe transactions and installed permissions.

Build the frontend from `frontend/`:

```sh
npm ci
npm run build
```

## Database and provider simulations

The combined runner lives in the sibling Hub repository. From that repository:

```sh
python3 scripts/simulate.py \
  --core ../frappe_relay_core \
  --frappe-python /path/to/test-bench/env/bin/python \
  --sites /path/to/isolated-test-sites
```

The current harness deliberately accepts only the named fixture site
`relay-ai-test.local`, database `relay_ai_test_20260922` on
`127.0.0.1:18433`, and Redis on `127.0.0.1:18089`. It reads credentials from that
fixture's private site configuration, never the Hub production `.env`. It is
a guarded developer harness, not an arbitrary-site test command. Prepare the
isolated fixture first; do not point it at an existing business site.

The runner checks Go with the race detector and static analysis, Core contracts,
real Frappe/database scenarios, frontend data tests, and whitespace. It rejects
skipped Hub integration tests. It saves results to the Hub's ignored
`.runtime/simulation-report.json`. Use that report for the exact current counts
and command results.

## Evidence boundaries

| Layer | Real components | Simulated components |
| --- | --- | --- |
| Hub integration | PostgreSQL, authentication, MCP, outbox, event journal, routing | Provider HTTP responses and media |
| Core integration | Frappe DocTypes, permissions, transactions, constraints, Redis locks | Model decisions and Hub/provider fixtures |
| Browser tests | Built Vue components, rendering, bounded loading and lifecycle | Synthetic messages and media |

The tests verify payloads, routing, deduplication, scope isolation, reactions,
failure handling, and bounded media behavior. They do not prove provider account
eligibility, real customer delivery, model answer quality, or production load
capacity. See Hub's
[simulation guide](https://github.com/andrometiq/relay_hub/blob/develop/docs/simulation-validation.md)
and [group coverage](https://github.com/andrometiq/relay_hub/blob/develop/docs/group-simulation-coverage.md).

## Test changes

Add a contract test when an API's allowed fields or error behavior changes.
Use database integration tests for permissions, concurrency, replay, and stored
state transitions. For UI media work, check actual browser decoding and cleanup
in addition to a production build. Record failures and limitations as well as
successful runs.
