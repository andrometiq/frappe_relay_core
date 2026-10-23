# Relay focused product contract

## Product boundary

Relay is a WhatsApp workspace for a configured Frappe business DocType. The
business document is the conversation boundary. A Contact linked to that
document is a recipient inside the conversation; it is not a separate business
conversation. One business may have many Contacts and each Contact may have
more than one verified WhatsApp identity.

The focused product contains five operator surfaces:

1. Business inbox and one-to-one WhatsApp chat.
2. AI summary of the selected business conversation.
3. WhatsApp canned messages.
4. Command flow builder and flow runs.
5. Meta WhatsApp template management.

Telegram, email, calls, groups, cases, topics, tickets and general reports are
outside this product boundary. Their historical implementation may remain in
the repository for compatibility, but the focused UI and business-chat APIs do
not expose or invoke them.

## Business conversation

The stable identity is `(business_doctype, business_name)`. Every newly created
message stores that pair. Legacy messages without it may appear only when the
linked Contact resolves to exactly one configured business document. Shared or
ambiguous legacy messages remain hidden until explicitly associated.

Opening a business loads one bounded recent WhatsApp page. Scrolling upward
loads older pages and preserves the visible anchor. Scrolling downward loads
newer pages when the user opened at a saved read position. Socket.IO announces
new messages, delivery/read changes and flow results; APIs are used for initial
pages, cursor pages, search, sends and one bounded reconnect catch-up. There is
no periodic chat/status polling.

The composer requires an explicit recipient. Replying to a message selects its
Contact endpoint. Starting without history first selects a linked Contact and
then one of its verified WhatsApp endpoints. Drafts are isolated by business,
channel and recipient. A closed customer-service window offers an approved
template rather than attempting free-form text.

## Identity and Meta

Frappe Contact and its Dynamic Link remain the source of truth for business
ownership. Provider identifiers are endpoint records. A phone number must not
be used as the permanent business-record key: WhatsApp usernames introduce a
Business Scoped User ID for users who adopt them, and phone visibility can be
limited. Relay therefore keeps provider identity history under a Contact and
can add contact-book synchronization only through a documented, account-scoped
Meta capability.

Template management uses the account's WABA/PMA management scope through Hub:
list, create, edit, delete and approval/quality status. Template mutations are
explicit manager actions and are never auto-published by AI. The AI/MCP surface
may prepare a validated draft; a manager reviews and submits it.

## AI and flows

Summaries read only messages accessible through the selected business record
and return overview, action items and evidence-linked topics. They run in the
background and update through Socket.IO.

Canned messages are bounded, searchable WhatsApp replies. Agents see published
entries; managers create and publish them.

Flow commands are configurable. The builder supports typed inputs, validation,
conditions, replies, waits, handoff, end and registered business actions. AI
creates a disabled draft from the same installed action catalog and authoring
contract used by the manual builder. AI cannot invent Python methods, SQL,
DocTypes, reports or permissions.

Business actions are installed by Frappe apps through replay-safe hooks. A
`/ledger` flow, for example, collects ISO start and end dates, validates them,
then invokes a registered ledger action. That action rechecks permission on the
current business document and calls the installed report/service. Relay does
not duplicate ERPNext ORM or report logic. A custom operation belongs in the
site's custom app and becomes available only after that app registers a typed,
idempotent action.

## Access rules

Every directory, message page, search, summary source, send and business action
rechecks Frappe read permission on the business document. Group ownership can
narrow responsibility; it never grants document access. A user who loses
permission must stop receiving data on the next event and the visible protected
state must be cleared.

