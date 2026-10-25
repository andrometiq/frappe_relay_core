# Relay AI events and business events

## Configure an event

Each Relay AI Skill is one event. The owner writes its Target, Memory and rules, and Reply style in plain text on the **AI & skills** page. Several enabled events can use one channel and business type. The saved Reply style is bounded to 2000 characters and included with the trusted owner instructions in both preview and live model prompts. Select a model, execution user, handoff owner, and business type. Set one company and an eligible triage owner on the channel. Relay Settings supplies a backup owner. If no eligible owner is available, Core keeps a recoverable ticket intent and stops AI work.

Relay uses the shared AI Model, AI Provider Account, and bounded agent adapter from `frappe_tools`. The existing site automation gate controls inbound work. An event can run in Shadow or Automatic mode. Shadow creates the episode ticket and records proposals. It does not send automatic replies or create business drafts.

The saved-event test checks the authenticated sender and shows the selected event, identity scope, proposed search, and proposed actions. It can call the model and consume budget. It creates no operational run, ticket, approval, business document, or outbound message. Test a saved draft before activation. This preview does not replace a local end-to-end test.

## Select and record an episode

The callback authenticates and stores the source. The automation drain creates one run per incoming message. Core creates or reuses an assigned episode ticket before event tools run. The message stores its ticket link. A replay retains that link, including after closure.

An active flow or confirmed search continues through the same admission path. Otherwise Core matches enabled event targets within the resolved business scope. An exact configured trigger can select an event without a classifier. Classifier selection requires a score of at least 0.85 and a lead of at least 0.15. Invalid output, a timeout, ambiguity, or no match causes company triage. Core does not select the first event as a fallback. A request for a person bypasses the model.

Unresolved senders and business choices also receive company triage tickets from the stored Hub event. These tickets expose a sanitized summary. Enrollment can attach the projected message to that ticket. A company or active-episode conflict keeps the source in triage.

## SEARCH and EXECUTE

The model has two tools: SEARCH and EXECUTE. SEARCH uses a declared `get_doc` or `get_list` reference. Each reference specifies readable fields, a direct business scope, an identity anchor, provider identity fields, and a company field. SQL, reports, arbitrary methods, and URL tools are unavailable.

The authenticated sender identity unlocks only that person's records. Text entered in a message cannot establish identity. Reads require private transport evidence and a verified endpoint. A linked Contact user is authoritative. A disabled or denied linked user cannot fall back to the event execution user. The configured execution user applies only when no user is linked.

Each read applies user, company, business, sender, document, and field permissions. Fixed filters apply before pagination. Model filters can only narrow them. Dynamic party links also fix the party type. A document name must pass the same filtered query before loading. Core checks the read evidence again before delivery and recovery. Empty or inaccessible results require staff review.

Core records a search plan and sends its statement through the message journal before reading business data. The plan includes purpose, reference, fields, and filters. Ledger searches always require confirmation of the exact date range. A changed plan requires a new declaration. An uncertain announcement cannot authorize SEARCH.

EXECUTE follows the event's declared steps in order. The shared Relay Flow Action journal stores typed inputs, scope, versions, status, and results. The registered actions are `create_draft` and `reply`. The current draft target is Payment Entry. The event must allow that target and its typed fields. Core supplies company and party from the authenticated scope, inserts through normal document validation, and requires `docstatus = 0`. It never submits a document. The ticket action history links each draft so staff can open, check, and submit it. A Ticket only event creates the ticket without model execution, replies, or drafts.

Each action uses a stable command key and input hash. A changed input under the same key fails. Local writes and their journal results share a transaction. Replies use the existing durable message journal, with Core supplying the destination. An uncertain reply blocks later steps until its receipt is resolved. A retry cannot create a second draft or bypass changed permissions. Bounded image input requires a vision-capable model and attachment access checks.

## Staff ownership and delivery

Take over, Start work, an explicit claim, and the first manual outbound message stop AI for that episode. The ownership transaction sets `ai_disabled`, advances its generation, and invalidates pending approvals. Assignment alone does not stop AI. All continuations, writes, flow steps, sends, and recovery attempts check ownership. Other business episodes for the same contact remain independent.

Close ticket and Resolved retain the episode scope and human hold. Only the explicit Close and release action clears that scope. Closing a ticket does not resume AI. Resume AI advances the generation and permits fresh work. It does not replay old actions. Close and release ends the episode. A closed ticket that retains its human hold reopens when another message arrives. Existing contact-wide pauses remain conservative holds.

Manual replies from the conversation and business composer hold the current episode in the same transaction as their delivery journal. An unresolved triage claim also fences queued business-choice prompts. Model continuations recheck current ownership after image observation and between tool turns. Core prevents new automatic dispatch after takeover. A delivery already accepted by Hub or the provider can still arrive. The ticket retains its outstanding delivery evidence. Recovery can obtain its receipt without sending it again. Core does not claim that takeover retracts accepted messages.

The ticket view loads the episode transcript from message links, beyond the selected-evidence table's 50-message limit. Chat and email delivery journals preserve their originating episode for outbound projection, including delayed receipts. The delivery view includes flow replies and lifecycle notices, including Suppressed notices, through permission-checked journal projections. Socket.IO refreshes revalidate the loaded transcript and history window rather than replacing it with the first page. Transcript and action APIs check company, business, message, and field access. Editor and ticket updates use Socket.IO notifications and permission-checked reads. They do not poll.

## Document lifecycle events

Relay Business Event Rule remains the separate mechanism for document lifecycle notifications. It maps a source event, recipient business, channel, execution user, approved template, and ordered parameters. An ambiguous or missing contact prevents delivery. Quantity summaries and zero-valued parameters are retained.

The document hook records an immutable delivery intent in the business transaction. Queue work starts after commit. Recovery retains intents through queue outages. Before delivery, Core checks source and rule versions, permissions, business links, and template approval. During human ownership, it retains the notice with Suppressed status and stops automatic conversation delivery. Resume AI does not replay suppressed notices.

## Local acceptance

`tests/integration_ai_events_site.py` exercises signed ingress, duplicate callbacks, concurrent projection, enrollment, HTTP isolation, declared searches, draft chains, takeover, and delivery races. It runs the matching, search, action, takeover, and delivery suites in fresh processes. `tests/integration_ai_permissions_site.py` probes real query and document permissions with populated company and party fixtures, then checks preview HTTP status, response shape, and denial. Its permission-layer probes supply a test search authorization callback; the event suite tests the real search journal and confirmation path.

`tests/automation_queue_site.py` exercises the actual drain and background jobs in an isolated RQ queue. See [automation-queue.md](automation-queue.md) for load and recovery evidence. These tests use `yrp.site`, import this worktree first, block external delivery, and delete their inserted fixtures. Local HTTP tests use the Frappe WSGI application. They do not establish that existing web or worker processes have loaded this checkout. See the activation record in [automation-queue.md](automation-queue.md) for remaining checks.
