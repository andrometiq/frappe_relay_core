# Relay Core

Frappe-based business communication workspace for WhatsApp, Telegram and email, backed by the separate [Relay Hub](https://github.com/andrometiq/relay_hub) Go service.

## Current status

Initial UI prototype, architecture and executable behavior specifications. This repository is **not yet an installable Frappe app**. The frontend uses sample data and in-memory state; Send and Publish do not call providers. A server-side read-only Hub MCP client is now implemented; business APIs, AI, Core database persistence and migrations remain to be implemented.

## Contents

- `frontend/`: Vue prototype using actual Frappe UI components; inbox, team forms and fixed flow node editor.
- `specifications/`: Relay-prefixed DocType naming registry and read-state/permission reference model.
- `docs/architecture.md`: architecture, requirements, implementation sequence and release gates.
- `docs/architecture.png`: visual overview.

## Development

Frontend: `cd frontend`, `npm install`, `npm run build`, then `npm run preview`.

Behavior specification: `python3 -B -m unittest discover -s specifications -v`.

The frontend dependency manifest includes its icon build plugin. A fresh dependency install and production frontend build passed. The dependency lockfile is committed; use `npm ci` for subsequent installs.

All new DocTypes, including child tables, use the `Relay ` prefix. Existing Frappe masters remain unchanged. No production site configuration or credentials belong in this repository.

## Branch workflow

Development happens on `develop`. The user merges reviewed work into production `main`.

## Local Hub connection

A server-side Core service package now provides the initial read-only MCP integration. `.env` is loaded automatically by the client, with process environment taking precedence. Copy `.env.example` to `.env` and set `RELAY_HUB_TOKEN` to the local Hub's `RELAY_MCP_TOKEN`; protect the file with mode 0600. Local files have already been configured on the development workstation and are excluded from Git. Never expose the service token through frontend/Vite configuration.

```sh
python3 -B -m relay_core check-hub
python3 -B -m unittest discover -s tests -v
RELAY_LIVE_TEST=1 python3 -B -m unittest discover -s tests -v
```

The live tests initialize an MCP session, call Hub `health.get`, and verify an invalid token receives 401. They perform no provider or business-data writes. This is a narrowly scoped stateless JSON MCP client, not a complete MCP SDK. Production multi-account authentication and Frappe installation remain future work. HTTPS is required except for explicit loopback IPs; redirects are rejected to avoid forwarding credentials to another destination.
