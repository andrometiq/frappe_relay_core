# Functional parity with frappe_whatsapp_core

Current access: [business type assignments](business-access.md). Team controls and group claims are hidden; team-related descriptions below refer to retained legacy implementation.


User instruction, 24 September 2026: match the old app's functionality, not its UI.
Source reference: installed frappe_whatsapp_core/core_ui/src. Implementations and
synthetic tests are not installed-site acceptance. Do not mark a workflow complete
until its browser behavior and permission boundaries are verified.

| Workflow | Relay position / remaining work |
| --- | --- |
| Shared inbox, contacts, business links, channel routing | Present; live Telegram receive proved; manager sender enrollment added and database boundaries tested; installed empty-state checked |
| Chronological history, original timestamps, paging, restore, latest jump | Provider timestamps and chronological cursor paging corrected; out-of-order history verified in isolated DB and installed Telegram history |
| Conversation/message search and exact-message navigation | Contact/message search and server-resolved quote jumps implemented; installed search/context verified |
| Compose, attachments, emoji/reactions, quoted reply, templates | Compact composer, Enter/Shift+Enter, cancel quoted reply, HTTP-safe stable request keys; installed draft retention through reply/cancel and contact/business scope switches verified; live outgoing acceptance still pending |
| Pending/failed/sent/delivered/read, retry and reconciliation | Incoming Received presentation fixed; monotonic WhatsApp receipts and visible snapshot refresh implemented; conversation delivery list, receipt checks and original-sender-only confirmed-rejection retry implemented; fixture tests prove one retry and no blind replay |
| Message info, original reply preview, download/viewer | Partial; complete contextual actions |
| Live message/status refresh, typing, operator presence, read coverage | Exact visible-message read evidence, team coverage, skipped-message unread preservation, operator presence and expiring typing implemented; DB permission/dedup checks and installed message-info read evidence pass |
| Unread/team/business/folder filters and latest-message list previews | Unread/unassigned filters, latest preview metadata and activity ordering implemented and DB tested; searchable team selector and exact message read coverage implemented |
| Assignment, teams, folders, stars, shared contact management | Partial; compare permissions and complete operational workflows |
| Internal comments/tasks, mentions, message selection and notifications | Internal notes/replies/edit/remove/message references, assigned tasks, mentions and in-app notifications implemented; DB recipient/revocation boundaries pass; installed self-task create/complete/remove verified |
| Contact summaries, period summaries, topics/threads, AI queue | Read-only AI period summaries, action items and evidence-linked topics implemented; fixture-model DB checks cover request dedup, source edits and access revocation. Installed disabled-policy state checked; live model acceptance pending |
| New conversation and WhatsApp service-window/template gate | Integrated new-conversation dialog for verified private endpoints; WhatsApp reply-window gate and approved-template parameters; installed Telegram destination/mobile layout checked, no live outbound sent |
| Groups, topics, members, invitations, polls | Partial provider controls; compare every old operation |
| Calls, signaling, permissions, dock, recordings and timeline | Persistent shell call dock, assigned-contact-only signaling/history, mute and audio lifecycle implemented. Fixture WebRTC and isolated DB checks pass; fixture browser navigation/mobile dock persists. Private recording archive/download with content hash, upload limit and conversation-access checks implemented; live calling/audio acceptance remains |
| Automation and Meta flows, triggers, versions, responses | Relay flows differ; schema/action parity and migration need comparison |
| Campaigns, bulk selection, recipient ledger, cancellation/recovery | Persistent draft/audience/recipient ledger, 25-recipient admission batches, pause/cancel/recovery and history mirroring implemented. 52-recipient fixture test passes. Installed setup checked; CSV audience import and per-recipient content implemented; parser, isolated DB and mobile browser fixture pass. Complete provider acceptance remains |
| Templates, parameters, editor, send dialog | Structured header/body/footer/button editor, positional/named samples, validity, advanced-component preservation and send parameters implemented; five authoring domain tests and Hub transport test pass. Installed mobile form checked without provider submission; media upload and live approval remain |
| Dashboard, audit/health, permissions, configuration in Desk | Permission-filtered overview and manager attention counts implemented; installed real counts checked. Hub opt-in hourly metadata refresh, cached status and offline key rotation implemented and isolated PostgreSQL tested; broader operations acceptance outstanding |
| Legacy message/detail migration | Desk same-site bounded importer implemented: preview, resume/dedup, dates/status/raw source, private local attachments, automation suppression; 52-message isolated DB test passes. yrp.site lacks legacy source tables; source site requested. Cross-site transfer and remaining legacy entities pending |

Immediate checks: installed HTTP crypto support, proper chat timeline, message
search/context, draft-safe compose, live inbound and reply. The old app remains
available; this ledger is not a completion claim.

## 24 September implementation evidence

- Core unit contracts: 84 tests, 82 passed and 2 optional integration skips (`.runtime/parity-unit.log`).
- Guarded inbox integration covers chronological cursors, literal search, snapshot/contact isolation and unread preview metadata.
- Typed send integration: 28 scenarios, 37 local fixture HTTP submissions; ordinary versus quoted sends preserve destination/topic and stable-intent keys. These are not live provider sends.
- Installed Administrator browser on HTTP yrp.site verified absent WebCrypto subtle, retained draft through reply/cancel and automatic snapshot HTTP 200, message search/info, internal note create/edit/remove, and unlinked-sender empty state.
- Legacy importer Desk list opens on yrp.site. Legacy source app code is present, but its message table is absent on yrp.site. No customer history was imported.
- Enrollment integration covers source-derived sender, replay, no reassignment, revoked binding and account/role boundaries.

- Read-only summary queue: `integration_summaries_site.py` passes with a fixture model. No live model calls.
- Tasks/mentions/notifications: `integration_collaboration_site.py` passes recipient and notification ownership/revocation checks. Installed temporary self-task was completed and removed; no colleague notified.
- Campaigns: `integration_campaigns_site.py` passes 52 recipients, bounded admission, lost-response and pre-admission retry, pause/cancellation, changed-recipient rejection, and single history mirror with receipt refresh. Hub transport is a local fixture in this test.
- Overview: `integration_overview_site.py` verifies access, old/imported exclusion and seven-day counts; installed overview displays 4 incoming, 0 outgoing, 1 conversation.
- Broad regression `.runtime/parity-inbox-ai-simulation.json` (Hub repo) passed Hub race/database/static checks and all Core integrations except the legacy zero cursor in channels. Fixed that compatibility regression; targeted `integration_channels_site.py` then passed all 44 scenarios. This report predates the campaign/overview additions.

- Hub metadata refresh: isolated PostgreSQL/fixture HTTP verifies opt-out, paginated cache, hourly gate, redacted failures retaining prior cache, and account removal mid-refresh. Hub migrated/restarted; existing accounts remain opted out. Offline rotation is tested, not applied to live keys.
- Inbox read evidence: team membership filtering, typing, exact reads, skipped unread messages, deduplication and revoked-reader exclusion pass in `integration_inbox_site.py`; installed Administrator message-info shows real operator read time. Unit suite remains 82 passed, 2 optional skips.

- Typed transport regression now passes 31 scenarios / 39 local fixture submissions, including conversation start, expired reply-window admission, queued template recovery, and idempotent confirmed-rejection retry. Installed delivery panel correctly shows no outgoing actions; dialogs support Escape.

- Full regression `.runtime/parity-workflows-simulation.json` in Hub: passed=true, 24 checks (Hub race/database/static, Core units, 17 Core integrations, frontend/whitespace). This report precedes the new call journal/dock; targeted call DB and WebRTC tests pass separately. Template authoring JavaScript tests were also run separately.

- Private call recording test stores/deduplicates an isolated audio fixture, verifies private file ownership and rejects unrelated/revoked readers. The installed call history empty state is checked without a provider call.

- Expanded regression `.runtime/parity-calls-simulation.json` in Hub: passed=true, 25 checks including call journal/private-recording boundaries and JavaScript authoring/call controls. Campaign CSV changes followed that report; targeted campaign integration and mobile CSV fixture pass, retaining Draft state with no provider delivery.

