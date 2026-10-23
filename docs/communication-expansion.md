# Relay communication expansion

Implementation contract from Telegram message 11593. This is planned scope, not a statement that these services are live.

## Ownership

Hub owns provider credentials, channel adapters, delivery queues, webhook verification, provider events and account-scoped MCP services. Core owns business-record permissions, conversations, ticketing, canned replies, AI policies and team workflows. AI services live in Core, without I2A. Core credentials never authorize another Hub account.

## Data and UI

A business record can link many existing Contacts, each with multiple channel endpoints. A Contact can link multiple business records. Do not duplicate a person's messages for each link; represent associations separately and enforce the selected business context before any report/action. Unknown endpoints remain uncategorized. Telegram IDs come from verified incoming updates, not guessed phone mappings.

Use sequential Relay-prefixed document names. Persist Relay Ticket with linked Relay Ticket Message child rows, category, brief, status, assignee and business reference. Each message link includes its conversation and exact message cursor. Opening a link fetches a bounded window around that message. Never preload a conversation to find it.

Expose a generic Calls interface with WhatsApp as the first provider. Do not imply Google Meet is implemented. Email conversations retain provider thread references, sender, recipients, CC/BCC and attachment metadata. Load attachment bytes only on preview/download, through permission-checked access. Sanitize email HTML and isolate active document content in viewers.

## Ticketing and automation

Manual ticket creation accepts one or multiple accessible messages. Automatic creation from queries/payment screenshots requires an enabled policy, stable event idempotency key, category and brief; a screenshot is evidence to review, not proof of payment. Ticket updates enqueue email or Telegram notifications only. No WhatsApp ticket-update notifications in this phase.

Canned replies have type, language, allowed channels, enabled state and explicit AI-use permission. Policies separately allow ticket creation, reply selection and approved report actions. AI output cannot grant itself a permission. If no suitable approved response exists, use the configured acknowledgement and hand off. Even acknowledgements obey provider messaging rules.

Report execution resolves identity and business record on the server, enforces action/report allowlists and date/size limits, and fixes the supplier/customer filter server-side. A prompt is never the security boundary. Unresolved or ambiguous business identity requires handoff. Human guidance becomes a versioned draft workflow; only an authorized published workflow may execute automatically.

Provider adapters for OpenRouter, Gemini, OpenAI/Codex and Anthropic/Claude must declare actual capabilities (text, vision, transcription, structured actions), timeouts and usage limits. Do not assume a local CLI session is a production API credential. Model output is validated against the same Core action schemas and permissions as human/API requests. Preserve original language and audit actions without logging credentials.

## Bounded loading

Core `relay_core.api.contacts` now supplies a permission-filtered database subsequence search and keyset pages capped at 50. `contactPageSource` implements its browser contract with cancellation. Hub user/token search already executes in PostgreSQL. These searches are subsequence matches, not typo-tolerant indexed ranking. Leading-wildcard searches can scan many rows: bounded result size does not prove bounded database CPU. Benchmark representative data before choosing an indexed search strategy. No claim of million-record search performance yet.

The current Core preview still uses sample contacts and local adapters. Production wiring, business grouping, message projection, tickets, channel adapters and AI services remain to be integrated; do not disguise missing APIs by falling back to sample data.

## Acceptance gates

- Real Frappe permission tests: agents cannot read another agent's restricted messages, tickets, attachments or reports through UI, direct API or MCP.
- Database searches with large realistic datasets: query plans, p95/p99 latency, memory, concurrent requests, cancellation and forward/reverse cursors.
- Duplicate and out-of-order provider events: one message/ticket/notification, durable retry and no duplicate sends on ambiguous failure.
- Customer with several Contacts and channels; same Contact linked to supplier and customer; unknown endpoint categorization.
- Email CC/BCC round trip, threading and permission-checked attachment previews; Telegram receiving/replies; WhatsApp call lifecycle with real provider configuration.
- AI failure, invalid action, cross-business report request, unsupported language/audio and human handoff. Published guidance cannot broaden permissions.
- Mobile layout, fixed-size page cache, virtual rows and lazy viewer loading under long browsing sessions.

## Local implementation checkpoint

Added source metadata/controllers for Relay Ticket and Relay Ticket Message, both with sequential names. Ticket services create, read and update status using normal Frappe permissions. Communication Users have owner-only ticket access; Communication Managers have team-wide ticket access. Ticket validation checks each message and its contact, rejects duplicates and caps links at 50. Read API rechecks referenced message access. Core MCP exposes the same three services. These DocTypes have not been migrated onto a site. Assignment-specific sharing, notifications, automatic ticket creation, UI navigation and idempotent AI actions are still outstanding. Do not enable AI ticket automation against the manual create method without durable event deduplication.

Validation: 39 Python tests run, 37 passed and 2 live integration tests skipped; 7 frontend tests passed. Frappe services were exercised with isolated mocks, not a live installed site.

## Frappe installation contract

Relay Core does not provide a login page or a second user/session system. Installed sites use Frappe authentication, API keys, roles, User Permissions and CSRF handling. The standalone preview is only a visual development fixture and must not be treated as a production Core login.

`Relay Contact Type` lets a System Manager configure which business DocTypes (Customer, Supplier, Employee or site-specific DocTypes) Relay may resolve through standard Frappe `Contact` Dynamic Links. Core refuses an unconfigured business DocType. Existing Contacts and their links remain the source of truth; Relay does not duplicate business records.
