# Relay Core

Frappe-based business communication workspace for WhatsApp, Telegram and email, backed by the separate [Relay Hub](https://github.com/andrometiq/relay_hub) Go service.

## Current status

Initial UI prototype, architecture and executable behavior specifications. This repository is **not yet an installable Frappe app**. The frontend uses sample data and in-memory state; Send and Publish do not call providers. Live APIs, MCP, AI, database persistence and migrations remain to be implemented.

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
