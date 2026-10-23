# Relay Core frontend

Vue 3 with PrimeVue unstyled components behind Relay-owned wrappers. This directory contains both design previews
and workspaces that call the installed Core backend.

## Installed workspace

Run `npm ci` and `npm run build:site`, then restart the site's Frappe web workers.
Open `/relay` on the installed site. This entry includes only Messages, WhatsApp,
Automation, and Settings and uses standard Frappe login and CSRF protection.
The build goes to `relay_core/public/relay`; it is ignored by Git and rebuilt for
each deployment. See [installation](../docs/core-installation.md).

## Build and preview

From this directory:

```sh
npm ci
npm run build
npm run preview -- --port 18082
```

Open the URL printed by Vite. The preview binds to loopback by default.
`npm ci` uses the committed dependency lockfile. Do not put Hub/provider tokens
in frontend environment variables.

## Views

| View | Data source |
| --- | --- |
| Messages | Same-origin Core contacts/history/typed-send/sticker APIs |
| Automation | Same-origin Core automation APIs |
| WhatsApp tools | Core's permission-checked WhatsApp operations |
| Sample Inbox, dashboard, folders, team forms, flow diagram | Design-preview data and state |

Core uses the host Frappe site's login. The standalone Vite preview has no
Frappe session/backend of its own; connected views should show an unavailable
or permission error there, rather than fabricated success.

Messages retain a bounded history window and render typed content with shared
components. Telegram TGS rendering is loaded on demand and has resource limits.
See [message behavior](../docs/messaging.md) and
[current limitations](../docs/implementation-status.md).

## Components and tests

`DocumentForm` composes individual fields. `RelayForm`, `RelaySelect`,
`RelayTable`, and paging/virtual-row components provide reusable building blocks.
`MessageContent` renders a stored typed message. `TgsSticker` owns animated
sticker loading and cleanup.

Run `node --test frontend/tests/*.test.mjs` from the repository root. Browser
fixtures under `tests/browser/` exercise the built components with synthetic
data. See the [testing guide](../docs/testing.md).

Production integration must serve connected views with the site's authenticated
API and CSRF behavior. A preview build alone is not that integration.
