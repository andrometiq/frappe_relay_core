"""Channels, feature state, workspace activity and business record tools."""
from relay_core.mcp_tools.registry import CURSOR, NAME_FIELD, READ, limit, obj, tool


@tool('channels_list', READ, obj({}), {
    'summary': 'List the Relay Channels (WhatsApp numbers, Telegram bots, mailboxes) of this site.',
    'use_when': 'a send, template or campaign needs a channel name (RELAY-CH-...).',
    'avoid_when': 'you need contacts or chats; use contacts_search or inbox_list.',
    'returns': '{items: [{name, channel, enabled, label, address, is_default}]}.',
    'errors': '"Not permitted" when the user has no Relay role.'})
def channels_list():
    from relay_core.api import channel_options
    return channel_options()


@tool('settings_read', READ, obj({}), {
    'summary': 'Read which Relay features are on and what the current user may do. Read only.',
    'use_when': 'checking if campaigns, flows, folders or AI are available before using those tools.',
    'avoid_when': 'you want to change a setting; settings cannot be changed over MCP.',
    'returns': '{connection: Hub link state and feature switches, capabilities: roles, enabled channels, file size limit}.',
    'errors': '"Not permitted" without a Relay role.'})
def settings_read():
    from relay_core import api, settings
    return {'connection': settings.connection(), 'capabilities': api.capabilities()}


@tool('account_overview', READ, obj({}), {
    'summary': 'Read the last 7 days of message activity and the current unread queue counts.',
    'use_when': 'the user asks how busy the inbox is or wants a daily summary.',
    'avoid_when': 'you need the messages themselves; use messages_list_unread.',
    'returns': '{activity: daily incoming and outgoing counts, queues: unread and open counts}.',
    'errors': '"Not permitted" without a Relay role.'})
def account_overview():
    from relay_core import overview, queue_counts
    return {'activity': overview.read(), 'queues': queue_counts.read()}


@tool('records_types', READ, obj({}), {
    'summary': 'List the business record types (DocTypes such as Customer) the user can open in Relay.',
    'use_when': 'before records_list, or to fill business_doctype in another tool.',
    'avoid_when': 'you already know the DocType name.',
    'returns': '{items: [doctype name]}.',
    'errors': '"Not permitted" without a Relay role.'})
def records_types():
    from relay_core.api import business_types
    return business_types()


@tool('records_list', READ, obj({'doctype': NAME_FIELD, 'query': {'type': 'string', 'maxLength': 80}, 'after': CURSOR},
                                ('doctype',)), {
    'summary': 'Search business records of one type that have Relay chats, 30 per page.',
    'use_when': 'finding the record (for example a customer) whose chats you want.',
    'avoid_when': 'you search for a person; use contacts_search.',
    'returns': '{items: [{name}], next: cursor for after or null}.',
    'errors': '"Not permitted" for a type that is not enabled for the user.'})
def records_list(doctype, query='', after=None):
    from relay_core.business_inbox import records
    return records(doctype, query, after)


@tool('records_messages', READ, obj({'doctype': NAME_FIELD, 'name': NAME_FIELD, 'before': CURSOR, 'channel': CURSOR,
                                     'limit': limit(100, 50)}, ('doctype', 'name')), {
    'summary': 'Read messages across every chat linked to one business record, oldest first in the page.',
    'use_when': 'the user asks what was discussed with a customer or another business record.',
    'avoid_when': 'you know the one chat; use messages_list.',
    'returns': '{items: messages, has_more, first, last}. Page back with before=first.',
    'errors': '"Not found" or "Not permitted" for a record the user cannot read.'})
def records_messages(doctype, name, before=None, channel=None, limit=50):
    from relay_core.business_inbox import messages
    return messages(doctype, name, before=before, channel=channel, limit=limit)
