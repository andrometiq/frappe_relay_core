# Relay Core WhatsApp business inbox — UI/UX specification

Status: design for review. This document does not authorize implementation.

## Product job

Relay Core is a Frappe-native workspace for an operator to manage WhatsApp communication around a business document. The business document is the primary entity. A business may have several linked contacts and phone numbers, while permissions and group ownership are inherited from the business document.

The first release is deliberately limited to:

- WhatsApp one-to-one conversations
- business records and their linked contacts
- grouping, assignment, and document permission enforcement
- AI summaries
- canned replies
- bulk messages
- Meta templates
- flow building and execution

Calls, WhatsApp groups, Telegram, and email stay hidden.

## Design direction

Relay should feel like CRM or Helpdesk inside Frappe. It uses PrimeVue in unstyled mode through Relay-owned components, semantic Frappe-compatible theme tokens, the existing Frappe typeface, and the normal Frappe spacing rhythm. It does not introduce an external font, a separate blue palette, decorative gradients, glass effects, or a dashboard made of cards.

The distinctive interaction is the transition from a business browser to a business conversation. The interface is otherwise quiet.

### Visual tokens

| Role | Decision |
|---|---|
| Typeface | Inherit the Frappe app font and type scale |
| Surfaces | `surface-base`, `surface-gray-1`, and `surface-gray-2` |
| Text | `ink-gray-9`, `ink-gray-7`, and `ink-gray-5` |
| Borders | `outline-gray-1` and `outline-gray-2` |
| Accent | Frappe's active/focus blue only |
| Status | Frappe semantic green, amber, red, and gray tokens |
| Spacing | 4, 8, 12, 16, 24, and 32 px |
| Radius | 6 px controls, 8 px menus/dialogs, restrained message bubbles |
| Shadow | Overlay and floating-action elevation only |
| Motion | 120–180 ms for state changes initiated by the user |

WhatsApp green may identify the configured channel once in settings. It is not repeated on every message or heading.

## Information architecture

The operator-facing navigation contains:

1. **Inbox** — business records and conversations
2. **Bulk messages** — recipient selection, template, scheduling, and delivery summary
3. **Canned replies** — reusable personal, team, and global replies
4. **Flows** — flow list and visual flow builder
5. **Templates** — Meta template catalogue and authoring

Channel credentials, webhook settings, AI-provider credentials, group-field configuration, and permission configuration remain in Frappe Desk. Calls, groups, Telegram, and email do not appear in this release.

## Inbox layout

### No business selected

The business browser uses the whole workspace. There is no empty chat canvas and no text telling the user to select a business. The page itself makes the next action apparent.

```text
┌──────┬──────────────────────────────────────────────────────────────────┐
│ rail │ Business inbox                                      filters     │
│      ├──────────────────────────────────────────────────────────────────┤
│      │ [ Search businesses…                                      × ]   │
│      │ [My group ▾]  [Unread]  [Unassigned]                            │
│      ├──────────────────────────────────────────────────────────────────┤
│      │ AMAN HOSIERY               2 contacts             10:42   3     │
│      │ G.M. Sales (MP)            “Please share the ledger…”            │
│      ├──────────────────────────────────────────────────────────────────┤
│      │ AARADHANA HOSIERY          1 contact              Yesterday      │
│      │ G.M. Sales (MP)            Image                                   │
│      ├──────────────────────────────────────────────────────────────────┤
│      │ ...continuous vertical list...                                  │
└──────┴──────────────────────────────────────────────────────────────────┘
```

The list is left aligned and scanable. It does not use cards. Search runs while typing. More rows load as the user approaches the bottom. The UI never displays Search, Next, More, or “Scroll for more” buttons.

### Business selected

Selecting a record animates the business browser into a fixed list pane and opens the conversation. The selected business is written to the URL.

```text
┌──────┬─────────────────────┬────────────────────────────────────────────┐
│ rail │ Search businesses…  │ AMAN HOSIERY                         ⋯     │
│      │ My group ▾          │ Customer · G.M. Sales (MP)                 │
│      ├─────────────────────┼────────────────────────────────────────────┤
│      │ AMAN HOSIERY     3  │ [All 3] [Anil · …4852 2] [Aman · …0626 1] │
│      │ latest preview      ├────────────────────────────────────────────┤
│      ├─────────────────────┤                    Today                   │
│      │ AARADHANA HOSIERY   │ Anil                                      │
│      │ latest preview      │ ┌──────────────────────────┐               │
│      ├─────────────────────┤ │ Please share the ledger. │               │
│      │ ...                 │ └──────────────────────────┘               │
│      │                     │                              ┌────────────┐│
│      │                     │                              │ Certainly.││
│      │                     │                              └────────────┘│
│      │                     ├────────────────────────────────────────────┤
│      │                     │ To: Anil · …4852            Canned replies│
│      │                     │ [Add]  Write a message…              [Send]│
└──────┴─────────────────────┴────────────────────────────────────────────┘
```

