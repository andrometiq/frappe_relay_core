# Relay AI events and business events

## Knowledge, events and skills

**Knowledge base** (standing owner instructions, "work like this") is the set of global desk playbooks in `Relay AI Playbook` (see [Playbooks](#playbooks)). The AI knowledge screen and its API (`ai.knowledge.directory` and `ai.knowledge.save`) read and write only these rows. Each row has plain-text instructions and optional company/business-type scope. The prompt labels these trusted instructions separately from the skill instructions. Verbatim-copy checks include applicable instructions both before proposing a reply and at delivery. At most 100 enabled global playbooks and 8000 applicable instruction characters are accepted; an oversized configuration stops inference for staff review rather than silently dropping rules.

**AI events** stores facts about an occurrence in the existing `Relay AI Event`, for example "Riverside Traders Association event on 5 November at Sampleville". It has its own screen, description, audience, company and publication window. Text-only events publish their description through the existing memory-build job without a model call. Attachments and links still use the existing bounded source reader and configured event-memory model. Only published, enabled events within the audience/company/window enter the reply. Events and the sender's conversation memory appear in the input's `reference_data`, labelled as facts, never instructions. The existing revision check fences delivery if an event changes.

**AI skills** stores intent targets, task instructions, reply style, configured reports and ordered actions in `Relay AI Skill`. The editor calls these skills; it does not call them events or mix their instructions with event facts. Select a model, execution user, handoff owner, channel and business type. Configure one company and an eligible triage owner on the channel. A channel can have no company only when every read capability of the skill is company neutral and the skill has no draft action, or when the site has no Company DocType. A company-neutral read needs a site without Company or with exactly one Company. Set the daily spend cap (USD) next to the daily model limit; an empty or zero cap uses 2. Relay Settings supplies a backup handoff owner. Without an eligible owner, Core retains a recoverable ticket intent and stops AI work.

Install/migrate idempotently creates one disabled **Default support** skill, identified by the unique `sample_key = relay-default-skill`. Re-running the hook preserves owner changes. Configure its channel, model and users before enabling it. It is the fallback for every enabled business type on its channel, so event and knowledge questions get an answer when no specific skill matches. It still binds the sender's own business link and grants no cross-company identity or report access. Its reports work only for its own business type. Channels without an enabled fallback go to triage. It starts in Shadow mode with a reply action and no reports.

The existing **Enable AI features** setting (`enable_ai_features`, frontend `capabilities.ai`) hides knowledge, events, skills, channel AI steps and ticket AI explanations. Dedicated AI APIs, evals, memory backfill and generic AI document access are gated server-side. AI settings cannot be changed while disabled; the System Manager can still turn the switch on. This switch is separate from channel automation and the site automation gate.

Relay uses the shared AI Model, AI Provider Account and bounded adapter from `frappe_tools`. Shadow records proposals and the episode ticket without automatic replies or business drafts. The saved-skill preview uses authenticated identity and the same decision path. It sends nothing and creates no operational run, ticket, approval or business document, but can call the configured model and consume budget. Unit tests mock this boundary.

## Languages and voice

The latest clear customer text determines the reply language and script. Short acknowledgements such as “ok”, numbers and emojis retain the last clear language from permission-checked incoming messages in the same conversation and business scope. For voice/audio, AI matching and replies use the stored `Relay Message.transcript`; they never infer words from an attachment placeholder. A missing/pending/failed transcript produces a specific staff-review reason through the existing handoff path, without calling a model to guess. The transcript is permission checked and hashed into the per-message scope so changes invalidate continuation/delivery. Search confirmation compares the conversation identity separately from message and transcript hashes, and checks the original transcript hash before each read; typed or spoken confirmations may therefore follow a voice request.

Local Unicode letter counts provide script hints for Malayalam, Devanagari, Tamil and other scripts. Recognized non-Latin question words take precedence over Latin event/product names in mixed messages. Language-neutral replies such as numbers, dates and amounts pass the language check. The model resolves languages sharing a script (Latin does not necessarily mean English; Devanagari does not necessarily mean Hindi). The reply path rejects a wrong dominant script before proposing delivery. This is a script check, not proof of linguistic fluency. Fixed handoff, privacy, disclosure, approval and empty-result notices support Malayalam, Hindi, Tamil, Telugu, Kannada, Bengali, Marathi and English. Devanagari text is Marathi only when it has more common Marathi words (for example `आहे`, `कधी`, `मला`) than Hindi words; other Devanagari text gets the Hindi notice. Search announcements and code-owned ledger labels support Malayalam, Hindi, Tamil and English. Other scripts use the model for ordinary replies; their fixed notices fall back to English. The bare reply words `person`, `ആൾ`, `व्यक्ति`, `ஆள்`, `మనిషి`, `ವ್ಯಕ್ತಿ`, `মানুষ` and `व्यक्ती` reach a person. Native-script date confirmation accepts `അതെ`, `हाँ`, `हां` and `ஆம்` as well as the existing English confirmations.

The privacy guard keeps combining marks with their letters and normalizes Unicode decimal digits for phone comparisons. A phone in Malayalam/Devanagari digits is allowed only when its normalized value is authorized; ordinary text, dates and short numbers are not treated as phone numbers.

The eval cases include Malayalam, Hindi, Tamil and English event questions, a general event overview and a Malayalam voice transcript with synthetic event facts. Grading checks expected outcomes, text and dominant reply language/script. Evals create no operational messages or tickets; the eval API is AI-gated and live-model use still needs its existing explicit opt-in.

## Select and record an episode

The callback authenticates and stores the source. The automation drain creates one run per incoming message. Core creates or reuses an assigned episode ticket before skill tools run. The message stores its ticket link. A replay retains that link, including after closure.

An active flow or confirmed search continues through the same admission path. Otherwise Core matches enabled skill targets within the resolved business scope. An exact configured trigger can select a skill without a classifier. Classifier selection requires a score of at least 0.85 and a lead of at least 0.15. Invalid classifier output or a timeout causes company triage. A valid result with no confident match uses the configured default skill when eligible; an ambiguous exact trigger still goes to triage. Human requests never use the fallback. A request for a person bypasses the model. A message that says an answer did not help (for example "that was not helpful", "this doesn't help", "you did not answer my question" or "help aagala") counts as a request for a person; the skill model also hands off when the sender says so in other words or languages. When the classifier or the skill model reports an identity claim (the sender says they write from another person's phone, asks as a relative, friend or agent for another account, claims a role such as supervisor or HR to see other people's records, or says their number changed), Core sends a fixed notice in the sender's language that asks them to message from the account's registered number. This decline reads no record and creates no ticket, and it takes priority over a privacy decline and a human request.

Unresolved senders and business choices also receive company triage tickets from the stored Hub event. These tickets expose a sanitized summary. Enrollment can attach the projected message to that ticket. A company or active-episode conflict keeps the source in triage.

## SEARCH and EXECUTE

The model has two tools: SEARCH and EXECUTE. SEARCH exposes only installed reports selected in the skill. The current report catalog contains `customer_ledger` and `supplier_ledger`, backed by the existing scoped Reader and code-owned ledger arithmetic. Their GL Entry fields, party scope and company field are fixed. The owner maps the authenticated provider identity field. Legacy generic `get_doc`/`get_list` references remain stored/editable but are not model tools; select a report to replace them. Arbitrary MCP functions, methods, Python, SQL and URL tools are unavailable. The model must hand off data questions when the needed report is not configured or no authorized result is available. Every decision must include a boolean `data_question`; missing or invalid classification is rejected. A model-declared data question without a report result or search also fails closed to handoff.

The authenticated sender identity unlocks only that person's records. Text entered in a message cannot establish identity. Reads require private transport evidence and a verified endpoint. A linked Contact user is authoritative. A disabled or denied linked user cannot fall back to the skill execution user. The configured execution user applies only when no user is linked.

Each read applies user, company, business, sender, document, and field permissions. Fixed filters apply before pagination. Model filters can only narrow them. Dynamic party links also fix the party type. A document name must pass the same filtered query before loading. When a pack reads the sender's own business record and the model gives no name, Core uses the authenticated record name. Core checks the read evidence again before delivery and recovery. Empty or inaccessible results require staff review.

Core records a search plan and sends its statement through the message journal before reading business data. The plan includes purpose, reference, fields, and filters. Core sets the fields from the approved pack. A field list inside the search arguments gets the same check. A model search that names a field outside the pack is rejected. When the final answer declares a search with an undeclared filter or another invalid shape, the model gets one correction turn with the reason. A search for another party is declined without a correction turn. When the confirmed turn returns the authorized plan again instead of calling SEARCH, Core reads exactly that plan. Ledger searches always require confirmation of the exact date range. A changed plan requires a new declaration. An uncertain announcement cannot authorize SEARCH.

EXECUTE follows the skill's declared steps in order. A plain answer is always allowed when the skill declares a reply step: it runs that reply step alone, without the other steps. The shared Relay Flow Action journal stores typed inputs, scope, versions, capability hash, status, and results. The AI actions are the Core `reply` action and the approved capability action packs, such as `erpnext.payment_entry_draft`. Migration converts saved `create_draft` steps to `erpnext.payment_entry_draft`. A key that two sources declare stops the action registry. An action method must belong to the app that declares it. The current draft target is Payment Entry. The skill must allow that target and its typed fields. Core supplies company and party from the authenticated scope, inserts through normal document validation, and requires `docstatus = 0`. It never submits a document. The ticket action history links each draft so staff can open, check, and submit it. A Ticket only skill creates the ticket without model execution, replies, or drafts.

**Allow AI write actions** (`Relay Settings.allow_ai_write_actions`) is off by default. While it is off, AI only reads and replies: the model sees only the reply steps of a skill, a proposal or a persisted step of any other action fails and the run hands off, and a staff approval cannot run a draft. The prompt then tells the model that it cannot change, cancel, create or record anything, and that it hands such a request off to staff on a ticket. Skills keep their declared actions, so turning the setting on restores them.

A draft action always waits for staff approval. Core records the proposal as `Awaiting approval` with an expiry 48 hours later, sends a fixed "recorded for staff review" notice, and stops. Recovery does not resume a waiting run after its notice is in the delivery journal. The same action with the same input for the same business within 7 days is a duplicate request: Core records it as `Rejected` with `duplicate_of` and hands the run off. `approve(name, input_hash, scope_fingerprint)` checks that the approver can write the ticket and create the draft target now, and refuses an expired proposal. `reject(name, reason)` records the reason and hands the run off with it. An hourly job sets unapproved proposals to `Expired` and hands their runs off. A changed capability hash between the decision and execution cancels the run.

Each action uses a stable command key and input hash. A changed input under the same key fails. Local writes and their journal results share a transaction. Replies use the existing durable message journal, with Core supplying the destination. An uncertain reply blocks later steps until its receipt is resolved. A retry cannot create a second draft or bypass changed permissions. Bounded image input requires a vision-capable model and attachment access checks.

## Playbooks

`Relay AI Playbook` holds owner and app instructions. A playbook is trusted owner text under the system rules. It never widens tools, scope or identity. Customer replies use only playbooks with audience `customer`.

| Kind | Name | Edited by | In the prompt |
|---|---|---|---|
| Global (`is_global`) | `desk/<name>` | Relay managers | Full text in every prompt of matching company and business type |
| Bound to a skill (`Relay AI Skill.playbooks`) | `desk/<name>` or `<app>/<name>` | Relay managers or the app file | Only `name: description` in an index; the model loads the text with `load_playbook(name)`, which counts as a tool call |

- An app ships a playbook as `skills/<name>/SKILL.md` at its source root, the folder that Frappe Flow also reads. The frontmatter needs `name` (the folder name), `description` (at most 1024 characters) and `relay: customer` or `relay: staff`. Relay ignores a file without `relay:`. Example: `skills/handoff-etiquette/SKILL.md` in this repository.
- `playbooks.sync` runs after migrate. It writes each file as a locked row named `<app>/<name>` and deletes the app rows whose file is gone or has no `relay:` key. An invalid file is logged and keeps its old row. A folder with more than 2000 entries is skipped and keeps all rows of that app. Sync never changes or deletes desk rows. Owners can enable, disable, scope or make global an app playbook, but its text changes only through its file.
- `load_playbook` loads only enabled, non-global customer playbooks bound to the skill that match the sender company and business type. Any other name gives "Playbook is unavailable".
- The reply guard verbatim-copy check takes the global text and the text of every bound playbook, loaded or not, before the reply and again at delivery.
- The patch `move_ai_knowledge_to_playbooks` copied each `Relay AI Knowledge` row (disabled rows too) to a global playbook named `desk/<old name>` and set `migrated_to` on the old row. It stops the migration when a row count or a prompt text differs. `Relay AI Knowledge` is read only for one release.
- When the skill has a bound playbook for the sender, the prompt lists the bound playbooks as `name: description` lines and the model gets `load_playbook`.

## Tool registry

SEARCH and EXECUTE are the built-in tools of `relay_core.ai.registry.builtin.CoreTools`. Their behavior is unchanged. An app adds a code tool for logic that a read pack cannot express. Declarative read packs stay the preferred form for plain reads.

```python
from typing import Annotated, Literal
from relay_core.ai.registry import ToolContext, relay_tool

@relay_tool(audience="customer", label="Open orders", business_doctype="Customer")
def open_orders(status: Annotated[Literal["Open", "Delivered"], "Order status"] = "Open", limit: int = 5,
                *, ctx: ToolContext) -> dict:
    """List the sender's own open orders."""
    return {"rows": ctx.read_list("Sales Order", fields=["name", "status"], filters={"status": status}, limit=limit)}
```

- The app lists the tool in its `relay_ai_tools` hook, for example `relay_ai_tools = ["acme_app.relay.tools.open_orders"]`. The path must start with the app name.
- The schema comes from the type hints: `str`, `int`, `float`, `bool`, `Literal`, `Enum`, `list[...]`, `Optional`, `Annotated` descriptions and `TypedDict` closed objects. Other hints fail at import. The docstring is the model description. Arguments are validated against the schema before the call.
- `ToolContext` is never shown to the model. It holds the run, skill, user, business and scope from `service.context`. `read_list` and `read_doc` read as the run user, add the business link and company of the sender, allow filters that only narrow them, and apply the read pack field rules (no text, table or sensitive fields). Like a read pack, a read needs a verified sender linked to the business, a sender of the skill business type and, for a DocType with a company field, the channel company.
- `capabilities.sync` (after migrate) stores each tool as a `Relay AI Capability` of kind Tool named `<prefix>.<name>`. The manifest holds the schema, audience, kind, label and `code_hash` (SHA-256 of the source). A code change gives a new hash and status Changed. A tool that does not import is logged and becomes Missing. Core tools approve themselves; other apps must be in `trusted_adapter_apps`.
- A skill selects a tool in `allowed_tools` like a read pack. Only approved tools of the run audience and the skill business type are offered. A staff tool never runs for a customer. The approval, audience and code hash are checked again at each call. An `action` tool is not offered yet: it must first propose through the action journal.

## Reply loop

`adapter.complete` runs one bounded tool loop on frappe_tools `AgentRun` (`registry.loop.SkillRun`). The tool set is built for each run:

| Tool | Offered when |
|---|---|
| SEARCH | The skill has read packs for the sender business type |
| EXECUTE | The skill declares actions |
| `search_knowledge` | The skill binds an enabled customer knowledge base and the site is on MariaDB |
| `load_playbook` | The skill binds a playbook that applies to the sender |
| `remember` | **Customer memory** is on, the sender has a business, the run has a record and the site is on MariaDB |
| App code tools | Selected in `allowed_tools`, approved, customer audience, kind `read` |

- The model gets at most `max_tool_calls` tool calls per reply (default 4, never more than 6). After the last call, the final turn may not call tools. A model that still calls a tool fails the run, and the run hands off.
- The takeover check runs before and after each tool batch and before each tool call. A staff takeover between tool turns stops the run.
- Each tool result to the model is at most 4000 characters. Built-in tools give fixed error texts. An app tool error reaches the model only as "This tool is unavailable". A tool call after an EXECUTE proposal is refused. Two tools with one name fail the run.
- Reply guard inputs: `search_knowledge` results allow contact values only. App read tool results allow their contact values and record names, like read pack results. Bound playbook texts and Skill-scope facts join the verbatim-copy check.
- The run records `tool_calls` (name, SHA-256 of the arguments, status and milliseconds; no row data) and `usage` (the turns and the token usage of each attempt's final turn, which is all the engine reports).
- The capability hashes of a run include the code hash of each tool the skill may offer. A tool change between the decision and delivery stops the reply. The decision lists the knowledge sources whose chunks the run returned, and delivery stops when one of them is no longer searchable for the sender.
- When more than 40 messages of the sender address wait since the last memory fold, the reply queues `memory.fold` for that address (deduplicated). The next reply reads the new summary. No summary model call runs inside a reply.
- Provider guard: every Relay AI call (`adapter.route`) refuses an AI Model whose AI Provider Account auth type is not in Relay Settings `allowed_ai_auth_types`. The default is `ChatGPT Login` only, and an empty value means the same. Add `API Key` or `Setup Token` only on purpose, because they use paid API credit. A refused model fails the run, and the run hands off.

Relay Automation Run also has `feedback_rating` and `feedback_comment`, which `fact_memory.rate_run` sets.

Reply prompts trim in this order: memory facts, record memory lines, history, knowledge chunks, events. Recalled fact memory (`reference_data.memory`) never allows a contact value in the reply guard. The guard copy check takes every trusted owner text of the prompt.

## Knowledge bases

A `Relay AI Knowledge Base` holds reference documents that a skill can search with the `search_knowledge` tool. Bind it in the skill's `knowledge_bases`. It has an audience (`customer` or `staff`), an optional company, a description that tells the model what it holds, and a run-as user for DocType sources. A customer run searches only enabled customer knowledge bases of the conversation company or of every company. A staff knowledge base is never offered to a sender.

Each `Relay AI Knowledge Source` is chunked into `Relay AI Knowledge Chunk` rows: paragraphs first, then sentences, then words. The default chunk is 1200 characters with a 150-character overlap. Ingest uses no model and no embeddings. It runs in the long queue after commit, one run at a time per source, and sets Status to Pending, Processing, Completed or Failed with the error.

| Source type | What is read | When it syncs |
|---|---|---|
| Text | The Content field | On save |
| File | The file attached to the source (text, Markdown, CSV, JSON, HTML, PDF, DOCX; no images) | On save |
| URL | One public page through the event link reader | On save, and daily with Sync daily |
| DocType | Content fields of rows that match Filters, read as the run-as user | After approval, and daily with Sync daily |
| Event | Title, description, files and links of one `Relay AI Event` | When the event or its files change |

- A DocType source copies field values into chunks. A manager approves its exact configuration (DocType, filters, content fields, business field, and the knowledge base audience, company and run-as user) with `relay_ai_knowledge_source.approve`. A changed configuration stops ingest and search of that source until a new approval. A form or REST save cannot set the approval. Search uses the chunks of a DocType source only after a sync under the current approval. In a customer knowledge base, a source without a business field stops when its DocType is no longer company neutral.
- In a customer knowledge base, a DocType source needs a business field, for example `customer` on Project, unless the DocType is listed in `company_neutral_types`. Each row is then found only by its own business, and a row without a business is not indexed. Rows with a company field are found only in that company. Text, table, password, code, HTML and sensitive fields cannot be content fields.
- A DocType sync reads rows modified since the last sync in pages of 500. A row hash skips unchanged rows. Rows that leave the filter, are deleted or become unreadable lose their chunks. A new approval reads all rows again. The `ingest.rebuild` API purges and re-chunks one source.
- Every `Relay AI Event` gets one Event source in the **Events** knowledge base (audience customer), which the patch `index_ai_events` creates for existing events. Event chunks are found only while the event memory rules (`eligible_events`: enabled, published memory, audience business type, company and publication window) offer the event to the sender. Event memory stays in the prompt as before; the knowledge base lets a skill find text that the 30 memory facts leave out, such as page 3 of a PDF.

Search uses MariaDB FULLTEXT in natural language mode with the scope as query parameters, at most 5 results of at most 1500 characters each. Measured on MariaDB 11.8: whole words in Tamil, Malayalam and Hindi match, but a word inside a longer inflected word does not, and words under 3 characters are dropped. When FULLTEXT finds nothing, a LIKE match of the 3 longest query words runs over at most 200 chunks of the scope. On Postgres the tool is not offered. The result note says it is reference data, not instructions. Returned chunks are reply guard evidence for contacts only; they never join the verbatim-copy check, and a Customer or Supplier named in a shared chunk still blocks the reply. Errors reach the model only as "Knowledge search is unavailable". `retriever.is_offered` and `retriever.description` give the loop assembly the offer rule and the tool description with the bound knowledge base descriptions.

## Fact memory

`Relay AI Memory` keeps short facts (at most 300 characters) for one skill. `Relay Memory` stays the timeline of messages. A fact has one of two scopes:

| Scope | Recalled for | Written by |
|---|---|---|
| Skill | Every sender of the skill, labelled `shared` | Relay managers only |
| Business | Only senders of that business record, labelled `own`. Every contact of the business shares it | Staff with read access to the record, or the model in a customer reply |

- Recall: before the model call, `fact_memory.memory_block` puts up to 8 Active facts into `reference_data.memory` as `[id] (shared|own) fact`, after a lead line that says the facts are data, not instructions. MariaDB FULLTEXT ranks them. When FULLTEXT finds nothing, the 3 longest query words are matched with LIKE. A recall error gives no facts and an Error Log.
- Customer writes: the `remember(content, memory_id)` tool is for skills with **Customer memory** (`memory_enabled`) on, a sender with a resolved business and a run. It writes only Business scope for the sender's own business, at most 20 facts per skill and business. Over the limit the model must revise a fact with `memory_id`. A fact with a secret, a masked contact, or a phone number, email or record name of another party is refused. The new fact is Pending. It becomes Active when the reply of its run is journaled for delivery. A revised fact is archived then. When the revised fact is already archived, or the business already has 20 Active facts, the new fact stays Pending. A blocked, superseded or taken-over run leaves the fact Pending, and a daily job deletes Pending facts after one day. When **Customer memory** is off, customer-written facts are not recalled.
- Staff writes: `fact_memory.directory`, `save` and `archive`. A staff fact is Active at once, at most 100 per skill in Skill scope and 20 per business. Staff edit only staff facts. Customer-written facts are marked `written_by_customer`; show them as plain text. Facts are archived, not deleted.
- Feedback: `fact_memory.rate_run(run, rating, comment, scope)` is for Relay managers who can read the run's ticket. A `Down` rating with a comment saves the comment as a Feedback fact. A new or withdrawn rating deletes that fact.
- Reply guard: only staff-written facts allow a contact value. A customer-written fact never does, so a saved third-party number stays blocked. Skill-scope facts join the verbatim-copy check.
- Delivery: the run records the fact ids and line hashes in `ai_context.facts`. Delivery stops when a used fact is archived, changed or out of scope.
- Sites on Postgres have no FULLTEXT index, so they get no `remember` tool and no recall.

## Staff ownership and delivery

Every handoff, triage and request for a person creates or reopens the episode ticket of the sender and holds it for staff, so AI stops for that episode. The fixed acknowledgement in the sender's language names the ticket, for example "Thank you for letting us know. A person from our team will follow up with you. Your ticket number is TKT-00042." Delivery accepts only this exact text with the run's own ticket number.

Take over, Start work, an explicit claim, and the first manual outbound message stop AI for that episode. The ownership transaction sets `ai_disabled`, advances its generation, and invalidates pending approvals. Assignment alone does not stop AI. All continuations, writes, flow steps, sends, and recovery attempts check ownership. Other business episodes for the same contact remain independent.

Close ticket and Resolved retain the episode scope and human hold. Only the explicit Close and release action clears that scope. Closing a ticket does not resume AI. Resume AI advances the generation and permits fresh work. It does not replay old actions. Close and release ends the episode. A closed ticket that retains its human hold reopens when another message arrives. Existing contact-wide pauses remain conservative holds.

Manual replies from the conversation and business composer hold the current episode in the same transaction as their delivery journal. An unresolved triage claim also fences queued business-choice prompts. Model continuations recheck current ownership after image observation and between tool turns. Core prevents new automatic dispatch after takeover. A delivery already accepted by Hub or the provider can still arrive. The ticket retains its outstanding delivery evidence. Recovery can obtain its receipt without sending it again. Core does not claim that takeover retracts accepted messages.

The ticket view loads the episode transcript from message links, beyond the selected-evidence table's 50-message limit. Chat and email delivery journals preserve their originating episode for outbound projection, including delayed receipts. The delivery view includes flow replies and lifecycle notices, including Suppressed notices, through permission-checked journal projections. Socket.IO refreshes revalidate the loaded transcript and history window rather than replacing it with the first page. Transcript and action APIs check company, business, message, and field access. Editor and ticket updates use Socket.IO notifications and permission-checked reads. They do not poll.

## Document lifecycle events

Relay Business Event Rule remains the separate mechanism for document lifecycle notifications. It maps a source event, recipient business, channel, execution user, approved template, and ordered parameters. An ambiguous or missing contact prevents delivery. Quantity summaries and zero-valued parameters are retained.

The document hook records an immutable delivery intent in the business transaction. Queue work starts after commit. Recovery retains intents through queue outages. Before delivery, Core checks source and rule versions, permissions, business links, and template approval. During human ownership, it retains the notice with Suppressed status and stops automatic conversation delivery. Resume AI does not replay suppressed notices.

## Local acceptance

The owner-requirement changes are source-only until the orchestrator migrates the development site. New metadata: `Relay AI Playbook` (standing instructions); `Relay AI Skill` changes labels/help only. No custom fields or fixtures are added. Local unit tests cover gated APIs, default seeding/fallback, prompt separation, report boundaries, script checks, Unicode phones and voice transcripts. Provider and send boundaries are mocked. These tests and the frontend build do not establish site activation or process reload.


`tests/integration_ai_events_site.py` exercises signed ingress, duplicate callbacks, concurrent projection, enrollment, HTTP isolation, declared searches, draft chains, takeover, and delivery races. It runs the matching, search, action, takeover, and delivery suites in fresh processes. `tests/integration_ai_permissions_site.py` probes real query and document permissions with populated company and party fixtures, then checks preview HTTP status, response shape, and denial. Its permission-layer probes supply a test search authorization callback; the event suite tests the real search journal and confirmation path.

`tests/automation_queue_site.py` exercises the actual drain and background jobs in an isolated RQ queue. See [automation-queue.md](automation-queue.md) for load and recovery evidence. These tests use `relay.test`, import this worktree first, block external delivery, and delete their inserted fixtures. Local HTTP tests use the Frappe WSGI application. They do not establish that existing web or worker processes have loaded this checkout. See the activation record in [automation-queue.md](automation-queue.md) for remaining checks.

`tests/integration_ai_knowledge_site.py` ingests Text, PDF event, and Project DocType sources on `relay.test` and checks Tamil, Malayalam, Hindi and English queries, the LIKE fallback, base and company scope, the Customer-only event audience, business isolation, row hash skip, filter exit, deletion and approval. `tests/integration_ai_knowledge_http.py` checks the source approval HTTP deny case.

The fake-model harness (`relay_core.ai.sim.run.main`, suite `core`, tier `fake`) has knowledge, memory and loop scenarios on the `Sim knowledge` skill: a page 3 answer, Tamil and Malayalam queries, a staff-only knowledge base, a shared chunk that names another customer, memory recall after delivery, a saved injection that cannot widen a read, and the tool call cap. The fake model can repeat its knowledge results and recalled facts (`echo`) and can keep calling tools after the cap (`fault: tool_loop`). The seed allows the `API Key` auth type on the test site, because the fake tier is a loopback server with a placeholder key. AI write actions stay off on the test site; the payment draft scenarios turn them on for their own trial with the `write_actions` step.
