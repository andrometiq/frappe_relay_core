# UI and configuration iteration

## Implemented

- Restrained blue selection/reply accents and green/blue/amber channel labels.
- Contact-wide message view with channel filter and an explicit reply channel. Session draft creation and long-message expansion.
- Fixed-height virtual rows for conversations and contacts; viewport plus overscan only.
- Message rendering retains an 80-message DOM window, supports loading either direction, preserves the retained anchor, remembers conversation scroll positions (maximum 100), and avoids jumping to new messages while reading history.
- Channel navigation expands to settings; the preview intentionally exposes no editable credentials.
- Frappe metadata for Relay Channel, Relay Contact, Relay Message. Ten-digit Frappe naming series; Relay Communication Manager and Relay Communication User roles. Configuration writes require System Manager on the server; both communication roles can read, subject to Frappe permissions.
- Permission-aware cursor endpoint, capped at 100 messages per request. Bounded cursor-cache adapter (200 records) with cancellation and stale-response protection.
- Responsive adjustments for 320, 375, 768, 1024 and 1440 pixel widths.

## Validation and limits

Browser fixture: 2,000 contacts rendered with 16 mounted rows at an 850px viewport; end traversal reached Contact 1999. A 1,000-message fixture kept 80 mounted messages and loaded older history while retaining the visible anchor. Node tests traverse a synthetic million-record source without allocating a million-record array and retain at most 200 records.

The main frontend still uses session-only sample data. Virtual rendering bounds DOM size, **not** the source array. The cursor cache and Frappe endpoint are foundation pieces; production frontend/API integration, installer validation, durable per-user read receipts and real provider delivery remain unfinished. These measurements do not establish million-record production performance.

Existing WhatsApp Core read-state code was inspected read-only: it distinguishes provider receipts from operator reads and persists a per-user ledger. That distinction must survive migration. No installed app, production site or production data was changed.

Run browser fixture: `cd frontend && npx vite build --config tests/vite.config.js`, then serve `.scroll-test-dist` and open `/tests/scroll.html`. Unit tests: `node --test frontend/tests/*.test.mjs`; Python tests: `RELAY_LIVE_TEST=1 python3 -B -m unittest discover -s tests -v`.

## Local visual refinement (not pushed)

Conversation details now open on demand. Channel filtering uses compact tabs;
reply-channel selection lives in the composer. Folder creation is disclosed on
request. Conversation rows are more compact, bubbles fit their content, and
mobile conversation mode hides list controls while retaining the back button.
