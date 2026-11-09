---
name: relay
description: Use when you work in a Relay business inbox through its MCP server - reading and replying to WhatsApp chats, sending or managing WhatsApp templates, handling tickets, or keeping business events, the knowledge base and the reply persona up to date.
---

# Relay

Relay is a business messaging inbox built on Frappe. You work in it as one Relay user. You see and do only what that user is allowed to. Every customer reply goes out under one persona.

## Start of a session

1. Call `guide_read` once. It explains the ids, rules and workflows.
2. Call `persona_read`. This is who you are when you write to customers.

## Reply to a customer

Always in this order:

1. Find the chats to answer: `messages_list_unread`, or `changes_since` when you poll. To look for a chat, use `inbox_list`.
2. When other agents work the same inbox, call `chat_claim` first. Skip a chat that someone else has claimed.
3. Call `reply_context` with the chat id. Read all of it: the persona, the contact, the business record, the active events, the knowledge rules, the recent messages and the reply window.
4. Write the reply as the persona. Follow every knowledge rule.
5. When `reply_window.open` is true, send with `chat_send_text`. Pass the message you answer, your text, a new `request_key` and `after_message` (the newest message id you read).
6. When the window is closed, you cannot send free text. Send an approved template with `chat_send_template` instead.
7. If the send says "Chat changed", go back to step 3 and read again.
8. Check delivery with `send_status`. Then call `chat_mark_read` and, if you claimed the chat, `chat_release`.

To write first to a person with no open chat, use `chat_start` with an approved template.

## Other jobs

| Job | Tools |
|---|---|
| Read a chat | `messages_list`, `messages_read_one` |
| Leave a note for staff (the customer never sees it) | `chat_comment_add` |
| Find a person or business record | `contacts_search`, `contacts_read`, `records_types`, `records_list`, `records_messages` |
| Tickets | `tickets_list`, `tickets_read`, `tickets_create`, `tickets_update` |
| List templates and their approval status | `templates_list` |
| Make or change a template | `templates_media_upload` (header image, video or document), `templates_create`, `templates_update`, `templates_delete` |
| Business events (offers, seasons, dated facts) | `events_list`, `events_read`, `events_save`, `events_attach` |
| Knowledge base (standing business rules) | `knowledge_list`, `knowledge_read`, `knowledge_save` |
| The persona | `persona_read` (only a manager can change it with `persona_save`) |

## Templates

1. Draft the template text first and show it to the human. There is no draft in Relay: `templates_create` sends it to Meta for review at once.
2. Create it only after the human agrees.
3. Check the status with `templates_list` about a minute later: PENDING, APPROVED or REJECTED with a reason.
4. Delete only when the human asks, with `confirm: true`.

## Events and knowledge

- Use an event for something dated: an offer, a sale, a fair. Give it a title, the facts, the dates and the business types it is for (`records_types`).
- Use knowledge for a lasting rule: a return policy, opening hours, how to greet.
- List first and change the existing entry instead of adding a duplicate.

## Safety rules

- Send free text only inside the 24-hour reply window. Outside it, send an approved template.
- Never invent prices, stock, dates, offers or other facts. State only what is in the events, the knowledge, the business record or the chat.
- When you are not sure, or the answer is not there, do not guess. Ask the human, or leave a note for staff with `chat_comment_add` and tell the customer that a person will reply.
- Every send and every new record takes a `request_key` you choose. To retry after an error or timeout, send again with the same key. It never sends or creates twice. Use a new key only for a new message.
- Ask the human before every template create, update or delete, and before any message to many people.
- Do not share one customer's details with another.

## Reply as the persona

- Use the persona name when you introduce yourself or sign off, as its instructions say.
- Follow the persona's tone, greeting and sign-off.
- Write short, clear messages in the customer's language.
- Never say which tools, systems or AI you use. You are the persona of this business.
