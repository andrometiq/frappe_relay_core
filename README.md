# Relay Core

Relay Core is a Frappe app for business conversations across WhatsApp, Telegram and email. It links verified identities to existing Contacts and business records. One person can link to both Supplier and Customer. Reply context, sender choice and triage select the business; permissions remain business-scoped.

[Relay Hub](https://github.com/andrometiq/relay_hub) is the separate Go service for provider credentials, delivery and callbacks. Core uses the site's Frappe login, users and permissions. It does not add a second login system.

The installed workspace includes Telegram and email composers, durable send recovery, AI skills with `get_doc`/`get_list` only, one-ticket handoff and business-event delivery after commit. Channel preferences record business/person consent. Relay history does not block business update, cancel or delete. Live updates use Socket.IO over WebSocket with no periodic HTTP polling fallback.

| Task | Documentation |
| --- | --- |
| Browse guides | [Documentation](docs/README.md) |
| Install on a test site | [Installation](docs/core-installation.md) |
| Understand identity and automation | [Business communication](docs/communication-expansion.md) |
| Compose email | [Email composition](docs/chat-email-recipients.md) |
| Recover Telegram sends | [Telegram recovery](docs/telegram-connection-repair.md) |
| Integrate APIs | [API and MCP reference](docs/api-reference.md) |
| Check support and evidence | [Implementation status](docs/implementation-status.md) |

The 2026-10-24 connected checkpoint passes 10/10 WhatsApp, 11/11 Telegram and 13/13 email cases. The drivers use local fake providers with real Hub/Core APIs and Socket.IO. They do not prove browser rendering, live provider acceptance, bulk campaign support or production capacity.

## Development

The standard app build (`bench build` or `pilot build`) installs the frontend packages and builds the installed UI. To build it by hand, run from the app root, then open `/relay` on the Frappe site:

```sh
yarn install --frozen-lockfile
yarn build
```

For a standalone preview, run from `frontend/`:

```sh
yarn build:preview
yarn preview --port 18082
```

Connected screens require same-origin Frappe APIs. The preview does not provide an authenticated site. See the [frontend guide](frontend/README.md) and [testing guide](docs/testing.md).

| Directory | Purpose |
| --- | --- |
| `relay_core/` | Frappe APIs, permissions, channel projection, automation and DocTypes |
| `frontend/` | Vue components and connected communication workspaces |
| `tests/` | Backend contracts and isolated site/database tests |
| `specifications/` | Behavior specifications |
| `docs/` | User and developer documentation |

Development stays on `develop`. The user reviews and merges into `main`. Keep credentials, site configuration and real business data out of Git.
