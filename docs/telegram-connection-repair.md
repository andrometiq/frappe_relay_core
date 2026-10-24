# Telegram connection and send recovery

Core uses an account-scoped Hub credential saved in Relay Settings. Hub owns the bot token, webhook registration and provider connection. Verify the Hub connection in Settings before retrying a credential failure. Hub HTTP 401/403 responses are recorded as confirmed non-submission with a safe connection error.

## Durable recovery

Core creates a Relay Message Action before sending. Hub stores the corresponding outbox intent under a stable request key. Reconciliation reads `channels.deliveries` and validates the operation and destination before it projects a receipt.

| Condition | Behavior |
| --- | --- |
| Repeated request key | Core returns or reconciles the same action. Different content with that key is rejected. |
| Dispatching with no Hub intent | A successful empty Hub lookup permits admission recovery. Core rechecks the verified endpoint, business context, permissions and saved payload before submission. |
| Queued | Hub retries eligible work. Telegram 429 responses use bounded backoff and honor `retry_after`. |
| Uncertain | Core checks evidence. It does not replay the provider send or change the destination automatically. |
| Rejected | The original sender can review a retry. The retry has a stable child key and repeats the access and destination checks. |
| Bot accepted | Telegram accepted the request. This is not a delivered or read receipt. |

A missing or revoked endpoint blocks recovery. Replies retain their chat and topic. A group participant ID is not the group destination. Group replies must refer to a message in the selected topic. Reaction receipts require explicit acceptance and a matching chat and target message.

## Composer and updates

The inbox Telegram composer supports plain text, supported media and reply context. Text is limited to 4,096 characters; captions are limited to 1,024. The group composer uses verified chat/topic destinations. Saved drafts and stable request keys support reload recovery. See [current support](implementation-status.md) for channel boundaries.

Pending actions are owner-scoped and loaded in bounded pages. Relay Message Action changes publish a payload-free invalidation after commit. The inbox and Message activity refresh their permission-checked state from these events. Live updates use Socket.IO over WebSocket only. There is no periodic HTTP polling fallback. Reconnect and visibility changes trigger bounded refreshes; manual status checks remain available.

## Connected evidence

The 2026-10-24 Telegram report passes 11/11 cases. It proves verified ingress and replay, send permissions and idempotency, 429 backoff, attachment round trip, queued restart recovery, ambiguous acceptance without resend, Customer/Supplier sender choice, scoped AI/handoff and business-event outage isolation. Ten single inbound probes have p50/p95 105/123 ms.

The driver exercises real HTTP and Socket.IO with a fake Bot API. It does not prove installed-browser rendering, live bot permissions, every group/topic operation or a Telegram delivery/read stream. See Hub [release evidence](https://github.com/andrometiq/relay_hub/blob/develop/docs/simulation-validation.md) for report paths and rerun commands.

Source: `relay_core/messaging.py`, `relay_core/telegram_delivery.py`, `relay_core/business_access.py`, `relay_core/relay_core/doctype/relay_message_action/relay_message_action.py`, `frontend/src/services/realtime.js`, `frontend/src/composables/useMessages.js` and `frontend/src/services/channelComposition.js`.
