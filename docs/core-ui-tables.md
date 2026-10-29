# Core tables and forms

Current access: [business type assignments](business-access.md). Team controls and group claims are hidden; team-related descriptions below refer to retained legacy implementation.


Contacts, Teams, Flows, Campaigns, canned replies and recent conversations share `RelayTable`. It defines columns and cell slots, keeps the header fixed above a vertically virtualized body, and contains horizontal scrolling inside the table on narrow screens. Inbox rows share its `PagedRows` paging implementation.

`PagedRows` uses the existing `createPageWindow` with 50-row pages and a 200-row maximum buffer. Rendering follows viewport height plus overscan. Forward and reverse page changes retain a visible row anchor. Request generations and abort signals protect against stale responses; search/filter changes reset the cursor. Earlier/more buttons provide explicit paging alongside automatic scrolling. Unread membership changes reset the inbox list while the existing conversation timeline preserves its own reading position.

`RelayForm` composes `DocumentForm` and dedicated field components. Campaign/canned-reply forms use form-level validation. New-conversation and team forms now use the shared field layout. WhatsApp/general workspace chunks remain lazy-loaded. This change does not rewrite every specialized WhatsApp input or flow-builder control.

Fuzzy search uses ordered-character matching in Contacts, Inbox, Teams, Flows and draft lists (for example `akmr` matches Asha Kumar). This is not arbitrary typo correction.

The public Core UI remains a preview. `arrayPageSource` adapts its small in-memory sample collections; it is explicitly not a production million-row data source. A real backend adapter implements `fetchPage({cursor, limit, query, signal}) -> {items, previous, next}` with server-side permissions/search and stable record cursors. Virtualization does not make an already-loaded full dataset memory-efficient; live-site data fetching remains integration work.

Validation:
- Six frontend tests pass, including million-record generated cursor traversal without allocating the dataset, stale-response rejection, fuzzy search and reverse boundaries.
- A built browser harness used a generated million-record source. After 13 page requests, each request was at most 50 rows, the cache held 200 rows, and 15 rows were mounted at the tested viewport. Reverse loading preserved the visible anchor. This is a synthetic frontend bound test, not live database throughput or a traversal of every row in the browser.
- Public Contacts table passed fuzzy search and viewport checks at 375/768/1440px; narrow widths scroll the table without widening the page.
- No production data was written. Temporary harness server/files were removed; the artifact remains under ignored `.runtime`.

Renderer update: see `frappe-virtualization.md`. Visible-row calculations now belong to the exact HyperList dependency used by the inspected Frappe DataTable; `PagedRows` retains only data paging and page-anchor restoration. Earlier custom-renderer counts above describe the baseline, not a fixed DOM limit of the upstream engine.
