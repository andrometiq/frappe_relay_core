# WhatsApp Core history cutover

The importer writes history directly in batches of 50, bypassing message,
File, collaboration, AI, notification and provider hooks. Historical Pending
messages have no send action. Importing does not enroll a verified endpoint,
provision credentials, switch routing, or change the source. Business record
names remain Data fields and the existing Relay backlink exemptions apply.

## Source snapshot and deltas

Run source exports as a System Manager with the **worktree first on PYTHONPATH**.
Use the bench Python and sites working directory. Keep source transactions
read-only; for a site-wide snapshot use:

```python
frappe.init(site=source_site)
frappe.connect()
frappe.db.sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
frappe.set_user('Administrator')
watermark = str(frappe.db.sql('SELECT CURRENT_TIMESTAMP(6)')[0][0])
```

Call `relay_core.legacy_bundle.export_conversation(conversation, destination,
watermark=watermark)` for every source conversation. Each private ZIP contains
at most 500 complete message rows, original identity/link/conversation/staff
history, derived template renderings, and streamed File attachments. Pass the
returned `next`, `upper`, and `watermark` as `after`, `upper`, and `watermark` to
export subsequent segments. Cursors are `(creation, name)` pairs, never names
alone. Finish with `frappe.db.rollback()` and `frappe.destroy()` on the source.

For each delta pass, capture a new watermark and export **all conversations**
again, with `since=previous_watermark`. The inclusive `modified >= since` filter
finds changed old rows and new rows even when their hash names sort earlier.
Retain the new watermark for the following pass. Do not reuse the previous
snapshot's upper cursor for a new delta. Same-site imports use the same ordering;
create a new Relay Legacy Import with **Delta from (inclusive)** set to the prior
pass watermark. Replaying a pass is safe. A stale revision is listed instead of
overwriting a newer imported revision.

A live cutover requires freezing **all** source writers, including send completion
and media caching, then a **full frozen export** of every conversation. Call
`export_conversation(..., frozen=True)` on every segment, starting each conversation
with fresh `after`/`upper` cursors. This mode ignores both modified bounds, even if
`since` is supplied. Legacy outbound completion uses SQL without advancing
`modified`; media caching uses `update_modified=False`. Deltas cannot capture these
changes reliably and are never the final cutover pass. Use portable frozen bundles
for this final pass, including for a same-site migration.

Import the full frozen bundles and reconcile all source identities, payloads,
statuses and attachment bytes against the target. Check total identity parity to
flag deleted source rows or extra target rows; do not silently delete history.
Keep the old apps read-only until this full comparison succeeds.
Drain/reconcile existing old outbound work separately and ensure one sender owns
each sending number before enabling the new channel. This importer never drains,
resends, or adopts historical outbound work.

## Destination mappings and the Desk report

Use one explicit Relay Channel/new Hub account mapping per source sending number.
The original channel, phone-number ID and old Hub account mappings are retained
in **Original identities, links and collaboration history**. Credentials are
provisioned separately. The rehearsal uses a disabled local-only archive channel.

For each bundle, create a private local File and a Relay Legacy Import. The
`prepare_import(manifest, channel, source_bundle=file_name, business=None,
user_map=None, team_map=None)` helper creates/reuses a source-site-scoped Contact
and Relay Contact. It creates unverified endpoints and paused archive contacts.
Phone/BSUID/Group identity type is retained in the source metadata and message
provider context. To use an existing Contact, create the import form with its
explicit Relay contact instead of calling this helper.

`business=(doctype, name)` is an explicit target mapping. The helper adds that
Contact Dynamic Link; the importer checks the enabled Relay Contact Type and
readable target. It never guesses a target from matching names or numbers.
Leave the mapping empty to retain messages in restricted migration triage.
Unmapped reads, assignments, notes, topics and memberships remain only in the
restricted import metadata; they are not projected onto the contact. Only System
Managers can read triage messages in Desk; ordinary Relay business
queries cannot infer an association from subsequently added Contact links.
Resolve triage by creating a new pass with the explicit business mapping.
Conflicting mappings are reported; an unresolved replay does not erase an
existing explicit business association.

