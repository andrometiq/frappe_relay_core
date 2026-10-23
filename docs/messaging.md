# Reply, react, and view message content

Use this guide with Core installed on a test site, an enabled Relay Channel,
a verified endpoint, and a readable incoming Relay Message. Provider credentials
are configured in Hub. See [installation](core-installation.md).

## Read a conversation

The Messages workspace uses same-origin Core APIs. Search for a Relay Contact,
select it, and choose a message to reply to. The provider, chat, topic, and quote
come from that message.

The current workspace loads 50 messages at a time and retains at most 150 while
browsing earlier history. Refresh loads the current page. This view is a bounded
connected workspace; it is not the completed automatic scroll/read-state inbox.

## Send a quoted reply

For an authenticated non-browser integration, POST to:

```text
/api/method/relay_core.messaging.send
```

Example body, replacing the message reference with an accessible test record:

```json
{
  "message": "RELAY-MSG-0000000001",
  "kind": "text",
  "data": {"text": "We received your request."},
  "request_key": "test-reply-001"
}
```

Use the Frappe authentication described in [authentication](authentication.md).
An authenticated browser uses its site session and CSRF token instead.

The response is inside Frappe's `message` envelope:

```json
{
  "message": {
    "action": "<Relay Message Action name>",
    "status": "Submitted",
    "message": "<outgoing Relay Message name>"
  }
}
```

The strings in angle brackets are placeholders, not literal record names.
`Submitted` means the provider request was accepted; it does not prove delivery
or reading.

## Choose content

All examples below use the same endpoint and source-message binding.

| Kind | `data` example | Behavior |
| --- | --- | --- |
| `text` | `{"text":"Hello"}` | Reply to the selected provider message |
| `reaction` | `{"emoji":"👍"}` | Set the bot/business reaction on the target |
| `reaction` | `{"emoji":""}` | Clear that reaction |
| `sticker` | `{}` | Resend the selected readable incoming sticker; do not pass a URL or local path |
| `location` | `{"latitude":13.0827,"longitude":80.2707}` | Share a fixed coordinate |

For a contact card:

```json
{
  "message": "RELAY-MSG-0000000001",
  "kind": "contact",
  "data": {
    "contacts": [{
      "name": {"formatted_name": "Example Person", "first_name": "Example"},
      "phones": [{"phone": "+12025550123"}]
    }]
  },
  "request_key": "test-contact-001"
}
```

To quote one message while reusing another sticker, supply
`{"sticker_message":"RELAY-MSG-0000000002"}`. That sticker must be readable and
belong to the same contact and channel. An optional `file_id` must match the
stored source. Outgoing copies retain the incoming sticker reference for reuse.

Telegram sends one contact card per call. WhatsApp accepts a bounded array of
cards. Portable contact details are preserved in Telegram's vCard field.
Core's typed facade exposes ordinary emoji reactions; Telegram custom
emoji reactions are available in Hub's lower-level typed API, subject to provider
eligibility.

## Provider support

| Content | WhatsApp direct | WhatsApp group | Telegram private/group/topic |
| --- | --- | --- | --- |
| Text and quoted replies | Supported | Supported | Supported |
| Stickers | Supported media path | Supported media path | Supported |
| Set/clear reactions | Supported | Rejected | Supported when bot/chat allows |
| Static location | Supported | Rejected | Supported |
| Contact card | Supported | Rejected | Supported, one card |

This table describes Relay's implemented paths and local tests, not approval of
a specific provider account. Meta lists text, media, and templates for groups;
Relay rejects the other types locally. See
[Meta group messaging](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/groups-messaging/)
and the [Telegram Bot API](https://core.telegram.org/bots/api). Checked 2026-09-23.

A quote never changes the route to a group participant's direct chat. Telegram
forum replies preserve the topic from the source message.

## Retry safely

Choose one stable request key for one user intent. Reuse it after a timeout.

| Action status | Meaning |
| --- | --- |
| `Dispatching` | Durable intent exists; final submission result is not yet recorded |
| `Submitted` | Provider acceptance recorded |
| `Rejected` | Known rejection before/at submission |
| `Uncertain` | The provider may have received the action; investigate before another send |

Reusing a key with the same content returns its stored action; changing content
under the same key is rejected. Creating a new key after an uncertain result can
send a duplicate. Automatic reconciliation is not completed.

## View stickers and updates

The UI reads stickers through
`/api/method/relay_core.messaging.sticker?message=<Relay Message name>`.
The route checks permissions and returns up to 2 MiB of WebP, WebM, or Telegram
TGS bytes. It does not expose provider tokens.

Animated Telegram stickers load their renderer on demand. The component pauses
when hidden and releases resources when removed. Oversized or unsupported
animations show a fallback; they do not get unlimited browser resources.

Incoming reactions and Telegram edits update the original Relay Message.
They do not become new user questions or trigger a fresh automatic reply.
Unknown targets remain uncategorized for investigation.
