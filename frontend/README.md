# Relay Core frontend

Vue 3, PrimeVue unstyled, Tailwind and the local `@relay/ui` wrappers. Both entry
points mount the same connected WhatsApp v1 application. There are no sample
screens or simulated save/send actions in the application.

## Screens

| Route | Contents |
| --- | --- |
| `/relay#/messages` | All/Mine/Unread/Unassigned queues, manager Unlinked link, business directory, recipient and sending number, history/search, attachments, reply window, approved templates, notes, assignment and reviewed retries |
| `/relay#/contacts` | Frappe Contact search, WhatsApp endpoint validity/binding timestamps, permitted business links and manager sender triage (`?tab=unlinked`) |
| `/relay#/whatsapp` | Template list, language/category/status filters, detail/preview, rejection reason, manager editor and socket status updates |
| `/relay#/teams` | Communication teams/members, separate business responsibility groups, role explanations and Frappe permission links |
| `/relay#/settings` | Setup checklist, saved connection verification, callback-secret readiness, account/number readback, channel/business-type configuration links and saved replies |
| `/relay#/activity` | Manager delivery controls, uncertain outcomes, failed-message links, callback/projection receipt status, recovery and socket health |

The sidebar stays visible above 640px. Mobile uses a compact header and keyboard
accessible drawer. Connection status and notifications remain visible on both.
Template tables become labeled cards on mobile. Existing theme tokens are used.

## Build and test

In this worktree, `node_modules` is a shared symlink. Do not install packages or
modify it. With the existing dependencies:

```sh
node --test frontend/tests/*.test.mjs frontend/tests/*.test.js
cd frontend
yarn build
```

The site build writes only `relay_core/public/relay` within this repository.
Generated assets are ignored. The standalone build needs same-origin Frappe
APIs and an authenticated session; it does not fabricate successful requests.

`tests/browser/v1Acceptance.mjs` exports an acceptance function taking an existing
Playwright browser and a Vite origin. It intercepts all APIs with local-only
fixtures and exercises all six screens, five viewport widths, recipient resets,
rejected-send retry, inline errors, empty lists and business-group deep links.
It also checks unread refresh after reads, mixed-contact read/note ownership,
send-dialog navigation, repeated notification note links, business-context resets
and dialog/menu touch targets on mobile and desktop.
It does not establish installed-site or provider acceptance.

Realtime invalidation uses the existing Socket.IO transport, including Frappe
list updates. No polling has been added. Recovery timers and reply-window expiry
are local state/timing controls, not polling loops.

See [v1 validation and remaining gaps](../docs/v1-ui-validation.md). Do not call a
change ready for developer testing until the orchestrator installs this worktree
on the exact isolated site, builds there, applies approved workspace migration,
reloads backend processes and verifies real local records through the site.
