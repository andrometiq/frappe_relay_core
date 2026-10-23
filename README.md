# Relay Core

Relay Core is a Frappe app for business conversations across WhatsApp, Telegram,
and email. It links messages to existing Frappe Contacts and business records.
The separate [Relay Hub](https://github.com/andrometiq/relay_hub) Go service owns
provider credentials, delivery, and provider callbacks.

Core uses the site's Frappe login, users, permissions, and API credentials. It
does not add a second login system. All app DocTypes and roles use Relay names.

## Start here

- [Documentation](docs/README.md): installation, guides, references, and tests.
- [Install on a test site](docs/core-installation.md).
- [Reply, react, and view message content](docs/messaging.md).
- [API and MCP reference](docs/api-reference.md).
- [Current support and limitations](docs/implementation-status.md).

For the installed UI, build `frontend` with `npm run build:site` and open `/relay`
on the Frappe site. See the installation guide for account connection settings.

## Development

From `frontend/`, install locked dependencies, build, and start a local preview:

```sh
npm ci
npm run build
npm run preview -- --port 18082
```

Open the URL printed by Vite. The WhatsApp v1 screens require same-origin Frappe APIs; the standalone preview does not provide
an authenticated Frappe site. See the [frontend guide](frontend/README.md).

Run backend contracts and frontend data tests as described in the
[testing guide](docs/testing.md). Database simulations use a separate Frappe test
site and local provider fixtures; they do not establish live-provider acceptance.

## Repository layout

| Directory | Purpose |
| --- | --- |
| `relay_core/` | Frappe APIs, permissions, channel projection, automation, and DocTypes |
| `frontend/` | Vue components and connected WhatsApp v1 workspaces |
| `tests/` | Backend contracts and isolated Frappe/database simulations |
| `specifications/` | Original behavior specifications |
| `docs/` | User/developer documentation and dated design records |

Development stays on `develop`. The user reviews and merges into `main`. Keep
tokens, `.env` files, site configuration, and real business data out of Git.
