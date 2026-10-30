# Relay product UI/UX redesign

Current access: [business type assignments](business-access.md). Team controls and group claims are hidden; team-related descriptions below refer to retained legacy implementation.


Status: design for review. No implementation is included in this document.

This specification covers the complete focused WhatsApp release across Relay Core and Relay Hub. The detailed inbox behavior is defined in [business-inbox-ui-ux.md](business-inbox-ui-ux.md).

## Product boundary

| Surface | Primary user | Responsibility |
|---|---|---|
| Relay Core | Sales, support, and business operators | Work with business records, contacts, conversations, campaigns, canned replies, flows, templates, and summaries |
| Frappe Desk | System Manager | Configure business DocTypes, grouping fields, roles, AI providers, automation policies, and the Core-to-Hub connection |
| Relay Hub | Platform and messaging administrators | Manage tenant accounts, WhatsApp provider channels, transport health, delivery queues, callbacks, API access, sessions, and audit evidence |

Core never exposes transport secrets. Hub never becomes a second CRM or business inbox.

## Release scope

Visible Core navigation:

- Business inbox
- Bulk messages
- Canned replies
- Flows
- Templates

Visible Hub navigation:

- Overview
- Accounts
- WhatsApp channels
- Deliveries
- Access
- Audit

Hidden from this release:

- Calls
- WhatsApp groups
- Telegram
- Email
- generic reports pages
- developer configuration inside operator screens

## Shared design system

Relay uses PrimeVue in unstyled mode for component behavior and a Relay-owned design layer for its Frappe-compatible visual vocabulary. It inherits the active Frappe font, density, semantic colors, focus treatment, and light/dark theme tokens.

### Visual rules

- Use the Relay-owned `TextInput`, `FormControl`, `Button`, `Badge`, `Avatar`, `Dropdown`, `Dialog`, and `ErrorMessage` wrappers built on PrimeVue unstyled primitives.
- Use Lucide outline icons with one stroke weight. Do not use emoji as interface icons.
- Use borders and surface contrast to establish structure. Reserve shadows for drawers, menus, and floating controls.
- Use 4 px increments. The principal spacing steps are 8, 12, 16, 24, and 32 px.
- Use 6 px control radii and 8 px overlay radii. Avoid turning every section into a rounded card.
- Use normal sentence case. Do not add decorative labels, repeated channel descriptions, or implementation terms.
- Use semantic tokens rather than fixed colors. Design and inspect light and dark themes independently.
- Reserve WhatsApp green for provider identity and healthy channel state. It is not the application accent.

### Motion rules

| Interaction | Motion |
|---|---|
| Selected row or pressed control | 80–120 ms surface/color response |
| List-to-detail transition | 160–180 ms spatial transition |
| Drawer or inspector | 160–200 ms |
| New real-time item | 120–160 ms opacity and short positional settle |
| Exit | About two-thirds of the related entry duration |

Animations never delay an operation. Reduced-motion users receive the final state immediately.

### Copy rules

- A label names one thing or action.
- A button describes its result: **Publish flow**, **Submit to Meta**, **Send campaign**.
- Successful feedback uses the same verb: **Flow published**, **Template submitted**.
- Empty states appear only when data is genuinely absent. They do not explain obvious navigation.
- Errors state what failed, why when known, and what the user can do next.
- Technical identifiers remain in details panels, logs, and copy actions rather than headings.

## Core application shell

Core follows the current Frappe CRM/Helpdesk shell.

```text
┌──────────────────────┬─────────────────────────────────────────────────┐
│ User                  │ Business inbox                                  │
│ Search                ├─────────────────────────────────────────────────┤
│ Notifications         │                                                 │
│                       │                  page content                   │
│ Work                  │                                                 │
│   Business inbox      │                                                 │
│   Bulk messages       │                                                 │
│                       │                                                 │
│ Automate              │                                                 │
│   Canned replies      │                                                 │
│   Flows               │                                                 │
│   Templates           │                                                 │
│                       │                                                 │
│ Frappe Desk           │                                                 │
│ Collapse              │                                                 │
└──────────────────────┴─────────────────────────────────────────────────┘
```

- Desktop sidebar uses the Frappe `Sidebar` component and persists collapsed state.
- In compact mode it is a rail. Hover or keyboard focus may temporarily expand it over content; explicit Collapse/Expand persists the preference.
- Mobile navigation is a drawer.
- The user menu is at the top, following CRM and Helpdesk.
- Search and notifications are predictable global actions.
- Theme selection belongs in the user menu.
- Normal Socket.IO health is silent. A reconnecting or degraded state appears as one nonblocking strip below the page header.
- Page headers contain the title and page-level actions. They do not repeat `Relay / Page title` when the sidebar already establishes the app.

