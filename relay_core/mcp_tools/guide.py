"""The domain guide served as relay://guide and guide_read, and the generated docs/mcp.md."""
from relay_core.mcp_tools.registry import DOC_PARTS, READ, SAFETY, listed, obj, tool

URI = 'relay://guide'
INSTRUCTIONS = ('Relay is the business messaging inbox of this site (WhatsApp, Telegram and email). You act as the signed-in '
                'user and see only what that user sees. Read the guide first (tool guide_read or resource relay://guide). '
                'Tools that send to a customer need a request_key you choose; reuse it to retry, it never sends twice. '
                'Ask the user before every customer send, campaign start and template submit or delete. With other agents on the same '
                'inbox, follow the safe polling loop of the guide: changes_since, chat_claim, read, send with after_message, chat_release.')
GUIDE = """# Relay guide

## Domain model
- **Contact** (`RELAY-CON-##########`): one person or group you talk to. It has **endpoints** (a phone number, Telegram chat or email address) and the Frappe Contact behind it.
- **Channel** (`RELAY-CH-##########`): one WhatsApp number, Telegram bot or mailbox. `channels_list` gives them.
- **Message** (`RELAY-MSG-##########`): one incoming or outgoing message in a chat.
- **Chat**: all messages of one Contact. `inbox_list` lists chats; `messages_list` reads one.
- **Business record**: an ERP document (for example a Customer) that a Contact is linked to. `records_types`, `records_list` and `records_messages` show the record tiles.
- **Ticket** (`TKT-#####`): a support case made from messages.
- **Template**: a WhatsApp message approved by Meta. Only templates can start a chat or reach a person after 24 hours.
- **Campaign**: one template or message sent to many numbers, with live counts.

## Rules
- **24-hour window**: on WhatsApp you can send free text or media only within 24 hours of the customer's last message. After that the send fails with "Outside the 24-hour reply window"; send an approved template with `chat_send_template` instead. `messages_read_one` shows if the window is open.
- **Customer sends** (class S) reach a real person or change live state. Every one needs `request_key`. A repeated key returns the first result and sends nothing new. Use a new key only for a new message.
- **Confirm**: campaign start, schedule, resume and retry, template delete and flow publish need `confirm: true`. Campaign start and schedule also need `expected_recipients` equal to the count from `campaigns_validate`.
- **Permissions**: you act as the API key's user. A chat, record or campaign the user cannot see returns "Not found" or "Not permitted". Campaigns, contacts_create and flows need the Relay Communication Manager role.
- **Templates** go to Meta for review the moment you create or update them; there is no local draft. Status starts as PENDING; read it again with `templates_list`.

- **Several actors**: staff in the portal, the Relay automation and AI, and other MCP agents can work on the same chats. Each MCP agent is its own Frappe user. Replies show `sent_by` and `via` (`mcp`, `automation`, `staff` or `system`).
- **Read state is yours**: `chat_mark_read` changes only your user's unread count. It sends no read receipt and hides nothing from staff or other agents.
- **Claims**: `chat_claim` holds a chat for up to 30 minutes. Other MCP agents then get "Chat claimed by X until T" on every send to it, and the Relay automation and AI stop replying (when your user has the Relay Communication Manager role). `chat_release`, or the end of the claim, resumes them. Staff in the portal can still reply.
- **Reply guard**: pass `after_message` (the newest message you read) on every send. When a newer message or send exists, the send is refused with "Chat changed: ..."; read the chat again before you answer. A repeat with the request_key of your own earlier send skips the guard and returns the first result.

## Workflows
**Safe polling loop (several agents)**
1. `changes_since` with your saved cursor. Save the new cursor at once. The first call, without a cursor, gives the current cursor.
2. For each chat with an `inbound` event that you will answer: `chat_claim` (skip the chat if it is claimed by another agent).
3. `messages_list` or `messages_read_one` to read the chat and the reply window.
4. `chat_send_text` (or `chat_send_template`) with a new request_key and `after_message` set to the newest message you read. On "Chat changed", go back to step 3.
5. `chat_mark_read`, then `chat_release`.

**Reply to unread messages**
1. `messages_list_unread` to see unread incoming messages by chat.
2. `messages_read_one` for one message with context and the reply window state.
3. `chat_send_text` with that message id, your text, a new request_key and `after_message` (or `chat_send_template` when the window is closed).
4. `send_status` with the returned message id to follow delivery.
5. `chat_mark_read` to clear the chat's unread count for the user.

**Create a template**
1. `templates_media_upload` when the header has an image, video or document; keep the returned handle.
2. `templates_create` with name, language, category and components; it is submitted to Meta at once.
3. `templates_list` about a minute later (after the next sync) to see PENDING, APPROVED or REJECTED with the reason.

**Run a campaign**
1. `campaigns_create` with a title, an approved template (or a message) and rows of phone numbers and values. It never sends.
2. `campaigns_validate` for the sendable recipient count, skipped rows and issues. Show this to the user.
3. `campaigns_control` with action start, `confirm: true` and `expected_recipients` from step 2.
4. `campaigns_read` to follow the counts; pause, resume or cancel with `campaigns_control`.
5. `campaigns_retry_failed` with `confirm: true` once a completed campaign has failed rows.
"""


@tool('guide_read', READ, obj({}), {
    'summary': 'Read the Relay domain guide: ids, rules and step-by-step workflows.',
    'use_when': 'starting a session, or before the first send, template or campaign.',
    'avoid_when': 'you already read it in this session.',
    'returns': '{guide: markdown text}.',
    'errors': 'none.'})
def guide_read():
    return {'guide': GUIDE}


def resources() -> list[dict]:
    return [{'uri': URI, 'name': 'guide', 'title': 'Relay guide', 'description': 'Domain model, rules and workflows.',
             'mimeType': 'text/markdown'}]


def read_resource(uri) -> dict:
    if uri != URI:
        raise LookupError(f'Unknown resource {uri}')
    return {'contents': [{'uri': URI, 'mimeType': 'text/markdown', 'text': GUIDE}]}


def markdown() -> str:
    """docs/mcp.md from the registry, so the reference cannot drift from the code."""
    lines = ['# Relay MCP', '', 'Generated by `python -m relay_core.mcp_tools`. Do not edit by hand.', '',
             'Endpoint: `POST /api/method/relay_core.mcp.endpoint` with `Authorization: token <api key>:<api secret>` of a user '
             'with a Relay role. JSON-RPC 2.0, protocol 2025-06-18, tools and resources. Browser requests (an `Origin` header) '
             'and cookie sessions are refused. Requests are at most 1 MB; `templates_media_upload` may send up to 7 MB.', '',
             'Safety classes: ' + ', '.join(f'**{key}** {label}' for key, label in SAFETY.items()) + '.', '',
             'The older `relay.*` tool names still work but are not listed.', '', GUIDE.replace('# Relay guide', '## Guide'),
             '## Tools', '']
    for entry in sorted(listed(), key=lambda item: item.name):
        lines += [f'### `{entry.name}` ({entry.safety})', '', entry.doc['summary'], '']
        lines += [f'- **{label}:** {entry.doc[key]}' for key, label in DOC_PARTS]
        arguments = ', '.join(f'`{name}`' + ('' if name in entry.schema['required'] else '?') for name in entry.schema['properties'])
        lines += [f'- **Arguments:** {arguments or "none"}', '']
    return '\n'.join(lines)
