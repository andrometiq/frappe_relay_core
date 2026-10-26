# WhatsApp read receipts and typing

Relay sends two signals to a customer in a one-to-one WhatsApp chat. Both use the Hub operation `messages.read`, because Meta accepts a typing indicator only together with a read receipt.

| Signal | Trigger | Setting in Relay Settings | Lease |
| --- | --- | --- | --- |
| Read receipt (blue ticks) | An operator marks messages read (`message_reads.mark`). | `send_whatsapp_read_receipts` | 5 seconds per contact and message |
| Typing indicator | An operator types a reply (`inbox.typing` or `business_inbox.typing` with a source message). | `send_whatsapp_typing` | 4 seconds per contact |

Both settings are on by default.

## Rules

- Core sends one signal for the newest incoming WhatsApp message of the contact. For a read receipt, Core looks only at the messages that the operator marked. For typing, Core looks at the channel of the source message.
- Core skips group messages, other channels, imported legacy messages and messages older than 30 days. Meta refuses older messages.
- A Redis NX lease stops repeats from other tabs and agents. A newer message gets its own read receipt.
- Core queues the Hub call on the `short` queue with a job ID, so the request stays fast. The job ignores a Hub rejection, for example for an expired message. The Hub does not queue, retry or store the call.
- A failure to queue the signal never fails the read mark or the typing call. Core writes an Error Log entry instead.
- The typing indicator also marks the message as read on WhatsApp. WhatsApp removes the indicator after 25 seconds or when Relay sends a reply.

Code: `relay_core/whatsapp_presence.py`. Tests: `tests/test_whatsapp_presence.py` and `tests/integration_whatsapp_presence_site.py`.
