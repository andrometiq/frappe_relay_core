# Relay AI hand-over contract (v1)

Relay can give a whole chat to an agent runtime instead of answering it with Relay AI. Relay posts each new inbound customer message to the agent once. The agent answers through the Relay MCP.

## Setup

- Install frappe_tools and turn on Relay AI features (`enable_ai_features` in Relay Settings).
- In frappe_tools, create an AI Provider Account for the agent runtime (its Base URL and shared secret) and an AI Model on that account. A model is a conversation agent when the model and its account are enabled and the provider takes a hand-over.
- Create a Relay AI skill for the channel and business type, with that AI Model, Mode Automatic (Live). The agent's MCP login is a Relay user with the Relay AI Agent role.

Relay finds the skill the same way Relay AI does: the enabled skills of the message's channel for its business type, plus the channel's default skill, in name order. The first Live skill whose AI Model is a conversation agent takes the message. When no such skill applies, Relay AI answers as usual. A message with no business record goes to the channel's enabled default skill. While a message goes to an agent, the Relay automation (flows, channel steps, Relay AI) and email auto-reply rules do not reply to it.

## Request

- One background job per message (job id `relay-ai-hand-over:<message_id>`) calls frappe_tools `hand_over(<skill AI Model>, "relay", body)`. frappe_tools posts to `<Base URL>/relay` with `Content-Type: application/json`.
- `X-Hub-Signature-256: sha256=<hex HMAC-SHA256(secret, raw body)>` (same scheme as GitHub webhooks). The secret is the account's shared secret in frappe_tools.
- `X-Relay-Delivery: <message_id>`. The agent dedupes on it, because a replay of the inbound drain can post a message again.
- Timeout 10 s. 2xx = accepted; redirects are not followed. On a timeout, connection error or non-2xx answer Relay writes one Error Log (`Relay AI hand-over failed`) and does not try again. Retries and chats left unanswered are the agent's job.
- The job checks the message again before it posts: a chat staff took over in the meantime is not sent.

## Body

```json
{
  "version": 1,
  "site": "relay.example.com",
  "message_id": "RELAY-MSG-0000123456",
  "chat": "RELAY-CON-0000001234",
  "contact": "RELAY-CON-0000001234",
  "contact_name": "Display name",
  "channel": "WhatsApp",
  "text": "message text, or Relay's voice transcript, or a caption",
  "transcript": "Relay's voice transcript, or empty",
  "transcript_status": "Pending | Completed | Failed | Unavailable, or empty",
  "message_type": "text | image | audio | video | document | sticker | location | ...",
  "has_media": true,
  "business": {"doctype": "Customer", "doctype_label": "Customer", "name": "CUST-0001"},
  "timestamp": "2026-11-25T10:50:52Z"
}
```

- `chat` is the Relay Contact id (`RELAY-CON-##########`), the same value as `contact`. Relay has no separate chat id: one chat is one Relay Contact. Pass it as `contact` to `reply_context`, `messages_list`, `chat_claim`, `chat_release` and `chat_mark_read`. `chat_send_text` does not take the chat: it takes `message` = the `message_id` of this body (a `RELAY-MSG-##########`) plus a unique `request_key`, and sends the reply to that message's contact and channel.
- Relay does not send a message of a chat staff took over: the Relay automation's rule (the contact's automation is paused, or the active episode ticket is held with AI off), except a pause made by an active MCP chat claim and a ticket held by the reply of a user with the Relay AI Agent role. A staff reply never opens a ticket. When a staff reply finds an active episode ticket, it holds that ticket. A staff reply alone does not stop the hand-over: the agent reads the recent messages and decides whether the staff conversation is still going on. The Relay automation instead treats a chat as taken over when, with no held or resumed episode ticket, the newest outgoing message that a person sent in the last 24 hours is from staff (not Administrator, not a Relay AI Agent user); automatic sends do not count. Such a message follows the staff path. If the hand-over check itself errors, the automation and email rule treat the message as Relay's and log `Relay AI hand-over check failed`.
- Relay does not send group chats (WhatsApp group, Telegram group, supergroup or channel), outgoing messages, imported history, system events, opt-out or opt-in keyword messages (STOP, START), or automatic email (auto-submitted or unauthenticated). Reactions and status updates are not new messages, so they are never sent. When Automation test contacts (`automation_test_contacts`) is set, Relay sends only the messages of those contacts.
- A voice note goes at once; Relay never waits for its own transcript. When Relay already has one, `transcript` holds it (and `text` too); else `transcript` is empty and the agent transcribes the audio itself.
- `contact_name` is empty when the display name is a phone number or contains an email address.
- No phone numbers, emails or secrets in the body. Media bytes are not sent. The agent sees a picture through the Relay MCP `messages_media_read` with the default format (an MCP image block), and reads a voice note's audio with `format: base64` (at most 3.75 MB).
- `business` is the business record linked to this message (Relay links it on receipt), or null when the message has none.
- A number with a marketing opt-out (after STOP) still sends its later, non-keyword messages: the opt-out covers campaigns only, the same rule as the Relay automation.

## Replies

The agent replies, claims chats, adds staff notes and creates tickets through the Relay MCP (`/api/method/relay_core.mcp.endpoint`, logged in as the agent's Relay user). `reply_context` returns `taken_over` (true when staff took the chat over, by the rule above): the agent then sends nothing and releases the chat.

The agent's `chat_send_text` passes `message` (the newest customer message), `after_message` (the newest message it read) and a `request_key` unique to that reply. Relay keys a send by user and `request_key`, so a send repeated with the same key returns the first send, and a send after a newer message is refused with "Chat changed". When the agent cannot answer, it adds a staff note on the chat (`chat_comment_add`).