The list pane may be resized on desktop within a safe range and remembers its width. It is always a vertical scroller; horizontal scrolling is prohibited.

## Business and contact model

- A business row aggregates all WhatsApp activity for that business document.
- Opening a business initially shows an **All contacts** timeline.
- If the business has one linked WhatsApp contact, the contact strip is omitted and that contact is the composer recipient.
- With multiple contacts, the contact strip shows each person, masked number, unread count, and availability state.
- Selecting a contact filters the timeline and fixes the composer recipient.
- In **All contacts**, inbound bubbles display the sender. Replying to a bubble sets that sender as the recipient.
- The composer remembers the last explicitly used recipient per business. It must never silently choose a different recipient.
- A compact contact picker is part of the composer when a recipient still needs to be chosen. It is not a blocking dialog.
- Contact search is server-backed and debounced. It searches name, phone, email, and fields configured as “show in link fields.” It never loads the entire contact table into the browser.

## Business directory behavior

### Search and loading

- Fetch the first 30 accessible businesses.
- Debounce business search by 250–300 ms.
- Cancel or ignore stale search responses.
- Load the next cursor page within roughly 240 px of the list bottom.
- Virtualize the visible rows after the list passes 50 records.
- Preserve list height with row skeletons while fetching.
- Show a true empty state only when no accessible records match. Do not use an empty state merely because no business is selected.
- Keep search, group, unread, and assignment filters when the user opens a business and returns.

### Row content

Each business row contains only information that helps triage:

- business title
- configured grouping value
- last-message preview or message-type label
- last activity time
- aggregate unread count
- optional assignee avatar when assignment is relevant

Long values truncate inside the row. The text container has a shrinkable width, and no identifier can expand the pane.

## Conversation timeline

- Load a window around the operator's last-read message, rather than loading the newest messages unconditionally.
- Load older messages automatically near the top and newer messages near the bottom.
- Preserve the visible message anchor when older rows are prepended.
- Preserve the per-business, per-contact scroll position across contact switches and route changes.
- Mark messages read only after they remain visibly present while the tab is focused.
- Batch read acknowledgements.
- Display each operator's read marker once, below the furthest message they have read. Operators at the same cursor share one read-by bubble.
- If a real-time message arrives while the user is near the bottom, append it and keep the viewport pinned.
- If the user is reading older history, do not move the viewport. Show one floating “New messages” control with the unread count.
- Message actions appear on hover, focus, or long press and remain keyboard accessible.
- Supported content includes text, image, video, audio/voice, document, sticker, location, contact, interactive reply, template, reaction, and quoted reply.

## Composer

The composer is one compact surface, not a form containing every WhatsApp option.

- `Enter` sends; `Shift+Enter` inserts a new line.
- `+` opens a grouped attachment/action menu: media, document, camera where available, location, and contact.
- The canned-reply action opens searchable suggestions and supports slash commands.
- Template selection is available when the 24-hour service window requires it and as an explicit action.
- Reply context appears as a removable strip above the input.
- Upload progress appears inside the attachment chip.
- Sending immediately creates an optimistic message bubble.
- Delivery progresses through queued, sending, sent, delivered, read, or failed using Socket.IO events.
- Failed messages expose Retry and Details. Delivery uncertainty does not block the next message.
- Typing indicators are transient and never trigger page polling.

## AI summary

AI summary opens in a right-side panel, leaving the conversation visible. It contains:

- current business summary
- unresolved requests
- commitments and due dates
- recent sentiment or escalation signal when configured
- citations that jump to source messages
- generated time and a Refresh summary action

Summary generation is a background task. Progress and completion arrive through Socket.IO. The panel keeps the previous summary visible while refreshing.

## Grouping, assignment, and permissions

- The configured grouping field is a first-class inbox filter, such as Territory or Customer Group.
- The operator's assigned group opens by default.
- “My group,” “Unread,” and “Unassigned” are compact filter states, not separate pages.
- Claim and release actions live in the group menu or business action menu. They do not occupy every row.
- Business-document read permission controls visibility in search, directory results, direct URLs, summaries, and Socket.IO events.
- Business-document write/comment permission controls replying and actions.
- A direct URL to an inaccessible business returns a neutral access-denied screen without exposing its title, contacts, message preview, or counts.
- Frontend hiding is only presentation; every API and real-time subscription enforces the same permission server-side.