## Core screen map

```text
Business inbox
├── Business browser
└── Business conversation
    ├── Contact filters
    ├── Timeline
    ├── AI summary drawer
    ├── Message search
    └── Composer

Bulk messages
├── Campaign list
├── New campaign
│   ├── Audience
│   ├── Message
│   ├── Schedule
│   └── Review
└── Campaign run

Canned replies
├── Reply list
└── Reply editor

Flows
├── Flow list
├── Flow builder
├── Test run
└── Version history

Templates
├── Template list
├── Template editor
├── Language variants
└── Meta review history
```

## Business inbox

The inbox uses the complete interaction specification in [business-inbox-ui-ux.md](business-inbox-ui-ux.md). Its defining behavior is:

- the unselected state is a full-width business browser, without an empty conversation canvas;
- selecting a business changes the route and transforms the browser into a list pane beside the conversation;
- a business remains the stable entity while linked contacts become filters and explicit recipients;
- list search is debounced and server-backed;
- businesses and messages load continuously without pagination controls;
- Socket.IO supplies new messages, delivery changes, read cursors, typing, permissions, and summary completion;
- browser back, reload, and contact switching restore position and state.

## Bulk messages

### Campaign list

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ Bulk messages                                      [New bulk message]   │
├─────────────────────────────────────────────────────────────────────────┤
│ [Search campaigns…]  [Status ▾]  [Owner ▾]  [Date ▾]                   │
├─────────────────────────────────────────────────────────────────────────┤
│ Name             Audience          Status       Progress       Started  │
│ Payment reminder Customer Group A  Sending      12,420/18,000  10:30    │
│ Festival notice  Territory South   Scheduled    0/8,450        Tomorrow │
│ Ledger follow-up Saved audience    Completed    2,714/2,714    Yesterday│
└─────────────────────────────────────────────────────────────────────────┘
```

- Search runs while typing.
- Filters update the list without a submit button.
- Rows use a Frappe list/table at desktop and stacked summary rows on mobile.
- Status, progress, and counts update in batches through Socket.IO without moving row geometry.
- Selecting a row opens the run route. It does not open a modal.

### New campaign

The flow uses four persistent steps: **Audience**, **Message**, **Schedule**, and **Review**. Users may go backward without losing data.

#### Audience

- Choose one configured business DocType.
- Build filters using Frappe field metadata and server-backed link or multiselect controls.
- The grouping field is available as a first-class filter.
- Show the estimated eligible count and a small server-sampled preview.
- Expose exclusions: missing WhatsApp number, opt-out, duplicate number, permission restriction, and invalid endpoint.
- Never send millions of records to the browser. The server owns the saved audience query.

#### Message

- Choose an approved Meta template.
- Map every template parameter to a business/contact field, a fixed value, or an allowed expression.
- Show a realistic WhatsApp preview using one sample recipient.
- Allow switching the preview recipient without changing the saved audience.
- Validate template language, required parameters, header media, and number formatting inline.

#### Schedule

- Send now or select a date, time, and timezone.
- Show the account throughput limit and estimated duration.
- Advanced rate and retry controls use progressive disclosure and require management permission.

#### Review

- Summarize audience, exclusions, template, language, parameter mapping, schedule, and estimated duration.
- Invalid sections link back to the exact field and keep inline errors.
- **Send campaign** is the only primary action.

### Campaign run

- Header: campaign name, owner, state, created time, and allowed Pause/Resume/Cancel actions.
- Progress: accepted, queued, sending, sent, delivered, read, failed, and excluded counts.
- Failures group by reason before individual recipients.
- Recipient results use cursor loading and server search.
- CSV export is a prepared background result; completion arrives through Socket.IO.
- A run never downloads or renders the entire recipient set in the browser.

## Canned replies

```text
┌──────────────────────────────┬──────────────────────────────────────────┐
│ Canned replies     [New]     │ Payment received                         │
│ [Search…]                    │ Personal  •  /received                   │
│ [All] [Mine] [Team] [Global] ├──────────────────────────────────────────┤
│ Payment received             │ Title                                    │
│ /received · Personal         │ Shortcut                                 │
│                              │ Message body                             │
│ Ledger request               │ Variables                                │
│ /ledger · Team               │ Optional business action                 │
│                              │                                          │
│ ...                          │                         [Save changes]   │
└──────────────────────────────┴──────────────────────────────────────────┘
```

- Initial state is a full-width list. Selecting a reply opens the list/detail layout.
- Search is debounced and server-backed.
- Scope filters are **All**, **Mine**, **Team**, and **Global**.
- The editor validates title, unique shortcut, message length, variables, and scope inline.
- Variables are inserted from an allowed-field picker rather than typed as undocumented syntax.
- The optional business action uses the registered action catalogue and schema-generated fields.
- The action runs only after an explicit operator action in the conversation. Selecting a canned reply never silently changes a business record.
- Version and audit information live in a secondary details panel.
- “Draft with AI” may prepare editable text. It never publishes or attaches an action automatically.

## Flow builder

### Flow list

- Full-width searchable list with Status, Trigger, Business DocType, Updated, and Owner.
- Filters update while selected.
- **New flow** starts with Blank, From template, or Describe with AI.
- Rows route to the builder and preserve list state on Back.

### Builder layout

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ Ledger request       Draft   [Test] [Version history] [Publish flow]   │
├───────────────┬─────────────────────────────────────┬───────────────────┤
│ Nodes         │                                     │ Ask for date      │
│ Trigger       │   [Command: /ledger]                │ Label             │
│ Ask           │           │                         │ Prompt            │
│ Validate      │   [Ask for start date]              │ Validation        │
│ Branch        │           │                         │ Invalid response  │
│ Get record    │   [Ask for end date]                │ Save as variable  │
│ Run report    │           │                         │                   │
│ Send          │   [Run General Ledger]              │                   │
│ Handoff       │           │                         │                   │
│ End           │   [Send PDF]                        │                   │
├───────────────┴─────────────────────────────────────┴───────────────────┤
│ Problems: 2   Missing invalid-date response · Report needs company     │
└─────────────────────────────────────────────────────────────────────────┘
```