Source staff users and teams require explicit maps. Staff reads are projected
into Relay Message Read and conversation state, independently of WhatsApp
Read/Delivered receipts. Original staff-read times become read-record creation
times. Notes, their replies/tasks, topics and topic memberships are projected
without notifications; complete original records remain in the import metadata.
The restricted reconciliation report stores the last applied collaboration
projection and carries it into subsequent jobs. Replay updates only fields still
matching that projection; local edits and removals survive, and conflicting fields
are listed. Read cursors and last-seen times never retreat. Pre-existing records
without a saved projection are retained conservatively. This also protects records
created by earlier importer versions that did not record projection baselines.
For segmented conversations, replay the metadata/import after all segments have
arrived so early references to later messages can resolve. Source conversation
status and source business/identity links remain in the import record for review;
Relay has no equivalent general Open/Pending/Resolved conversation field.

The original author is in `Relay Message.legacy_author` and the message API;
`owner` identifies the importing user. `legacy_data.row` is the complete original
row, with its canonical SHA-256 in `legacy_checksum`. Source site plus original
message name determines the same `source_key` for both import modes. Deleted
message evidence remains in the original row. Templates retain typed parameters
and renderable snapshots when available; reactions project onto their provider
message target using the same actor keys and timestamp history as live updates.
Source timezone is retained for provider-time comparisons; live reactions and
removals at equal or later times take precedence. Quotes retain the provider reference.

**Reconciliation report** lists source type/status counts, checked identities,
original-payload hashes, copied attachment bytes, updated rows and individual
mismatches. **Completed** means the segment was processed, not that cutover is
approved. Version 1 bundles are readable but explicitly flagged as incomplete;
re-export version 2 to preserve all original columns and related history.

## Media and failure handling

File bytes stream in 1 MiB chunks through ZIP export, private storage and archived
media reads. There is no 4 MiB migration/viewer drop. Every copied File is checked
against its SHA-256 and size before linking. Source local Files and the installed
S3 integration's explicit bucket/key are supported. Arbitrary payload URLs are
never fetched; other external storage needs an explicit streaming adapter.
Missing files, missing storage metadata, failed downloads and checksum failures
are recorded per message. Media unavailable in a restored copy must be recovered
from the authoritative archive before treating that copy as a complete cutover.

Imports serialize through a site-wide Redis lock. Run preparation/import scripts
serially on a target: standard Frappe series allocation can reject overlapping
setup transactions. A failed batch can be retried; completed batches are durable.
Never commit a failed batch manually. No source/business row is locked by import.
Reconciliation mismatches do not roll back otherwise valid imported history.
Rows rejected for mapping/status/direction conflicts retain their complete original
row and checksum in the restricted report, including same-site imports.

## Imported messages in daily use

An imported message is a normal message. The inbox, search, ticket links,
folders, reply windows, quotes, reactions, media and the overview use its real
message time (`sent_at`), not its import time. A reply quotes the WhatsApp
message ID of an imported message. When the ID is missing, the reply goes
without a quote. The newest STOP or START keyword in the imported history sets
the opt-out of the number, unless the number changed later.

These differences stay, because the event already happened in WhatsApp Core:

- Import does not run arrival actions: AI replies, flows, email rules,
  automatic translation and automatic transcription. Users can still ask for a
  translation or a transcript of an imported message.
- Imported messages arrive as read. They do not add to unread counts, and the
  read cursor does not move to an imported message, because imported names do
  not follow message time.
- Billing template counts leave out imported messages. They are not new spend.
- Rows with `legacy_triage` (bundle import only) stay visible only to managers
  until a business is assigned. The database import sets `legacy_triage` to 0.

## Reloaded schema

No new DocTypes were added. These standard fields were loaded on `yrp.site`
from the worktree JSON with `frappe.reload_doc`:

- **Relay Message:** `legacy_author`, `legacy_checksum`, `legacy_triage`.
- **Relay Legacy Import:** `source_site`, `source_channel`, `business_doctype`,
  `business_name`, `user_mapping`, `team_mapping`, `delta_since`, `watermark`,
  `last_creation`, `upper_creation`, `source_metadata`, `reconcile_report`.

## Local rehearsal (2026-10-24)

Source: read-only `sales-prod.site`. Target: `yrp.site`, running scripts with this
worktree first on PYTHONPATH. Only Relay Message and Relay Legacy Import were
reloaded via `frappe.reload_doc`; no migrate, fixtures, build, source mutation,
site configuration change, commit or push was performed. Target S3 is read-only
and disabled; email is muted. Provider, enqueue and email calls were also blocked
in the import/replay acceptance runs.

