# Telegram typing feedback

The text composer sends a source-message reference alongside agent typing presence. Core rechecks the message, business contact, enabled channel and verified endpoint, derives the Telegram destination and forum topic from stored provider context, and coalesces all agents/tabs for that destination with a four-second Redis lease. Draft text is never transmitted by this operation.

Hub exposes account-scoped `telegram.typing` under `messages:send`. It calls only `sendChatAction` with `typing`, with a two-second deadline. This ephemeral signal does not enter the message outbox or delivery journal and is not automatically retried. Empty drafts and channel changes stop local typing updates. Telegram expires its own indicator within five seconds: https://core.telegram.org/bots/api#sendchataction .

This implements outbound Telegram typing only. It does not claim customer typing events for bot channels or email typing support. For WhatsApp, see [WhatsApp read receipts and typing](whatsapp-read-signals.md). Existing Relay agent presence remains separate.

## Evidence — 2026-09-24

- Guarded Frappe database/Redis integration passed verified source routing, private-chat and forum-topic handling, shared lease coalescing, stopping without a provider call, and revoked-endpoint denial. Provider calls were mocked.
- Go Telegram, channel and MCP package checks passed; Telegram and MCP race tests passed. Tests verified payload validation, disabled-account denial, account isolation and messages:send scope.
- Browser chat acceptance with API fixtures verified source-message references on typing calls and passed existing chat, recipient, draft, pending-recovery and retry checks.
- Current local Hub rebuilt and restarted, readiness HTTP 200; Core frontend built and workload reloaded. Runtime metadata is in Hub .runtime/typing-deployment.json. The user-facing typing indicator has not been observed on a real Telegram client.