### Cross-site history verification (24 September)

Read-only discovery found 7,297 legacy Core messages in 824 conversations on
`sales-prod.site`, all on one WhatsApp channel. No source records were changed
and no history has been imported into `yrp.site`. The destination has no
`Partners` DocType, so business mapping must be explicit.

Portable private ZIP bundles now preserve source identity, checksums, message
metadata, timestamps, delivery state, reply references and bounded local media.
Imports resume in batches of 50 with duplicate protection and pinned bundle
checksums. The isolated database test verifies cross-site import, private media,
replay, immutable mappings and rejection of malformed archives.

A full read-only format scan found 4,256 templates, 481 interactive messages,
2,232 text messages and 328 media messages. Template snapshots and interactive
replies now render as readable history. 4,210 older template records lack their
snapshots; their existing body and raw metadata are retained with a review
warning. The scan matched 308 message references to File records. Later byte checks found
all 316 legacy attachment File records point to missing local files; restoring
attachments requires the original public/private files backup. No provider requests
were made during this verification.

### WhatsApp forms and response history (24 September)

Added account-owned Flow list/details/create/update/JSON upload/download/publish/
retire/delete operations and a manager-only **Flows → WhatsApp forms** workspace.
Foreign Flow IDs are rejected before access or mutation. JSON downloads are
bounded to 1 MiB from the Meta CDN without forwarding the Graph bearer; signed
asset URLs stay out of the form JSON response. The adapter follows Meta's
[Flow API collection](https://www.postman.com/meta/whatsapp-business-platform/request/m1exgnx/list-assets-get-flow-json-url).

Mobile browser fixtures passed draft creation, definition upload and publication
without JavaScript errors or horizontal overflow. The actual `yrp.site` browser
passed the unconfigured-channel state. No live Meta Flow was created or changed.
Form submissions now retain readable field values in chat without displaying
internal correlation tokens.

The broad `.runtime/parity-meta-flows-simulation.json` Hub report passes 26 checks.
Targeted race tests cover the additional JSON download adapter. Still pending:
Flow cloning/migration, managed encrypted data exchange, sending forms from chat,
and live-provider acceptance.

Call connect transport failures now enter Outcome unknown and block repeat
submission in the active workspace (Node failure test passes). Durable call
admission/reconciliation across page reloads is still pending.

Published forms can now be sent from the private WhatsApp chat composer using
verified contact routing, the reply-window gate, stable delivery request keys
and receipt reconciliation. Hub rejects draft or foreign-account forms. Core
integration passes 32 typed-message scenarios; the mobile browser fixture
verified queued → submitted with one submission and no JavaScript errors or
overflow. This is fixture acceptance, not a live form delivery. The message
format follows [Meta's published-Flow send contract](https://www.postman.com/meta/whatsapp-business-platform/request/ftdtf2c/send-published-flow-by-id).

Conversation flow definitions now support forward answer branches, persisted
delays (1 second–24 hours, resumed by the scheduler), and terminal steps.
Publication rejects backward jumps, unreachable steps and paths that use an
input they might skip. Isolated DB acceptance verifies early-resume denial,
branch isolation, restart during a delay and idempotent continuation. The
installed-site editor was checked without saving a live flow.

Actual-site export/decode verification: a 10-message source conversation decoded
on `yrp.site` without legacy source tables. Five attachment references in that
sample could not be exported. A filesystem audit found all 316 legacy message
File records missing their local bytes in this source clone. The temporary
private sample archive was removed after verification; only aggregate counts
remain in `.runtime/migration-review/verification.json`. Migration needs the
original public/private files archive to preserve those attachments. No source
or target message records were changed.

### Durable call recovery (24 September)

Relay Call Attempt is installed on `yrp.site`. A connect intent is committed
before transport; unresolved attempts prevent another submission to the same
endpoint even after reload. Exact `biz_opaque_callback_data` matching resolves
lost acknowledgements; phone/timing guesses are not used. Explicit provider
4xx rejections (excluding timeout 408) and local capacity rejection are recorded
as rejected; ambiguous transport/server outcomes remain blocked.

The root call workspace restores unresolved or active attempts. Recovered calls
can be ended, but browser microphone sessions cannot resume across reloads.
Call provider IDs now accept padding characters and are stored without a short
Data-field limit. Isolated DB tests cover lost acknowledgements, replay, exact
correlation, definite rejection and permissions; three browser-control Node
tests pass. Targeted Hub race tests cover safe error metadata and callback
forwarding. Live provider calling still has not been exercised.

Read-only inspection of the real source flow found 26 nodes using choice and
number inputs, conditions, multi-select, topic categorization and a custom
`retailer.create_follow_up` action, with command and template-button triggers.
Those custom actions and source-flow migration still need implementation and
destination business-model mapping.

Flow inputs now support bounded whole numbers, optional answers and multiple
choices. Unit and isolated DB checks cover invalid bounds, numeric validation,
choice deduplication, rendering and persisted answer review. The recovered-call
mobile browser fixture ended the correct prior call once, remained clear after
reload, and reported no JavaScript errors or overflow.

### Conversation topic backend — in progress

Added internal Relay Conversation Topic storage and scoped directory/save/upsert APIs. A message has one topic per contact; automatic updates use stable source keys and preserve human edits. Manual edits reject stale revisions. The isolated PostgreSQL integration test passes replay, membership conflicts, cross-contact isolation, stale edits, human preservation, and guest denial, including cleanup. Topics use Long Text for serialized message IDs because Frappe's JSON list serialization failed during document deletion; rerun passed after correcting the schema. This is backend evidence only: Inbox UI, flow action wiring, normal-operator permission coverage, installed-site migration and browser acceptance remain unfinished. No live data changed.

### Topics Inbox UI and installed read-only acceptance

ConversationTopics now opens from Inbox: paginated topics, create/edit title/summary/category/status, message checkboxes, retained older selections, jump-to-message, and release by deselect/save. Build passes. Extended isolated database checks prove assigned-operator edits and unassigned-operator denial. Installed Relay Conversation Topic on yrp.site and reloaded workers. Actual Administrator browser opened the empty topic directory and unsaved creation form against four real Telegram messages; 390px viewport had no horizontal overflow. No live topic was saved. Still pending: browser fixture save/reload/conflict tests, membership scaling, workflow actions, richer topic timeline, and complete functional parity.

### Topic flow step

Added “Organize as topic” to the flow editor and validated runtime. Topic titles interpolate collected answers, summary uses step text, category/status are editable. The runtime associates accepted flow-event messages (including command), excludes rejected inputs, and uses the run/step key for retry deduplication. Human edits remain preserved by the topic service. Full isolated flow integration passes, now asserting one topic with precisely command + accepted answer through an uncertain send/retry; six contract tests pass. Frontend build passes and installed mobile flow editor shows topic fields without horizontal overflow. No live flow was saved or executed. General allowlisted custom business actions, source graph conversion and template-button triggers remain unfinished.

### Custom action contract groundwork

Read the actual ESSDEE retailer action implementation: it creates configured legacy cases (catalogue, callback, stocking_interest), deduplicated by flow instance, with collected fields; it is not merely a generic ticket label. Relay must preserve these business semantics when adding its action adapter. Added bounded recursive typed action-input resolution/validation, closed fields by default, explicit collected-variable references, array/enumeration/numeric limits, no coercion or arbitrary Python expressions. Three focused contract tests pass. This module is not yet wired to the runtime/catalog/UI and does not establish custom-action parity.

### Registered action runtime

Added the `relay_flow_actions` installed-hook catalog and runtime action node. Definitions must explicitly declare replay safety; handlers receive contact, run and stable idempotency key. Internal Relay Flow Action journals input hash/result and rejects changed replay inputs. Handlers remain responsible for permission checks on their business records and idempotent external effects if a crash occurs before journaling. Unknown Python paths cannot be invoked from node arguments. Collected references are resolved as bounded literal data (not recursively evaluated expressions). Ten contract tests and the full isolated flow suite pass, including real DB result replay without a second handler call and rejection of changed inputs. No business handler is enabled on yrp yet; UI action editor and retailer adapter remain required. New journal DocType is synced only on isolated test site so far.

### Business action editor

Flow editor now offers Business action from the installed catalog, field-specific fixed values or collected-answer mapping, enum selection, numbers, booleans and structured JSON with immediate syntax feedback. Invalid/incomplete action fields block draft saving. The internal action journal DocType is installed on yrp.site. Frontend build passes. Mobile browser fixture (catalog only mocked, no writes) selected callback, rejected malformed structured input, recovered after correction, with no JS errors or overflow. Corrected a Frappe select-label accessibility issue by using the existing native RelaySelect for enum fields. Actual installed-site empty catalog state also verified. Retailer adapter, saved-flow browser acceptance and source graph migration remain unfinished.

### Action schema validation and retailer case requirements

Registered action schemas now reject unsupported constraints instead of silently ignoring them, malformed required/properties definitions, missing array item schemas, invalid numeric/length bounds and enum type mismatches. Eleven contract tests pass. Full isolated flow integration passes with catalog filtering checks for unsafe hooks, malformed schemas and non-method paths.

Read ESSDEE solution_pack.py requirements: catalogue Normal priority; callback/stocking_interest High. Stages open, in_progress, waiting, completed (requires completion_evidence), rejected. Additional complaint Critical and mapping_exception High case types exist in that solution. Fields action_type, party, note, completion_evidence. Current Relay Ticket has only fixed category/status and cannot yet faithfully represent these cases. Required next work is configurable typed case lifecycle (Desk configuration, custom operations UI) and retailer adapter, preserving these lifecycle rules. Do not claim a generic ticket is equivalent.

### Configurable case lifecycle backend

Added Relay Case Type (System Manager Desk configuration) and internal Relay Case with pinned lifecycle snapshot, typed fields, priorities, states, allowed transitions and stage-required evidence. Scoped create/read/move APIs enforce readable contact and optimistic edit revisions. Two contract tests and isolated PostgreSQL integration pass: creation replay, evidence enforcement, completion timestamps, stale-edit rejection, lifecycle pinning after type changes, and guest denial. Not installed on yrp; no operator case UI or retailer adapter yet. Further work includes case directories, assigned-operator checks, immutable creation intent hash, initial-terminal closed timestamp, and lifecycle configuration UI documentation. Existing tickets remain separate pending deliberate unified operator navigation.

### Case retry and operator boundaries

Case creation now pins an intent hash and rejects changed-title/field retries using the same request key. Initial terminal cases receive a closed timestamp. Added a contact-scoped case directory. Extended isolated database tests pass for intent rejection, directory access, assigned-operator reads/reopening (clears closed timestamp), and denial of unassigned reads/transitions. Case UI and retailer adapter remain unfinished; these latest changes are only synced to the isolated site.

### Inbox case panel

Added ConversationCases in Inbox with paginated directory, detail, typed fields, allowed-stage selection, required-field hints, update/reload and stale revision passed to server. Case types remain Desk configuration. Frontend build passes; Relay Case Type and Relay Case installed yrp, workers reloaded. Actual mobile Administrator browser opens Cases on the real Telegram conversation and confirms the empty directory with no horizontal overflow. No live case created. Browser save/validation fixtures, manual creation UX, global case operations and retailer adapter still required.

### Case browser save and retry recovery

Mobile browser fixture now verifies completion without evidence makes zero write requests; adding evidence submits once and reload preserves it, with no JS errors or overflow. All case APIs mocked in this fixture; no live case modified. Fixed creation recovery so an existing matching intent is returned even after its case type is disabled/changed, while new cases remain blocked; isolated DB test passes both paths. Editing a terminal case preserves its original closed timestamp. Retailer adapter, manual/global case operations and broad acceptance remain unfinished.

### Retailer adapter first integration

Added the actual `retailer.create_follow_up` hook backed by Relay cases and an explicit local case-type installer preserving existing admin definitions. Supplies the five legacy type priorities/stages; flow action supports catalogue/callback/stocking_interest. Per-run/action-type keys deduplicate across different action steps. Real installed-hook isolated DB integration passes priority, retained collected string fields, deduplication and evidence enforcement. Found and fixed Frappe's nested hook scalar-list normalization, missed by earlier mocked definitions. No live retailer types installed yet. Structured/non-string collected legacy values, per-run dedup with changed later payload, manual/global case UX and migration remain pending; do not claim full adapter parity.

### Retailer structured answers and site setup

Added bounded literal JSON field contracts so collected arrays/numbers/nested answers retain their types. Later steps requesting the same follow-up type reuse its existing case and preserve its details, matching legacy behavior. Twelve action-contract tests and real-hook isolated retailer integration pass with structured values and changed later-step note. Frontend build passes. Installed five retailer case definitions on yrp (preserving any existing definitions) and verified the registered action through actual Frappe hooks. No live case or outgoing message created. Browser catalog acceptance, migration and full goal acceptance remain outstanding.

### Installed action catalog and collected case fields

Actual yrp mobile browser now selects the registered retailer follow-up action and renders its type/title/note/collected-values controls without overflow; no fixture catalog used and no flow saved. Case detail previously rendered only declared properties, hiding additional collected answers retained in storage. It now includes all saved fields using the additional-property schema, preserving structured display/edit behavior. Frontend build passes; specific extra-field browser fixture remains to verify. Source flow inspection confirms labeled choices with distinct values (HAAN→yes, NAHI→no), nested references `answers.*`, and end-node messages, which graph migration must preserve.

### Labeled choice values

Conversation flows now accept both existing string choices and explicit label/value choices, preserving stored branch values. Single/multiple selection accepts labels or values; numbered multi-choice input returns stable values. Ambiguous overlapping labels/values reject at definition validation. Editor supports one `label | value` per line while retaining simple choices. Seven flow contract tests and full isolated flow integration pass; multiple-choice test now proves displayed Red/Green persists red/green and renders the stored answers. Build passes. Legacy graph importer and template-button triggers remain required.

### Explicit flow edges and terminal messages

Added forward next-step routing for nonterminal steps, validated for reachability and guaranteed inputs at joins. Runtime advances inputs, delays and actions through these edges; end steps can send a final message under their durable send key. Editor exposes next-step selection and optional end text. Eight contract tests and full isolated flow integration pass, including explicit yes/no join skipping the unrelated reply and sending the terminal message once on event replay. Frontend build passes. Source graph conversion remains pending; new backend needs worker reload before installed acceptance.

### Legacy graph conversion groundwork

Added pure legacy DAG converter for input/condition/action/topic/end nodes, nested answer references, explicit edges, labeled choices and final messages. It returns disabled review-required steps with original triggers; it does not create or activate a flow. Actual ESSDEE source template converts 26 nodes to 26 validated Relay steps. Deterministic path checks reach correct terminals for accepted A, accepted C, deferred consent and declined consent. Two converter tests pass. This is template conversion evidence, not installed source-database graph import or provider execution. Import API/UI and template-button trigger handling remain missing. Converter currently supports equality edges and forward DAGs only; unsupported patterns reject.

### Converter validation and preview endpoint

Converter now rejects unknown node configuration and unsupported topic fields/confidence, and translates explicit required=false to optional input. Three converter tests pass and the real template still converts to26steps. Added System-Manager-only bounded preview endpoint returning converted steps, original triggers, missing registered actions and explicit warnings that non-command triggers are not executable yet. It performs no writes or publication. Preview browser/UI and stored-source acceptance remain pending. Topic source keys/output metadata still need preservation audit before final import parity.

### Legacy preview editor UI

Added legacy graph file/paste dialog with bounded JSON input, conversion preview, warnings, missing-action report, and opening an unsaved disabled draft. Administrator-only endpoint tested against actual retailer template:26steps, /feedback command, registered action, no RelayFlow row writes. Ordinary operator denied. Frontend build passes. Browser interaction still to verify; unsupported trigger metadata currently shown as warning and not yet saved in the draft. Template-button implementation remains required before full legacy import acceptance.

### Template button routing backend

WhatsApp template button normalization now stores payload separately from displayed text and records button provenance. Added optional per-channel unique button payload trigger to flows, included in version snapshot. Matching requires WhatsApp button provenance and exact stored payload; ordinary text matching that payload does not start the flow. Two normalization tests and isolated flow integration pass matching/ordinary-text rejection plus prior workflow scenarios. New fields synced only on isolated site; UI/import wiring, actual webhook projection integration and yrp schema deployment remain pending. No live webhook/button sent.

### Installed import preview and trigger editor

Added Template button payload to flow editor, carried imported payload into the draft, and tightened preview to exactly one command plus at most one button trigger; unsupported trigger sets now reject rather than being dropped. Actual retailer-template preview returns /feedback and retailer_feedback_start. Installed Flow/Version fields on yrp and reloaded workers. Actual mobile browser previews a two-node graph through the real endpoint and opens an unsaved draft with /review and review_start intact, no horizontal overflow. No live flow saved or activated. Full webhook-to-flow button integration and stored legacy graph end-to-end acceptance remain outstanding.

### Full converted retailer flow database acceptance

Extended the guarded flow integration to persist/publish the actual converted26step retailer graph on the isolated site and drive the full accepted-A path through the real runtime. Passed consent, three ratings, stable multiple-choice values, catalogue/callback actions, two persisted cases (Normal/High), structured categories, one resolved topic containing all10 accepted incoming messages, and final reply. Provider sending remains mocked; this is not live WhatsApp delivery evidence. Read-only sales-prod.site inspection confirms its single saved draft_graph exactly equals the source template tested and converts26→26 with command/template_button metadata. No legacy source mutation or actual yrp flow import performed.

### Retailer branch and projected button acceptance

Full guarded flow suite now executes stop/defer/stocking-interest branches after accepted-A and verifies exact case counts, topic message counts and completion. Initial test used unsupported consent 'no'; corrected to the actual 'stop' source choice. All paths pass. Extended typed-message DB/HTTP fixture suite passes34scenarios/39fixture submissions, including actual WhatsApp button payload projection to RelayMessage with provenance, queued FlowEvent, real runtime prompt once under replay. Provider prompt send mocked; no actual WhatsApp call made. This proves Core projection-to-flow integration, not provider webhook registration or live delivery.

### Global case directory groundwork and audit correction

Added bounded global case search/state directory with keyset continuation and per-contact permission checks before returning case details. Scans50records/page; pages may be empty when all scanned contacts are inaccessible, so UI must allow continuation. Isolated case tests pass assigned-operator inclusion and unassigned exclusion. Global operator UI remains pending. Corrected the earlier migration paragraph:308 references matched File records, not existing file bytes; all316attachment file records lack local bytes. Original backup remains required for historical media restoration.

### Cross-conversation case workspace

Added Cases tab alongside Tickets with server search/state filters, bounded continuation, case cards, direct case details and conversation links. Reuses the Inbox case editor via initial-case selection. Frontend build passes; workers reloaded. Actual yrp Administrator mobile browser opens the real empty workspace and state controls without horizontal overflow. Populated global workspace fixture, manual case creation, case assignment and full operator acceptance remain unfinished.

### Manual conversation case creation

Added contact-scoped case type choices and a POST manual-create endpoint with user-scoped retry key. Inbox Cases now offers New case, type/title selection and the configured initial-stage fields, reusing typed validation and existing detail editor after creation. Isolated DB test now exercises manual create/replay and prior permission/lifecycle checks, passing. Frontend build passes. Browser new-case interaction and installed backend reload remain pending; no live case created.

### Manual case browser acceptance

Actual yrp mobile browser opens New case and selects Callback from all five installed types, showing High priority and configured fields with no overflow. Separate isolated browser context intercepts only the create write; submits title/note/type/retry key exactly once and opens returned case details, with no JS errors or horizontal overflow. Read APIs use actual installed site; create result is a fixture. No live case added. Case assignment/global populated-page acceptance and broad product requirements remain outstanding.

### Case assignment

Added manager-only case assignment with optimistic revision checks and recipient conversation-read validation; assigning a case does not grant conversation access. Eligible-agent endpoint filters existing Relay agents. Case detail shows assignee and manager assignment control. Isolated DB checks pass allowed assignment, inaccessible-agent denial and ordinary-operator reassignment denial. Build passes and assigned_to field installed yrp; reload requested. Populated browser assignment interaction still pending; no live assignment made.

### Populated case workspace and assignment browser fixture

Mobile fixture navigates Tickets→Cases→Open case, selects an eligible agent, submits exactly one assignment with correct revision, and displays the new assignee. No JS errors/overflow; assignment controls close after response. Fixed stale assignment controls by resetting on record change. No live assignment. Extended Hub simulation runner with topics/cases/retailer integrations; full broad regression started and is still running (not yet a pass).

### Expanded integrated regression

Hub `.runtime/parity-retailer-cases-simulation.json` completed passed=true with29checks: Hub race/database simulations with no skipped integrations, static analysis, Core unit contracts, all prior Core integration scripts plus topics/cases/retailer, frontend data simulations and whitespace checks. This is the latest broad local fixture regression, not live-provider or production acceptance. Provider support docs refreshed against current code for Telegram media, MIME/threaded email, IMAP polling, durable channel outboxes and metadata reconciliation. Remaining explicit scope (live provider acceptance, complete migration/media recovery, operations/load/restore, full provider controls/Meta workflows) still prevents completion.

### Synthetic database restore rehearsal

Added guarded Hub scripts/rehearse_restore.py. Actual pg_dump/custom archive and transactional pg_restore passed for1,000 synthetic queued/submitted records with matching content digest and correct identity sequence continuation. Unique owned schema and private temporary archive cleaned up. Report Hub .runtime/restore-rehearsal.json passed=true. This is a synthetic-schema rehearsal only: full site/files/encryption-key restore and measured production recovery objectives remain unverified. Live databases/tables were not modified.

### Burst load test expansion underway

Existing adaptive-worker integration covered100messages. Added an opt-in bounded RELAY_TEST_BURST (100–2000, multiples of50), longer test deadline, drain/concurrency assertions and elapsed/heap/goroutine metrics. Started2000-message real PostgreSQL outbox burst against local fake provider with race detector; result pending. Updated stale scaling document to reflect existing queues/pools/adaptive workers while retaining unverified sustained end-to-end and infrastructure-autoscaling gates.

### 2,000-message burst result

Actual isolated Hub outbox burst passed under go-race:2000messages,61.629seconds admission/drain (~32.5/s), peak2workers, idle1, final heap1,938,416bytes,13goroutines. Log Hub .runtime/burst-2000-tests.log. No real provider traffic. This does not prove sustained50/100/s, peakRSS/CPU or full Core/UI end-to-end latency. Those gates remain open.

### Manual topic retry recovery

Topic creation now sends a stable per-draft request key, scoped to the authenticated user and contact. A retried creation returns its existing topic, preserves subsequent human edits, and rejects reuse with different creation content. Actual isolated database tests covered all three cases alongside existing permission/membership/conflict tests; site build passed. Status uses a labeled native select. Browser lost-response acceptance remains pending.

### Eight-worker burst result

Isolated real-PostgreSQL outbox with fake provider and race detector passed 2,000 messages at configured rate100:32.1267seconds, peak8workers, idle1, finalheap2,377,664bytes,16goroutines. Hub log .runtime/burst-2000-workers8-tests.log. This measures about62.3messages/second for this burst, not sustained100/s or end-to-end Core/provider capacity.

### Topic browser retry and numbered flow inputs

Mobile installed-bundle browser fixture aborted the first topic save response, retained the draft, then retried with the identical request key. Exactly two requests, one displayed topic, Waiting status preserved, no page errors or horizontal overflow. Topic API writes were intercepted: this complements the real isolated database replay tests, not a live topic creation.

Fixed multi-choice labels/values colliding with another option number: definition and runtime validation now reject ambiguous options; whitespace in JSON choice lists is normalized. Nine flow contract tests passed. Real isolated integration_flows_site.py passed including full converted26step retailer accepted/declined/deferred/stocking branches, saved cases/topics, replay, permissions and delayed-run recovery. Provider sends remained mocked.

### Core metadata sync visibility

Delivery now includes a read-only WhatsApp synchronization panel: last attempt/success, cached template count, partial snapshot indicator, current/failed/pending/not-synced/overdue states. Ready snapshots older than two hours are overdue. Manager-only Core facade verifies Hub site binding and reads account.metadata without triggering provider calls or returning profile/template payloads. New integration_metadata_site.py passes actual Frappe role checks (agent/guest denied before Hub access) with fixture health responses. Mobile installed-bundle fixture passes overdue/partial rendering without page errors or overflow; site build passed. Added this integration to Hub simulation runner; broad suite not rerun for this change yet.

### Unknown call outcome review

Added paged, permission-filtered unconfirmed call attempts and a manager-only evidence resolution form to call history. Verified not-started outcomes release the admission guard without sending; existing-call outcomes link only a known outgoing call matching the channel/contact/endpoint. Resolution evidence/user/time persist, exact retries are idempotent, contradictory retries reject, and row/admission locks serialize resolution with webhook confirmation and new admission. Schema selectively installed on yrp.site and workload reloaded.

Expanded actual isolated integration_calls_site.py passes manager-only resolution, immutable retries, unrelated-call denial, linked-call recovery, subsequent admission after verified rejection, plus prior call/recording/revocation scenarios. Mobile installed-bundle fixture submits exactly one evidence resolution and refreshes the empty list without JS errors/overflow. Build and whitespace checks passed. No live call or provider mutation; real audio/calling acceptance remains open.

### Additional WhatsApp group controls

Connected joining approval mode and separate new-group subject/description drafts, bounded replacement-page join-request navigation, JPEG photo upload, invite creation, durable queued pin/unpin, and typed-ID deletion confirmation (also guarded in submit handler). Mobile installed-bundle fixture verified correct create/photo/invite/paging/pin/delete requests, confirmation gate, no JS errors/overflow. All provider operations were intercepted; no real group changed. Site build passed. Group media/template composition remains open. Updated stale group/call documentation to reflect implemented recovery/private recording and retain real-audio limits.

### Group media/template composer and account boundary

Added reusable GroupComposer: text, image/video/audio/document (local file up to4MiB or URL/mediaID), caption/filename/reply context, approved paged templates with structured parameters and preview. Queued admission retains stable keys on failure. Tightened all account-wide WhatsApp groups.* operations to managers; inbox source-bound replies retain their existing permission path. Upload bytes accepted only for groups.media with one source and bounded encoded size, then existing Hub validation applies.

Installed-bundle mobile fixtures verify URL and local-file document failure draft retention, identical retry keys, template values, no page errors/overflow. Expanded isolated group integration passes ordinary-agent denial across group read/send/media/template/pin and byte-source validation alongside22 existing scenarios. Build passed. No live group sends.

### Telegram topic administration controls

Added existing Hub-backed general-topic rename/close/reopen/hide/show/unpin controls, selected-topic unpin, and topic deletion with typed-ID confirmation enforced in submit handler. Mobile installed-bundle fixture verifies rename/hide/show/unpin/delete payloads, confirmation gate, no page errors/overflow; build passed. Provider requests intercepted, no real topics changed. Topic discovery with human-readable persisted names remains open. Broad30-check regression groups-recovery-metadata-simulation is still running; do not label it passed yet.

### Broad regression and pagination-test correction

Hub .runtime/groups-recovery-metadata-simulation.json completed with29 of30 checks passing, including full Go race/database suite with no skipped integrations. The sole failure was ticket-notification integration assuming its newly created endpoint must occur on the first30-row page after repeated runs. Inspection confirmed the API returns a cursor and UI offers Next endpoints. Corrected the test to traverse all pages, assert page bounds and no duplicates, and find the owned endpoint. Targeted integration_ticket_notifications_site.py then passed all notification/retry/revocation scenarios. Original failed broad report is preserved; do not relabel it passed. No production pagination behavior was changed. Telegram topic-control browser fixture/build were separately verified after the suite started.

### Persisted observed Telegram topic directory

Added internal Relay Telegram Topic with unique channel/chat/thread key and indexed paged directory. Authenticated projected forum service events and successful topic actions update names/states, ordinary thread messages seed ID placeholders, late creation names fill placeholders, stale events cannot undo later edits, and deleted topics are excluded. Directory rechecks manager role, current-account channel, verified group endpoint and readable contact. The observed cache does not claim a complete provider topic enumeration. Cache persistence failure after a successful provider action preserves the successful API response to avoid inviting duplicate actions.

Installed schema/index and built UI on yrp.site. Topic name selector populates thread ID and name; mobile fixture closes the exact selected thread without errors/overflow. Real isolated integration_telegram_topics_site.py passes projection-hook replay (service event remains non-conversational), identity/order/state/revocation/role checks. Existing22 group integration scenarios pass;105unit tests ran with103passing and2optional live skips. Added new integration to broad runner. No live Telegram topic mutation occurred.

### Recovery readiness — actual installed-site finding

Read-only operations.recovery_status reports eight expected recovery jobs, scheduler disable reasons, missing/stopped/never/overdue/recent-start states and recent completion/failure only when supported by Scheduled Job Log. Overview exposes this only to managers; starts are explicitly not success claims. Actual yrp.site API and mobile browser show scheduler paused, disabled in site configuration, and disabled in System Settings, with all eight jobs never started. No scheduler configuration was changed. This remains an operational readiness gap; normal after-commit jobs are not proof of periodic recovery.

New guarded integration_operations_site.py validates real job/log records for paused/never/stopped/overdue/recent/failed/completed states and ordinary-agent denial, without executing jobs. Build and actual installed Overview rendering pass with no horizontal overflow. Added test to broad runner. Isolated review also has pause_scheduler=1 and no scheduler service. A Relay-scoped recovery runtime or authorized broader scheduler enablement plus timed recovery acceptance remains necessary.

### Installed Relay-only recovery runtime

Implemented opt-in recovery_runtime CLI: once/minute exact8method scheduling through existing Scheduled Job Type.enqueue, due-time/queue deduplication, stopped-job and maintenance gates, per-site lock and180second heartbeat. It leaves the general Frappe scheduler paused and requires relay_scoped_recovery_enabled. Manager Overview distinguishes Relay-only mode and missing heartbeat. Guarded runtime integration passes opt-in/maintenance/allowlist/missing/stopped/heartbeat checks; build passed.

Actual yrp.site preflight found zero pending rows in all9Relay work queues. Enabled only its Relay-scoped flag and started user service relay-core-yrp-recovery.service with restart-on-failure. Multiple timed ticks queued8jobs each with no missing/stopped/errors. Temporary job logging verified all8Complete in the actual Pilot worker; original logging settings restored. Actual mobile Overview displayed8recent completions without overflow. Evidence .runtime/installed-recovery-verification.json. No provider send was triggered; empty-queue scheduling proves installed periodic execution, not provider/fault-load acceptance. This local service is transient, not production reboot persistence. Runbook docs/relay-recovery-runtime.md added. Supervisor crash-restart check in progress.

Supervisor failure acceptance: deliberately killed only the owned Relay recovery process. systemd restarted it automatically (NRestarts=1, active/running); the new process recorded a successful8job scheduling tick with zero errors. General site scheduler settings remained unchanged.

### Remote link and multiselect search

Record-backed Core and Hub fields now use a 300 ms API search with bounded suggestions, cancellation and stale-response protection. Hub no longer embeds all account/grant options in security page payloads. See `remote-field-search.md` for covered controls and validation limits. Migration of customer history remains explicitly on hold.

### Daily summary prepared-report verification

The isolated summary integration now creates its own business/contact and executes both PDF and Excel daily-summary requests through Frappe’s native Prepared Report generation lifecycle. Both complete with private downloadable artifacts and retain the exact source-message list; Excel contains the generated overview. Existing evidence-cache, changed-source and revoked-access checks also pass. Enqueue dispatch is intercepted and the job entry point is invoked directly; AI responses are fixtures. This proves the populated native report/export integration, not installed worker scheduling or live AI acceptance. Evidence: `.runtime/daily-prepared-test.log`.

Daily-summary failure recovery: a new report request can retry a Failed cached summary only while its existing attempts count is below two. Permission, evidence and AI budget checks remain in the existing processing path; successful cached results are reused. The isolated model-timeout → next-request success → cache-reuse scenario passes, including native PDF/Excel report generation. No live AI invocation occurred.

Daily summary export clarity: Excel now uses a Daily summaries sheet with explicit summary reference, source-message count and all source references. PDF lists all source references and distinguishes daily-summary count from unique source-message count. Native PDF/Excel integration passes with fixture AI, including spreadsheet provenance assertions.

Ordinary-user report acceptance in the isolated database: PDF and Excel daily reports now run as Relay Communication User, rather than Administrator. Found and fixed the Relay status endpoint unnecessarily requiring the Desk Prepared Report User role; the endpoint now uses explicit Relay owner/source authorization. Download succeeds for the owner and is denied after conversation reassignment, without invoking AI. Generic Desk report permissions are unchanged. The test reloads current Relay Message schema to include its declared report permission.

Contextual media download: compared the old MessageActionMenu with Relay. Added a direct Download attachment action for persisted image/photo/video/audio/voice/document/animation messages, using the existing permission-checked attachment endpoint with download disposition. Text and pending messages do not expose it. URL filtering/encoding checks pass. Installed provider-media download acceptance remains pending.

Reply display: removed the duplicate raw provider reply-ID line from inbox bubbles, preserving the existing readable quote and permission-checked jump. Shared group content retains its reference. Group conversation review also identified remaining parity work: its history is manual refresh and its send path lacks the inbox’s durable status presentation; these remain incomplete.

Telegram group sends: the legacy Hub telegram.send alias discarded the outbox receipt and returned sent:true even when queued. Its worktree implementation now returns the canonical receipt (Hub package tests pass; binary not redeployed yet). Core now calls the already-live telegram.message operation instead. Group composer clears the draft/request identity only after a confirmed message_id; queued/uncertain responses retain both. Core client receipt-contract test and frontend build pass. Durable group action/history projection and automatic status checking remain outstanding.

Hub receipt fix deployment: built and started `.runtime/releases/relay-hub-telegram-receipts` after verifying and gracefully stopping the owned previous process. `/readyz` returned HTTP 200 and yrp.site’s authenticated verify_connection returned verified:true. No provider send occurred. Deployment evidence is in Hub `.runtime/telegram-receipts-deployment.json`; legacy telegram.send now returns actual receipts in the running binary.

Durable Telegram group dispatch: telegram.send now requires a stable request key and records Relay Message Action before provider I/O. Recovery rechecks channel/account/verified group binding, reads the existing Hub receipt and projects one outgoing message with topic/reply provenance. Rejected group actions use the existing reviewed retry route. Isolated lost-response recovery/duplicate checks pass; the 22-scenario group regression passes over 12 loopback HTTP submissions; frontend build passes. Group realtime/pending presentation and live provider verification remain unfinished.

Telegram group realtime history now refreshes at the bottom and preserves the reading position with a New messages indicator when scrolled away. Request generations reject stale history responses; busy operations defer refresh. Browser check used fixture group data with an actual private socket event: zero history fetches while scrolled at offset 100, indicator shown; clicking it performed one bounded fetch and cleared the indicator. Build passes. This is mixed transport/UI evidence, not live group provider acceptance.

Report download optimization: removed a duplicate full source-permission scan after status() had already performed it. Ordinary-user PDF/Excel integration now asserts exactly one source_report call per download and still verifies denial following conversation reassignment. This is a measured call-count reduction, not a large-dataset latency benchmark.

Chronological index optimization: history sorts by COALESCE(sent_at, creation), while old indexes covered record names only. Added contact/channel/endpoint timestamp indexes; MariaDB uses an indexed virtual effective timestamp and PostgreSQL uses expression indexes. Installed all three MariaDB indexes on yrp.site and ran its actual timeline query successfully. Temporary 100,000-row query benchmarks: MariaDB full sort ~100.21 ms → indexed ~0.05 ms; PostgreSQL ~59.27 ms → ~0.076 ms. Both plans removed the sort. These are single-query synthetic measurements, excluding permissions, payload serialization, network and concurrency. Temporary data was removed. Evidence: `.runtime/timeline-mariadb-benchmark.json`, `.runtime/timeline-benchmark.json`.

Timeline correctness after index installation: read-only yrp.site API pagination with limit two traversed all six installed messages in three backward pages and matched forward pagination and independent COALESCE(timestamp)/name ordering exactly, without duplicates. The isolated inbox regression also passed late-arriving chronology, cursor/contact boundaries, snapshot permissions, unread previews and migration suppression. Evidence: `.runtime/timeline-inbox-regression.log`. Installed data is small; this is correctness evidence, not a production-scale API benchmark.

Recovery journal optimization: added (status, modified, name) index and bounded per-state candidate queries (30 each, at most 90 merged, oldest 30 processed). The isolated integration compares results with the original globally ordered query and passes. Installed MariaDB EXPLAIN uses relay_action_recovery without filesort. This avoids sorting the whole unresolved set but does not establish recovery throughput under provider load.

Group recovery authorization regression: a revoked verified endpoint blocks reconciliation and reviewed retry before Hub I/O, and removes the action from pending-message results. After restoring binding, a reviewed retry preserves chat/topic/reply values; repeating that retry returns the same message without another provider call. Verified on isolated database with fixture Hub. Missing verified bindings now consistently raise PermissionError in the Telegram facade.

Group pending UI: queued/uncertain actions show their text/status and a separate journal-only Check status action. Private action events trigger reconciliation, deferred while busy. Confirmed recovery clears only unchanged text and preserves a newly edited draft. Browser API-fixture test: one send, one reconciliation, Next draft retained. Full-reload restoration and multiple simultaneous pending actions in this group panel remain incomplete.

Group pending restoration: added owner-scoped verified-endpoint API with 50-row cursor pages and current channel/account/contact checks. UI restores multiple unresolved group sends when selecting a group after page reload. Isolated tests verify exact intent restoration and revoked-binding denial. Browser fixture shows two pending sends before and after reload with zero send requests. Build passes; installed real group-provider acceptance remains pending.

Bounded group pending navigation: older requests now replace the current 50-item page instead of accumulating every page. Latest navigation is explicit, realtime refresh preserves the current cursor, and a new send refreshes the latest page if needed to retain the bound. Isolated pagination over 51 newly created queued group actions returns all IDs across pages without duplicates. Browser pagination behavior still needs direct acceptance; backend regression and build pass.

Hub access navigation (2026-09-24): Users, API tokens, Sessions and Password now use the same theme-aware auto-expanding overlay sidebar as the Hub workspace. Accessible icon labels, current-page state, hover/keyboard expansion, mobile backdrop/toggle/Escape, and close-on-navigation are retained; browser history updates the active route. Login remains a focused standalone form. Built and atomically deployed static assets to the live Hub UI directory without restarting its process; /readyz 200. Installed-assets browser test with intercepted security data verifies 54→220 px hover expansion without content shift, keyboard expansion, back navigation, different light/dark surfaces, mobile open/close, no horizontal overflow, no page errors and zero writes. This is frontend acceptance, not new authentication-policy acceptance.

Broad regression checkpoint (2026-09-24): Hub current-parity-regression.json ran 37 checks; 33 passed, four failed. Investigated failures rather than treating builds as acceptance. Fixed Core successful-send replay shape inconsistency (reconcile had added error:null only on replay). Updated channel simulator to the canonical telegram.message contract and typed-message fixture to valid Telegram reaction receipts and journal lookups; all 44 channel scenarios and 39 typed-message scenarios now pass. Prepared-report date test now explicitly establishes/restores its older timestamp instead of depending on timestamps from an earlier script; native report/date/ownership test passes. Full report remains the original failing evidence, not overwritten as green. Remaining Hub group callback failure includes obsolete acknowledgement expectations and a real compact-status gap: recipient_participant_id is currently dropped. That transport/projection gap remains open. Added Telegram recovery, typing and channel-campaign scripts to the future broad runner. Tests use isolated databases/local provider fixtures, not live acceptance.

WhatsApp participant transport (2026-09-24, not yet deployed as a coordinated Hub/Core release): compact status rows now optionally carry recipient_type and participant. Hub preserves these when reducing provider status envelopes; Core accepts bounded group-only participant values and reconstructs recipient_participant_id in its durable raw event payload. Legacy compact private receipts remain valid. Updated authenticated group callback fixture to acknowledge exact integer counts and separately verify unchanged realtime/lifecycle envelopes plus all four participant/status pairs. The previously failing Hub group simulation now passes with the race detector and isolated database. Compact batching tests and Core signed-validator tests pass. Per-participant projected message state and presentation still require implementation; this transport change alone is not completion of group read receipts.

WhatsApp participant persistence/UI (2026-09-24): added service-maintained Relay Delivery Receipt with one unique row per message/participant, separate from bounded message JSON, and a (message,name) paging index. Projection records each participant independently under the existing message lock before aggregate status dedup/ranking; replay/out-of-order updates do not regress participant state or change the message modified token. Read API rechecks conversation, channel/account and verified endpoint access, returns at most 50 rows, and validates cursors. Message info displays participant/status/provider time with realtime invalidation and bounded replacement pages. Forty-scenario isolated typed-message integration passes, including 54 participant rows, replay, different simultaneous statuses, revoked binding, and signed compact callback→durable event→participant projection. Initial new signed-callback assertion incorrectly expected a return from projection.project; corrected it to inspect persisted projection_status and reran successfully. Installed browser API fixture passes 50→4→50 rows, three fetches, no errors. Core table/index installed on yrp.site; Core workload reloaded; Hub participant-receipts binary deployed after Core schema. Hub readyz and actual Core connection verification pass. Live WhatsApp group receipts are still unverified pending the user's channel credentials; no real provider message was sent.

Receipt ordering correction (2026-09-24): aggregate and participant receipts now share an explicit evidence-order helper. Older timestamps cannot suppress a stronger Delivered/Read confirmation; weaker states still cannot regress confirmed delivery/read, and an old Sent event cannot undo a newer failure. Eight ordering tests and the 40-scenario isolated typed-message integration pass, including a signed group Read receipt timestamped before its stored Delivered receipt. Message modified remains untouched. Core workload reload requested for installed code. This is ordering/fixture evidence, not live provider acceptance.


### Operator read bubbles (24 September 2026)
Relay now follows the old Core message-bubble pattern: two overlapping avatars,
a double-check and “Seen by N” beneath each operator’s latest read message.
Clicking opens a viewport-bound popover with reader names/times and assigned
operators still waiting. Provider group-participant receipts remain independent.
Visible-window cursor lookup is bounded to 150 messages/100 markers with batched
profiles; coverage loads on demand. Reads publish contact-room invalidations only
when evidence/cursors change. Light/dark and mobile browser fixtures pass; isolated
DB tests cover cursor placement, exact read evidence and revoked access. Installed
yrp.site returned two real cursor markers via HTTP 200. Multi-operator live socket
interaction has not yet been manually accepted.


Case-assignee search correction (24 September 2026): the broad 40-check receipt
regression found two failures (unit metadata contract and case agent search).
Case candidates were limited globally before assignment filtering, hiding valid
operators on larger sites. Agent lookup now uses role subqueries without DISTINCT
joins and applies conversation assignment/team/manager eligibility before its
30-row limit; final business-document permissions remain checked. The isolated
case workflow passes with 40 unrelated agents ahead of the assigned agent,
literal wildcard searches, stale edits and revoked access. All 114 unit checks
complete successfully (two optional skips). Receipt metadata checks explicitly
validate its unique, immutable service-only deduplication key. The original broad
report retains its failures; these targeted reruns do not imply a fresh full-suite
pass or live provider acceptance.


Saved-reply library paging (24 September 2026): replaced the unreachable 20-result
ceiling with stable title/name keyset pages, bounded to 20 results per request.
The picker replaces pages, provides Previous/More controls, resets on search or
source changes, and defers API search until IME composition finishes. Existing
published/channel/source permission restrictions remain. Isolated typed-message
integration passes 41 scenarios, including 45 same-title replies paged 20/20/5
without duplicates; component IME test and installed-assets browser fixture
(20→5→20, select into composer, zero errors) pass. No real provider send was made.
Business actions attached to canned replies remain unimplemented.

Saved-reply actions (24 September 2026): supersedes the earlier missing-action
entry. Desk can attach a registered, schema-validated action to a chat reply;
the picker exposes an explicit labeled execution button. Server-owned arguments,
current-operator permissions, source/channel checks and durable receipt replay
protect execution. Included Add internal note action survives a crash after its
comment commit and before receipt persistence without duplicate notes. The
43-scenario typed-message integration, 114 unit checks (two opt-in skips), IME
component test and lost-response browser fixture pass. Installed receipt schema,
configuration fields, action catalog and assets are deployed. Live business-action
execution is not yet accepted; no customer message or live business write was
performed. See saved-reply-actions.md for configuration and hook contracts.

Template language UX (24 September 2026): replaced the raw language-code field
with readable English/native-name choices using the provider codes published in
Meta's WhatsApp Node.js SDK LanguagesEnum. Existing uncommon codes remain selectable;
a separate custom-code option avoids silently blocking newer provider languages.
Template selection labels also show readable languages, and the template preview
uses theme tokens instead of a light-only background. Domain test verifies Tamil
payload code preservation, regional English and uncommon existing codes. Installed
assets browser fixture selects “Tamil · தமிழ் (ta)” correctly. No template was
submitted to Meta; provider approval and media-sample upload remain unverified.
Catalog source: https://github.com/WhatsApp/WhatsApp-Nodejs-SDK/blob/main/src/types/enums.ts

Collaboration recipient search (24 September 2026): note/task colleague lookup
now filters assignment/team/manager candidates before the 30-row bound, sharing
the case picker query and retaining final business-record permission checks.
The old Find button, separate dropdowns and Add mention step are replaced with
shared debounced remote single/multiselect fields, capped at ten mentions.
Removed hard-coded light colors from the notes drawer, textarea and task cards.
Isolated collaboration tests pass with 40 unrelated users, wildcard search,
revoked recipient exclusion, task ownership and notification boundaries. Installed
assets browser fixture verifies remote selection, correct note payload and distinct
light/dark surfaces without errors. Actual yrp.site colleague query succeeds with
nine accessible options; no live note was created by this browser fixture.

New-conversation queued UX (24 September 2026): a durable Queued acknowledgement
now closes the start dialog and opens its conversation, where the existing
pending-action ledger restores the message as Queued. It no longer traps accepted
messages behind Check delivery or represents queued admission as confirmed delivery.
Unknown/rejected attempts retain recovery controls and offer Open conversation.
Accepted intents release their browser draft key; unknown responses retain it for
safe retry. Three component cases (Submitted/Queued/Uncertain) and installed-assets
browser fixture pass: one start submission, dialog closes, queued bubble restored.
No live provider send was performed.

Broad regression checkpoint after chat/actions changes (24 September 2026):
Hub `.runtime/chat-actions-regression.json` records 40/40 checks passing, including
Hub Go race/database integration and static analysis, Core unit contracts and all
33 registered Core integration scripts, frontend data/component tests and whitespace
checks. The earlier receipt-parity report remains preserved with its original two
failures. New coverage includes saved-reply action crash/replay, bounded reply
paging, read cursors, scoped case/colleague search and queued-conversation UX.
This run uses isolated databases and local provider/model simulators; it does not
prove live provider delivery, production inference, live calls or sustained-scale
acceptance. Reporting and acceptance-checkpoint docs were corrected to distinguish
implemented fixture-proven behavior from those remaining acceptance requirements.

Open message-info refresh (24 September 2026): message info now follows replacement
rows from the visible-message snapshot refresh and refreshes operator read coverage
on read events, reconnect and visibility recovery. It no longer freezes the initial
status/coverage while the timeline updates. Generation guards discard stale responses
and closing/changing conversation invalidates outstanding reads; a failed coverage
refresh clears old reader evidence. Two reactive-state tests pass. Installed-assets
browser fixture verifies Sent→Read and 0→2 team views while the dialog stays open,
using visibility recovery and intercepted APIs. This is not a new live-provider or
multi-user socket acceptance claim.

Internal-note realtime (24 September 2026): note create/edit/remove/task-status
writes now publish payload-free comments invalidations after commit in the contact
room. The open drawer refreshes through its permission-checked API, preserves drafts,
defers refresh during writes, and offers New note updates while older history is
loaded. Request generations discard stale page responses. Isolated collaboration
checks pass, including exactly one comments invalidation on create (notification
invalidation is separate). Browser fixture verifies draft and older-history retention.
Installed yrp.site acceptance without API interception: a metadata-only contact-room
comments event caused notes API requests to increase from one to two, with the unsent
draft unchanged. No notes or customer messages were created. Core workload and
assets updated; this proves this installed refresh path, not all workspace realtime.

Summary drawer realtime (24 September 2026): replaced unconditional 2.5-second
pending-job polling with contact-room report/message invalidations, reconnect and
visibility recovery. A 15-second pending-job fallback runs only while the socket
is disconnected. Refresh preserves channel/period choices, defers during requests,
and rejects stale responses after source changes or new generation requests.
Summary surfaces use theme tokens. Reactive test verifies live/no-poll and offline
fallback; browser fixture verifies Pending→Ready, preserved choices and zero new
summary-generation requests. No real AI inference or populated live summary job was
run for this change; those acceptance gates remain open.

Case panel refresh (24 September 2026): subscribes to case invalidations,
reconnect and visibility recovery. The list refreshes automatically; an open editor
retains its draft and offers an explicit Reload case and discard edits control.
Refresh waits for an in-flight write. Existing backend modified-token checks remain.
Reactive component test verifies list refresh, draft retention and explicit reload;
site build passes. Populated browser/multi-operator case-event acceptance remains
unverified, so this is implementation evidence rather than completed case acceptance.

Case refresh browser acceptance (24 September 2026): installed-assets fixture
opens Case history, edits a case field, triggers visibility recovery, verifies the
update notice without draft replacement, then explicitly reloads and verifies the
server value. Zero case writes and zero browser errors. An initial test waited on
the first page textarea (the chat composer); corrected it to wait for the case
reload notice to disappear and assert the case-field value. Real multi-operator
case mutation/socket acceptance remains outstanding.

Bounded topic membership validation (24 September 2026): topic saves no longer
fetch every other topic and decode all message lists in Python. A parameterized,
contact-scoped database JSON-membership query returns at most one conflicting row,
excluding the topic being edited. The existing conversation lock, 500-message
input bound, permissions and human-edit preservation remain. Isolated PostgreSQL
acceptance passes 1,000 topics / 500 candidate IDs, exact vs prefix matches,
escaped IDs, self/contact exclusion and existing topic lifecycle checks. Installed
MariaDB passes exact membership and self exclusion using one rollback-only fixture;
verified the temporary row is absent afterward. Core workload reload requested.
This bounds application reads, not a claim of indexed JSON lookup or million-row
throughput; normalized membership indexing remains a possible scale improvement.

Topic organization refresh (24 September 2026): topic saves now publish a
payload-free topics invalidation after commit in their contact room. The panel
refreshes its list on invalidation/reconnect/visibility recovery, preserves open
drafts with an update notice, and defers refresh during writes. Contact/request
generation guards reject stale directory and save results after navigation.
Database integration verifies the event plus existing membership/permission/replay
contracts; reactive tests cover draft retention and old-contact response rejection.
Core workload reload requested and site assets rebuilt. No live multi-operator
topic-edit acceptance is claimed.
Browser fixture also passes topic draft preservation followed by cancel/refresh
showing the updated list, with zero saves/errors. Initial Title locator omitted
the required-field suffix; corrected the locator and reran successfully.

### Template sample upload transport — 2026-09-24

Hub now has an account-scoped `templates.media_upload` operation and optional
`app_id` channel configuration. It validates image/video/PDF samples using the
existing 4 MiB attachment boundary, creates a Meta upload session, uploads binary
bytes with offset zero, and returns the sample handle rather than a message
media ID. Provider session paths are restricted before sending credentials.

Provider references: [create session](https://www.postman.com/meta/whatsapp-business-platform/request/qqtpgcu/upload-media-step-1-of-2-create-session)
and [upload bytes](https://www.postman.com/meta/whatsapp-business-platform/request/13382743-871ea332-a6a4-4ad0-800a-0be9796b1933).

Local HTTP fixture covers the two requests, binary content, authentication,
signed session query preservation, rejected unsafe session paths, missing app
ID and disabled templates. Hub WhatsApp, accounts, hubmcp and command package
tests pass. This is transport implementation evidence only: Core manager
boundary/editor wiring, installed deployment and real Meta upload acceptance
remain unfinished. Existing credentials have not been used or changed.

Template sample editor wiring now implemented locally: manager-only Core
operation, same-site Hub verification, bounded upload payload, native file
chooser restricted to header format, uploaded filename feedback and advanced
manual-handle fallback. Header format changes invalidate the sample; failed
replacements retain the old handle. Ten WhatsApp boundary tests and two editor
state tests pass; frontend development build succeeds. Hub MCP authorization
also explicitly tests that account-read tokens cannot upload template samples.
Installed build/deployment and provider acceptance are still outstanding; do
not treat the local build as an installed-site acceptance result.

Template upload installed-build check: Core `build:site` passed and backend
reload requested; Hub deployed as `relay-hub-template-media` (PID 2918406),
readiness 200. Browser `templateSampleAcceptance.js` uses installed assets with
fixture API responses: exactly one PDF upload request, returned handle shown,
changing to image clears the handle, no page errors. No Meta request or template
creation occurred. An unmocked authenticated GET to `whatsapp.connection` on
`yrp.site` returned HTTP 200 and `configured:false`; live WhatsApp upload
acceptance remains pending account configuration. Migration remains on hold.

### Pushed channel receipts — local implementation

Core now durably accepts signed Telegram/email status batches through
`inbound.receive_channel_statuses`; content digests deduplicate batch replay.
Telegram projection finds the original request key, rechecks the original
sender's access and current account/channel binding, and creates the outgoing
message through the existing deduplicated finish path without a Hub lookup or
provider send. Batch projection can retain its transaction instead of committing
per action. Email rows remain unresolved pending their projection implementation.

Isolated Telegram recovery integration passes: a pushed submitted receipt
projects exactly once, replay/stale uncertain receipt cannot regress a submitted
message or change its modified timestamp, and a callback that arrives before a
submission timeout remains authoritative. The timeout race required updating
private/group/new-conversation submission error handling to lock and reload the
known receipt before assigning an uncertain outcome. No installed-site reload
or live provider acceptance is claimed. Email recovery, complete callback HTTP
round-trip acceptance and coalesced batch invalidation remain unfinished.

Email pushed receipt projection now implemented locally. New email sends use
the actor-scoped Core action key at Hub, while preserving the browser request
key for local history lookup. Signed submitted receipts reuse email validation
and history projection with provider I/O disabled, preserving content, threading,
recipient and attachment metadata. Projection runs as the original sender and
keeps batch transaction ownership. Failed/uncertain receipts update only the
original action. Submission error handling cannot overwrite an already pushed
receipt. Existing pre-change email attempts retain their original Hub keys;
no historical key rewrite or data migration was performed.

The isolated email suite passes normal sends, private attachments, threading,
recipient revocation, stable retries, pushed lost-response recovery, original
owner preservation, duplicate receipts and a callback-before-timeout race.
Email unit tests also pass. The installed Frappe realtime implementation
coalesces identical after-commit event/message/room entries in a transaction;
the new callback path avoids per-action commits to retain that behavior.
Authenticated HTTP end-to-end acceptance and deployed status-worker activation
are still outstanding. No real email was sent by these tests.
