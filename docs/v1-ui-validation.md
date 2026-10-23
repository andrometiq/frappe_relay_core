# WhatsApp v1 UI validation

Status: uncommitted work on `feat/v1-ui`, prepared for orchestrator review.
This is not installed-site or release acceptance.

## Implemented

The six installed screens and their contents are listed in
[frontend/README.md](../frontend/README.md). Both frontend entry points now mount
SiteApp. Removed unused preview and out-of-scope Vue screens; legacy backend
operations and tested shared rendering components remain. Desk workspace source
now links to the six real routes. No DocTypes, tables, records, dependencies,
credentials, site configuration or production state were changed.

Contact switches clear the recipient, quote, text, attachment and structured
message draft. Search/deep-link switches follow the same rule. Uncertain sends
use existing reconciliation; only server-confirmed rejected actions expose the
existing reviewed retry path. Templates remain available outside the 24-hour
reply window. Communication team membership and business-group responsibility
have separate views.

Read-only backend additions are limited to permission-checked contact/link and
endpoint readback, bounded account-scoped callback receipt/projection state, and
server-side Mine/WhatsApp queue filtering (including WhatsApp unread counts).
Existing mutation endpoints are reused unchanged.

## Evidence

- `node --test frontend/tests/*.test.mjs frontend/tests/*.test.js`: 59 passed.
  Includes real local Socket.IO reconnect/burst invalidation, standard Frappe
  list-update invalidation, contact reset and safe server-error extraction.
- `python3 -B -m unittest discover -s tests -p test_api.py`: 9 passed, including
  inaccessible business links and assignment-denied endpoint reads.
- `npm run build` and `npm run build:site`: passed using the existing dependency
  symlink, writing assets only inside this worktree.
- Browser fixture acceptance: six screens at 320/390/640/768/1440px, no horizontal
  page overflow; persistent notifications; mobile drawer and template cards;
  three linked contacts (one without history); non-zero unread and order data;
  clear draft/quote context; rejected-send review/retry; server validation errors;
  empty/error contact searches; restored business-group deep link.
- Review regressions: unread queues refresh on socket `reads` events and after
  successful local read mutations (including during socket reconnection); failed
  reads and presence-only writes do not invalidate queues. Mixed-contact business
  timelines pass only the selected contact's messages to read controls, and notes
  use the clicked message's contact independently of the sending recipient.
  Sending to another contact opens that conversation and updates the URL.
  Notification links open notes after history loads, including reopening the same
  contact; the one-use notes parameter is consumed. Direct-contact navigation
  clears business title/count context. Teleported dialog/menu controls have at
  least 40px touch targets on desktop and mobile.
- Full Python discovery with system Python: 132 discovered in the initial run,
  19 errors due to unavailable `frappe`, two opt-in live-Hub skips. This is not a
  passing full backend suite. No live-Hub tests were enabled.
- No polling introduced. No provider or customer delivery was exercised.

Browser fixtures are synthetic and all API requests are intercepted. They do
not replace representative seeded records and authenticated browser/API checks
on an actual development site. Screenshots and raw local logs are ignored under
`.runtime/`.

All seven findings in the full reviewer output were confirmed and fixed. No
backend API, schema, dependency or site changes were needed for these fixes.
The previous review's sandbox failures did not recur: the actual Node transport
test and both disk-writing builds passed in this worktree.

## Remaining backend and environment gaps

- Callback forwarding attempt history and acknowledgement errors are Hub-owned.
  Core stores receipt/projection status but no detailed projection failure reason.
  The UI identifies that boundary rather than claiming a saved secret proves
  callback delivery.
- Number identity/quality and template rejection details depend on Hub/Meta
  metadata being present. Missing values are labeled explicitly. Pacing controls
  have no existing Core API and remain in Hub administration.
- Account-wide Hub delivery rows do not expose a guaranteed Core conversation
  reference. Failed Core messages have drilldowns; contact-scoped Message activity
  provides reconciliation and reviewed retry. Uncertain Hub-only rows must be
  investigated with Hub diagnostics.
- Endpoint readback exposes verification and creation/update timestamps; the
  current schema does not record a structured enrollment/provenance reason.
- Contact masters, channel setup, business types/grouping, saved-reply editing and
  user permissions use real Frappe Desk forms. Their existing server permissions
  apply; this change does not widen configuration privileges.
- The available Frappe 16.52.0 bench has `whatsapp-hub.site` in developer mode but
  points at `/home/sakthi/development/pilot/benches/version_16/apps/relay_core`, not
  this worktree. Changing it would violate the task's filesystem boundary.
  The exact isolated validation site has been requested from the orchestrator.
- Desk shortcut source changes require an approved migration on that exact site.
  No migration, site-config change, fixture export, bench-wide build, process
  restart, commit or push was performed. Actual bench build, backend reload,
  permissions, database queue queries, callback recovery and representative
  happy/failure/load cases remain to be verified there.

## Proposed commits

See [the exact file manifest](v1-ui-commits.md). Every proposed commit body ends:

```text
Co-Authored-By: Codex <noreply@openai.com>
```