- Export: 8,153 messages, 848 conversations, 6.47 seconds.
- Import: 8,153 inserted, 89.60 seconds; 2,451 staff-read records projected.
- Initial replay: 0 inserted, 8,153 skipped, 94.05 seconds. A later full replay
  updated the four reaction-actor projections after that mapping was refined;
  it inserted zero messages and took 89.66 seconds.
- Independent identity/payload/status check: 8,153/8,153, no differences, 3.06 seconds.
- Read-only delta query after the snapshot: 0 created/changed rows, 0.30 seconds.
- Receipts: 4,845 Read; 2,571 Delivered; 615 Failed; 122 Sent.
- Original types: 5,033 template; 2,281 text; 482 interactive; 265 image;
  62 audio; 24 document; 4 reaction; 1 sticker; 1 unsupported.
- 580 source File records (58,491,726 declared bytes) have absent local files and
  empty S3 bucket/key metadata despite their uploaded markers. Actual copied
  bytes: 0. Another 14 media entries have no archived File.
- Review: 4,210 missing template snapshots, 1 unsupported content structure,
  and 594 unavailable media entries. Full originals are retained. All 8,153
  messages remain in restricted business-mapping triage. Three overlapping source
  staff cursors map to existing target state: 307 originals retained, 304 target
  cursors, with three explicit collaboration conflicts. No send actions exist.

A separate target-only fixture passed 52-row import/replay, a delta with one
updated row and one newly created row whose name sorts earlier, stale-revision
rejection, continued import after a bad direction, private 6,291,456-byte binary
attachment copy/read, original author, staff reads, notes/topics, unverified
endpoints and zero provider/email/enqueue calls. Records are labelled local-only
and retained for review. The tests do not delete data.

Run the reproducible scripts with:

```bash
FRAPPE_STREAM_LOGGING=1 PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/home/sakthi/development/relay-wt/core-mig \
/home/sakthi/development/pilot/benches/version_16/env/bin/python \
tests/rehearse_legacy.py export --frozen --directory /tmp/relay-history-new-run
```

Then run `import`, `verify`, and `replay` with the same directory. Source snapshots,
private bundles, source IDs, and detailed reports stay outside git. For the
completed rehearsal they are under `/tmp/relay-sales-rehearsal-20261024`; per-pass
reports and source metadata are also on the target's Relay Legacy Import forms.
Run `tests/integration_legacy_site.py` with the same interpreter/environment for
the labelled target-only fixture. It is deliberately fixed to the approved local
`yrp.site` and never creates source DocTypes or modifies `sales-prod.site`.

Production sender cutover, business/user/team mapping decisions, recovery of
missing source media/templates, and deploying the worktree to ordinary web/worker
processes have not been performed. The target API paths were exercised directly
with the actual site connection and worktree code, not through the main checkout's
web process. No frontend assets changed.

## Review regression coverage

The final frozen-export tests cover legacy send completion (status/provider ID)
and media-cache content/File changes while `modified` stays unchanged. Target-only
acceptance also exercises import → live API edit → repeated replay for assignments,
read cursors, notes and topics; unchanged fields still accept source updates.
An ordinary Relay user with access to the contact cannot read the restricted import
or triage message, and sees no projected triage note/topic. A live provider reaction
removal remains empty after replay. Provider, email and enqueue paths remain blocked.

No additional DocType fields were needed for these review fixes. The existing
migration schema above still needs loading when deploying to a fresh target.

Review rerun (2026-10-24), using a read-only consistent snapshot of the local source
copy as the frozen image:

- Full frozen export: 8,153 messages across 848 conversations, 6.47 seconds.
- Full target replay: 0 inserted, 8,149 skipped, 4 reaction timestamp projections
  updated, 125.25 seconds.
- Independent verification: 8,153 source and target identities, zero payload or
  status mismatches, 4.21 seconds. Existing review items remain: 4,211 content
  warnings and 594 unavailable media entries; no media bytes were recovered.
- Target-only acceptance passed 52-row import/replay, unchanged-modified send and
  cache reconciliation, live edit/conflict handling, ordinary-user triage denial,
  live reaction removal, private 6 MiB attachment reads and no resend.
- Focused migration suite: 26 passed. Full suite: 205 tests, 200 passed, 3 skipped;
  the two pre-existing ffprobe/audio errors remain. `git diff --check` passed.

Private rerun bundles and reports are under
`/tmp/relay-migration-frozen-review-20261024`. Web/worker code was not switched;
these site tests loaded the worktree directly. No new schema reload was needed.