- Left: searchable node palette grouped as Trigger, Conversation, Business, Logic, and Finish.
- Center: pan/zoom canvas with keyboard-operable node selection and connection alternatives.
- Right: inspector for the selected node using ordinary Frappe fields.
- Bottom: collapsible validation panel with errors that focus the affected node and field.
- The URL includes the flow and selected node.
- Draft changes autosave with an explicit saved state. Publishing creates an immutable version.
- Unsaved, saving, saved, validation-error, published, and conflict states have distinct language.
- On mobile, users may inspect, test, enable, or disable a flow. Canvas authoring requires a tablet/desktop-sized workspace rather than presenting a broken miniature editor.

### AI flow creation

- **Describe with AI** opens a side panel, not an unstructured chat replacing the canvas.
- The AI produces a proposed graph and a written assumptions list.
- Every Frappe DocType, field, report, action, and permission is selected from server-provided metadata.
- Unsupported operations appear as unresolved nodes. AI cannot invent callable methods.
- The user reviews the diff before applying it to the draft.
- Publishing still requires deterministic validation and explicit user action.

## Meta templates

### Template list

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ Templates                         [Sync with Meta] [New template]        │
├─────────────────────────────────────────────────────────────────────────┤
│ [Search templates…] [Status ▾] [Category ▾] [Language ▾]               │
├─────────────────────────────────────────────────────────────────────────┤
│ Name                 Category       Languages   Meta status   Updated    │
│ payment_reminder     Utility        3           Approved      Today      │
│ festival_offer       Marketing      2           In review     Yesterday  │
│ account_otp          Authentication 1           Rejected      2 days ago │
└─────────────────────────────────────────────────────────────────────────┘
```

- Sync is an explicit background action with progress and a last-synced time.
- Status updates arrive live and retain their stable table slots.
- Rejected rows display the reason in the detail view, not as truncated table noise.

### Template editor

The editor is a full route with two columns: form and phone preview.

1. **Identity** — validated template name, category, default language.
2. **Content** — header type/content, body, footer, and buttons.
3. **Variables** — numbered variables with a required example for Meta review.
4. **Languages** — add, duplicate, translate, and remove variants.
5. **Review** — validation summary and Meta submission result.

Rules:

- Template names validate while typing: lowercase letters, digits, and underscores only.
- Category choices explain Utility, Marketing, and Authentication with short examples.
- Header inputs change with the selected type instead of displaying all possible fields.
- Body variable numbering is visual and consistent. Renumbering warns before changing existing mappings.
- Buttons use type-specific editors for quick reply, URL, phone, flow, and supported Meta actions.
- The phone preview updates as fields change and supports each language tab.
- Draft saves locally in Core. **Submit to Meta** is separate and explicit.
- Submitted versions become read-only while in review. Changes create a new editable version when Meta rules require it.
- Disable, archive, and delete use the provider's real supported semantics and explain the consequence.

## AI summary drawer

The summary is available from the business conversation header and opens beside the timeline.

- Summary
- unresolved requests
- commitments and due dates
- people involved
- source citations that focus the original message
- generated time and model/provider details under More details

Refresh is a background job. The previous summary stays readable, a compact progress state appears, and completion arrives through Socket.IO.

## Hub application shell

Hub is an operations console with higher density than Core. It uses the same restrained surface hierarchy, accessible controls, and light/dark support, but it does not imitate a chat application.

```text
┌──────────────────────┬─────────────────────────────────────────────────┐
│ Relay Hub             │ Overview                     Updated 8 sec ago  │
│                       ├─────────────────────────────────────────────────┤
│ Overview              │ Provider health  Queue depth  Error rate       │
│ Accounts              │                                                 │
│ WhatsApp channels     │ Throughput timeline                              │
│ Deliveries            │                                                 │
│ Access                │ Accounts needing attention                       │
│ Audit                 │                                                 │
│                       │ Recent delivery failures                         │
│ User                  │                                                 │
└──────────────────────┴─────────────────────────────────────────────────┘
```

- Desktop sidebar may collapse persistently; mobile uses a drawer.
- Authentication, theme, and user actions use one account menu.
- Login/logout events never appear in Overview. They belong to Audit.
- Overview data is labelled live only while its stream is current. A stale timestamp replaces the live state after disconnection.

## Hub Overview

Overview answers four operational questions:

1. Are providers reachable?
2. Are queues growing?
3. Is delivery throughput within expected limits?
4. Which accounts require action?

The page contains:

- Hub readiness and version
- WhatsApp provider health by account
- pending/sending/callback/status-batch queue depth
- current and recent throughput
- delivery and callback error rate
- accounts or channels with failed authentication, webhook, or token validation
- recent grouped failures with a route to filtered Deliveries

Metrics are compact and use tables or small charts only when time-series comparison helps. They do not use oversized marketing cards.

## Hub Accounts

- Searchable, cursor-loaded account list.
- Columns: account, mapped site, state, WhatsApp channels, pending deliveries, last callback, and updated time.
- Account detail tabs: Overview, Channels, Delivery policy, and Access grants.
- The backend derives account ID, username, role, and enabled state. The browser never posts authoritative identity or role values supplied by the user.
- Enable/disable actions are explicit, permission-controlled, and audited.
- Site URL validation occurs inline and explains host mismatch without exposing secrets.

## Hub WhatsApp channels

- Channel list groups entries by account.
- Detail shows WhatsApp Business Account, phone-number identity, verification state, webhook state, template-sync state, throughput limit, and last provider check.
- Credential fields accept a new secret but never return the stored value.
- Token state is Active, Invalid, Revoked, or Provider unavailable. Hub does not invent an expiry date when Meta supplies none.
- The webhook section presents the exact public callback URL, verify-token state, subscribed fields, last callback, and a copy action.
- **Verify connection** performs a backend check and reports each stage.
- Raw provider responses are available only to authorized administrators in a redacted detail panel.

## Hub Deliveries

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ Deliveries                                                              │
├─────────────────────────────────────────────────────────────────────────┤
│ [Search ID…] [Account ▾] [State ▾] [Provider ▾] [Time range ▾]         │
├─────────────────────────────────────────────────────────────────────────┤
│ Message ID       Account       State       Attempts  Updated       ⋯    │
│ ...                                                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

- Filters update the cursor query directly.
- The detail drawer separates Intent, Provider attempt, Callback evidence, and Core status delivery.
- Provider/raw payloads use a structured tree with redacted secrets and an optional raw JSON tab.
- Retry is available only for retry-safe states and explains whether it reuses the existing idempotency key.
- Large status backlogs are shown as batches and chunks, including target site, item count, attempts, and next retry.
- Real-time updates patch visible rows or invalidate a bounded query. They do not trigger repeating full-list fetches.

## Hub Access

Access is a primary area with tabs:

- **Users** — identity, role, enabled state, last sign-in
- **Roles and grants** — account and operation scopes
- **API tokens** — label, scopes, created, last used, state; secret shown once on creation
- **Sessions** — device/client, created, last active, and revoke action

Sessions use secure server-managed cookies or refresh behavior. Normal use does not repeatedly force users back to login. The UI never lets a browser claim a different user ID, role, or enabled state.

## Hub Audit

- Searchable timeline of authentication, access, account, channel, token, and administrative events.
- Login and logout events live here.
- Filters: event type, actor, account, result, and time range.
- Each event shows actor, server-derived identity, action, target, result, IP/client information when policy permits, and correlation ID.
- Payload inspection opens a redacted structured/raw panel.
- Audit rows use cursor loading and prepared export for large ranges.

## Shared list and selector behavior

- All text searches debounce at 250–300 ms.
- A changed query cancels or invalidates older requests.
- Link and multiselect controls query the server using text, active filters, permission context, and a stable cursor.
- The browser never loads all options merely to filter them locally.
- Lists load 20–50 rows per request and virtualize beyond 50 rendered records.
- List state is represented in the URL when it must be shareable and in session storage when it is personal presentation state.
- Back restores the prior query, filters, selection, and scroll anchor.
- No general list has Next, Previous, Search, or Refresh buttons. Explicit refresh exists only for provider synchronization or a failed request.

## Responsive rules

| Width | Core | Hub |
|---|---|---|
| ≥1280 px | Sidebar, list/detail, optional drawer | Sidebar, dense tables, detail drawer |
| 768–1279 px | Rail, narrower list/detail, overlay drawer | Rail, reduced columns, overlay detail |
| <768 px | One routed pane at a time | Summary rows replace wide tables; detail is a route |

Every screen is verified at 375, 768, 1024, and 1440 px, in light and dark themes, with 200% browser zoom. There is no document-level horizontal scrolling. Complex canvases may pan internally, but their toolbars and inspectors remain accessible without widening the page.

## Accessibility and feedback

- All actions use semantic buttons or links.
- Icon-only controls have accessible names and tooltips.
- Filter chips expose selected state.
- Focus order follows visual order, and route changes focus the main heading.
- Primary mobile targets are at least 44 × 44 px.
- Normal text maintains at least 4.5:1 contrast in both themes.
- Color never carries status alone; every status has text or an accessible label.
- One contextual live region announces meaningful async changes. Individual counters do not compete as live regions.
- Validation appears beside each field. A failed multi-field submit also focuses an error summary with links.
- Skeletons reserve the final geometry for waits longer than a brief response.
- Toasts announce completed background actions but never replace persistent failure details.

## Design critique and rejected patterns

The following patterns were rejected during review:

- an external SaaS font and palette, because Relay must feel native to Frappe;
- a narrow business list beside a blank panel, because it wastes the initial inbox and requires instructional copy;
- generic cards for every metric and form section, because they weaken hierarchy;
- top-of-chat Cases, Topics, and Deliveries tabs, because they interrupt one-to-one communication;
- a channel selector in the composer, because this release is WhatsApp-only;
- select fields containing every business record or contact, because the dataset can contain millions of rows;
- periodic API polling, because messaging and job progress require Socket.IO events with bounded catch-up requests;
- front-end configuration of user identities, roles, credentials, or transport internals;
- displaying login/logout events in Hub Overview;
- hover-only actions, text-only icon substitutes, decorative animations, and filler descriptions.

## Design acceptance gates

Implementation should not be presented for product review until all gates pass:

1. Every visible page matches this screen map and uses the shared shell.
2. Inbox behavior passes the acceptance list in [business-inbox-ui-ux.md](business-inbox-ui-ux.md).
3. Bulk audience and all large link fields are server-backed and bounded.
4. Canned replies work from management list through composer insertion and explicit action execution.
5. Flow authoring, deterministic validation, test, versioning, and publish states are visible and coherent.
6. Template creation covers category, language, header, body, footer, buttons, variables, previews, validation, Meta submission, and rejection details.
7. Hub separates health, accounts, channels, deliveries, access, and audit.
8. Core and Hub use Socket.IO for live updates without repeating full API calls.
9. Direct URLs, Back, reload, permissions, and state restoration work throughout.
10. The four responsive widths, 200% zoom, keyboard-only operation, reduced motion, and both themes pass visual review.

## References reviewed

- [Frappe CRM](https://github.com/frappe/crm)
- [Frappe Helpdesk](https://github.com/frappe/helpdesk)
- [PrimeVue](https://github.com/primefaces/primevue)
- [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill)
- [Anthropic frontend-design skill](https://github.com/anthropics/skills/tree/main/skills/frontend-design)
