# Relay → Genie inbound contract (v1)

Relay POSTs each new inbound customer message to the Genie hooks communicator.

## Request

- `POST <genie_url>` (configured in Relay; the hooks path is `/relay`), `Content-Type: application/json`.
- `X-Hub-Signature-256: sha256=<hex HMAC-SHA256(secret, raw body)>` (same scheme as GitHub webhooks).
- `X-Relay-Delivery: <message_id>` (idempotency; hooks dedupes on it).
- Timeout 10 s. 2xx = accepted; redirects are not followed. Relay retries non-2xx/timeouts after 1, 2, 5, 10 and 15 min (6 tries over about 33 min, the scheduler runs each minute, with or without a Relay Hub), same message. After the last try Relay writes one Error Log (`Relay Genie delivery failed`).
- Each forwarded message has one `Relay Genie Delivery` row (named by the message id): status Pending, Sent, Replied, Noted, Note Failed, Failed or Skipped, attempts, next try, last error (140 characters) and delivered at. A delivery whose last try failed is Failed and also gets the staff note at once. The scheduler job does nothing before the migrate that adds the table. Tries and the voice-note wait live in this row, so a cache flush or a lost job loses nothing: a Pending row whose next try is due is queued again under a 2-minute lease. System Managers and Relay Communication Managers can read the list.

## Body

```json
{
  "version": 1,
  "site": "yrp.essdee.fit",
  "message_id": "RELAY-MSG-0000123456",
  "chat": "RELAY-CON-0000001234",
  "contact": "RELAY-CON-0000001234",
  "contact_name": "Display name",
  "channel": "WhatsApp",
  "text": "message text, or the voice transcript, or a caption",
  "message_type": "text | image | audio | video | document | sticker | location | ...",
  "has_media": true,
  "business": {"doctype": "Customer", "doctype_label": "Customer", "name": "CUST-0001"},
  "timestamp": "2026-11-25T10:50:52Z"
}
```

- `chat` is the Relay Contact id (`RELAY-CON-##########`), the same value as `contact`. Relay has no separate chat id: one chat is one Relay Contact. Pass it as `contact` to `reply_context`, `messages_list`, `chat_claim`, `chat_release` and `chat_mark_read`. `chat_send_text` does not take the chat: it takes `message` = the `message_id` of this body (a `RELAY-MSG-##########`) plus a unique `request_key`, and sends the reply to that message's contact and channel.
- Relay does not send a message of a chat staff took over: the Relay automation's rule (the contact's automation is paused, or the active episode ticket is held with AI off), except a pause made by an active MCP chat claim and a ticket held by the Genie user's own reply. Such a message follows the staff path. The takeover signals (the takeover API, a staff reply's episode hold, an MCP claim's pause) work while Relay AI or Genie is on. If the Genie check itself errors, the automation and email rule treat the message as not Genie's and log `Relay Genie check failed`.
- Relay does not send group chats (WhatsApp group, Telegram group, supergroup or channel), outgoing messages, imported history, system events, opt-out or opt-in keyword messages (STOP, START), or automatic email (auto-submitted or unauthenticated). Reactions and status updates are not new messages, so they are never sent. When `genie_business_types` is set, Relay sends only messages linked to those business types. When Automation test contacts (`automation_test_contacts`) is set, Relay sends only the messages of those contacts; the other contacts get neither Genie nor the Relay automation.
- For a voice note with a Relay transcript pending, Relay waits (as a retry) until it is ready, so `text` holds the transcript. If it is still not ready at the last try, `text` is the message content. The hooks device transcribes every voice note again with its own speech-to-text and uses that text when it gets one.
- `contact_name` is empty when the display name is a phone number or contains an email address.
- No phone numbers, emails or secrets in the body. Media bytes are not sent. The agent sees a picture through the Relay MCP `messages_media_read` (an MCP image block), and the hooks device reads a voice note's audio with `messages_media_read` `format: base64` (at most 3.75 MB).
- `business` is the business record linked to this message (Relay links it on receipt), or null when the message has none.
- A number with a marketing opt-out (after STOP) still sends its later, non-keyword messages: the opt-out covers campaigns only, the same rule as the Relay automation.

## Relay settings

Relay Settings (System Manager): `genie_enabled`, `genie_url` (https, or http only to a loopback, private or 100.64.0.0/10 address), `genie_secret` (Password, at least 32 characters), `genie_user` (the Relay user of the agent's MCP login and of the hooks `relay_token`; required to turn Genie on), `genie_business_types` (optional, one DocType per line). While Genie gets a message, the Relay automation (flows, channel steps, Relay AI) and email auto-reply rules do not reply to it.

## Replies

The Genie agent replies, claims chats and creates tickets through the Relay MCP (`/api/method/relay_core.mcp.endpoint`, `Authorization: token <key>:<secret>` held by the agent device, never shown to the model). `reply_context` returns `taken_over` (true when staff took the chat over, by the rule above): the agent then sends nothing and releases the chat.

The agent's `chat_send_text` passes `message` (the newest customer message), `after_message` (the newest message it read) and `request_key` = `genie-<that customer message id>-<n>`. A send with no answer is tried once more with the same key; only then the turn ends `fallback` and returns `request_key`.

Hooks' outbound for the `relay` provider, with the same Relay user as the agent (Relay keys a send by user and `request_key`):

- Fallback only: a `relay-fallback` notify whose first line is the agent's `request_key` (else `genie-<newest message>-1`) and whose rest is the text. Hooks calls `chat_send_text` with that key, `message` = the message the key names and `after_message` = the same message, so Relay returns the agent's send if it went, or refuses with "Chat changed" when anything came after that message. It never sends a second reply. A Relay call waits up to 5 min (the agent's MCP bridge too; a cut call answers a distinct `timeout:` error).
- Staff note: on `step_failed`, `turn_deadline`, `turn_stall` or `budget_breach` (never on a close: a wish closes for an operator stop or a playbook change), `chat_comment_add` on the chat with "Automatic reply could not be completed; please reply.", `request_key` from the wish id, so one note per wish.

## Watchdog

Each minute Relay checks Sent deliveries 10 min after delivery (index on status and delivered at). With an outgoing message after it, the status becomes Replied; with an internal note on the chat after it, Noted; with an active chat claim, it waits; else Relay adds one internal note "Not answered automatically; please reply." (key `genie-watch-<message>`, as Administrator) and sets Noted (Note Failed and one Error Log when the note fails). The relay turn's deadline is 8 min, so a cut turn's hooks note comes before the watchdog looks. The message stays unread for staff.

## Agent device

A profile with its own MCP servers (the Relay login) runs only sandboxed and with cgroup containment; every turn's CLI is denied reading the device state folder.
