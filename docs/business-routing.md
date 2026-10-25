# Business references and inbound routing

Relay stores business names as historical Data references. Relay history must not prevent a business document from being updated, cancelled, renamed, or deleted. Relay DocTypes are excluded from Frappe business delete checks. Cancel hooks extend the document's existing exemptions. Other business links still apply. Historical names do not follow a rename. Reads continue to require access to the referenced business.

`business_routing.resolve` selects the business for an incoming message. Authenticated reply context is scoped to the contact, channel, endpoint, and conversation. A single current contact link can resolve the business. Otherwise Core uses a validated sender choice or saved conversation selection. Manager enrollment uses the same resolver. The model cannot choose the company or business record.

Each projected message records its routing rule in provider context. Unresolved Hub events retain routing decisions for each message. A sender choice is validated before single-link fallback. Removing a choice cannot silently route its reply to a different business.

Relay Business Routing stores selection and prompt state. A lock on a Relay endpoint serializes routing. It does not lock the business record. Core checks the selection against current contact links and reads committed routing state after it acquires the lock. A selection can route later messages in the same batch without changing earlier messages on replay.

For private WhatsApp conversations with two to ten businesses and fresh timestamp evidence, Core can prepare one list prompt. Local event arrival time also bounds the reply window. Choices contain only the contact's enabled business links and opaque selection IDs. Forged, revoked, consumed, or foreign-conversation choices cannot select a business. Groups, unsupported prompt channels, large lists, and expired or missing window evidence remain in triage.

The prompt uses Relay Message Action with a stable request key. Its journal remains restricted to managers because no business is selected yet. Existing delivery lookup, callbacks, and recovery apply. Core does not blindly resend an uncertain attempt. Sender choices retain their interactive type and cannot act as text replies to an explicit flow.

## Company triage and episodes

Configure one company and an eligible triage owner for each channel. Relay Settings can supply a backup owner. An unresolved sender or ambiguous business receives a sanitized company triage ticket from the stored Hub event and provider message key, even when no Relay Message exists. If no eligible owner is available, Core retains the source for recovery.

Enrollment checks company and business access before it creates an endpoint or projects a message. A successful enrollment attaches the message to the original ticket. An active-episode collision or changed company keeps the source in triage. Cross-company staff and guests cannot read the ticket or raw source, or bind its sender.

A resolved message enters the existing automation drain. The shared episode service assigns its ticket before event tools run. An unmatched message remains on that ticket for staff review, with its business reference retained. Replays use the original source link. Event changes do not create a second episode. Coordination uses Relay source, routing, and ticket records.

Staff takeover belongs to the episode. It stops AI for that conversation and business without pausing unrelated episodes for the same contact. A manual message uses the same ownership service. Closing alone does not resume AI. Socket.IO notifications trigger permission-checked UI reads.

## Local verification

`tests/integration_ai_events_site.py` uses signed local callbacks and independent database connections to test duplicate projection, unknown senders, ambiguous Customer/Supplier links, owner failure and recovery, enrollment replay, and company conflicts. HTTP checks cover response shape, list filtering, guest denial, cross-company denial, and refusal of internal helper methods. The fixtures contain amount 1250 and quantity 25. All inserted records are deleted after the test.

These tests intercept external transport. They do not establish provider delivery for the WhatsApp interactive-list operation. Verify that Hub accepts `whatsapp.execute` with `operation=messages.interactive` before enabling that prompt on a live channel. The current activation evidence and remaining environment checks are in [automation-queue.md](automation-queue.md).