## Routing and state restoration

The route expresses the selected business and optional contact:

```text
/relay#/messages/{business-doctype}/{business-name}
/relay#/messages/{business-doctype}/{business-name}?contact={contact-name}
```

Browser back returns to the previous business or to the business browser. Returning to the browser restores search text, filters, list scroll position, and focused row. Reloading a business route restores the last-read message window and contact selection.

## Responsive behavior

| Width | Behavior |
|---|---|
| ≥1280 px | Collapsible Frappe sidebar, 320 px business pane, conversation, optional summary drawer |
| 768–1279 px | Collapsed Frappe rail, 288 px business pane, conversation; summary overlays from right |
| <768 px | Business browser is full screen; selection navigates to a full-screen conversation; Back restores the exact list position |

At all widths:

- no document-level or pane-level horizontal scrollbar
- no content beneath the navigation rail
- input height is at least 44 px on touch layouts
- primary touch targets are at least 44 × 44 px
- keyboard focus remains visible and unobscured
- light and dark themes are designed and tested independently
- reduced motion removes nonessential transitions

## Loading, empty, and failure states

| State | Presentation |
|---|---|
| Initial business load | Fixed-height row skeletons; search stays usable |
| Next business page | Two or three skeleton rows appended; no status sentence |
| No search matches | “No businesses match ‘…’” and a Clear search action |
| No accessible businesses | Explain that no accessible business records are available; no create action unless the user can create the DocType |
| Business has no contacts | Show business details and an “Add contact” action only when permitted |
| Contact has no WhatsApp number | Show the contact and a permission-aware “Add WhatsApp number” action |
| Conversation has no messages | Composer remains primary; template guidance appears only when required by Meta |
| Offline/socket reconnecting | One nonblocking status strip; queued drafts remain intact |
| Permission revoked live | Close the conversation, remove its row, and show a neutral access-change notice |

## Motion

Motion communicates structure:

- business browser to split view: 160–180 ms
- row selection/pressed feedback: 80–120 ms
- new real-time message: 120–160 ms opacity and small vertical settle
- side panel: 160–200 ms
- exiting states are faster than entering states

There are no decorative scroll reveals, bouncing icons, or continuous animations.

## Design review against the brief

The initial generic design-system result suggested an external SaaS font, a navy/blue palette, and a conventional narrow master-detail screen with instructional empty copy. Those choices were rejected because they would make Relay feel separate from Frappe and recreate the current empty-canvas problem.

The revised design is specific to Relay in three ways:

1. the unselected inbox is a full-width business browser that transforms into the conversation split view;
2. a business remains the stable entity while linked contacts become filters and explicit recipients;
3. read position, permissions, grouping, summaries, and real-time state are visible where operators make decisions, without exposing backend configuration in the chat.

## Acceptance checklist before implementation is considered complete

- Opening Inbox shows a full-width business list with no “select a business” instruction and no blank chat panel.
- Search starts on typing and never requires a button or Enter key.
- Scrolling loads more businesses without pagination controls or horizontal movement.
- Selecting a business updates the URL; reload and browser back preserve state.
- A multi-contact business can be viewed as one combined history and by individual contact.
- Sending always has an explicit, visible recipient.
- Older and newer message windows load automatically while preserving the viewport.
- Read-by markers match the WhatsApp Core cursor behavior.
- New messages and delivery updates arrive through Socket.IO without repeated polling.
- Permissions are enforced by business document on lists, routes, APIs, and events.
- The composer supports WhatsApp attachments, canned replies, templates, replies, reactions, optimistic sending, and retry.
- The same workflow passes at 375, 768, 1024, and 1440 px in light and dark themes.
- There is no horizontal scrollbar at any tested width or zoom level.

## References reviewed

- [Frappe CRM](https://github.com/frappe/crm) — application shell, sidebar, list, routing, and theme-token patterns
- [Frappe Helpdesk](https://github.com/frappe/helpdesk) — agent navigation, searchable saved replies, and responsive layouts
- [PrimeVue](https://github.com/primefaces/primevue) — accessible component behavior used through Relay-owned wrappers
- [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) — responsive, accessibility, search, motion, and delivery-review guidance
- [Anthropic frontend-design skill](https://github.com/anthropics/skills/tree/main/skills/frontend-design) — deliberate visual direction, copy restraint, and critique process
