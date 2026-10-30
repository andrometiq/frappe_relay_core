"""Chat list, unread messages, history, read state and internal notes."""
from relay_core.mcp_tools.registry import CURSOR, FLAG, NAME_FIELD, READ, WRITE, limit, obj, tool

CONTACT = {'type': 'string', 'pattern': '^RELAY-CON-[0-9]{10}$', 'description': 'Relay Contact id, RELAY-CON-##########.'}
MESSAGE = {'type': 'string', 'pattern': '^RELAY-MSG-[0-9]{10}$', 'description': 'Relay Message id, RELAY-MSG-##########.'}
MESSAGE_FIELDS = ('name', 'direction', 'content', 'message_type', 'status', 'creation', 'sent_at', 'channel', 'transcript',
                  'delivery_error', 'business_doctype', 'business_name', 'sent_by', 'via', 'client')
CHAT_FIELDS = ('name', 'display_name', 'unread', 'channel', 'provider', 'business', 'latest_preview', 'latest_at', 'starred',
               'folder', 'assignment', 'unlinked')
UNREAD_PER_CHAT = 10


def brief(row, fields=MESSAGE_FIELDS):
    return {key: row.get(key) for key in fields if key in row}


@tool('inbox_list', READ, obj({'mode': {'type': 'string', 'enum': ['all', 'unread', 'read', 'unlinked'], 'default': 'all'},
                               'query': {'type': 'string', 'maxLength': 80}, 'channel': CURSOR, 'team': CURSOR,
                               'starred': FLAG, 'folder': CURSOR, 'business_type': CURSOR, 'after': CONTACT}), {
    'summary': 'List chats, newest activity first, 30 per page, with unread counts and the latest preview.',
    'use_when': 'browsing or searching chats by name, number, channel, team or business type.',
    'avoid_when': 'you need the unread messages themselves; use messages_list_unread.',
    'returns': '{items: [{name (RELAY-CON-...), display_name, unread, channel, business, latest_preview, latest_at}], '
               'next: {after} or null}.',
    'errors': '"Invalid conversation filter" for a bad mode; "Not permitted" without a Relay role.'})
def inbox_list(mode='all', query='', channel=None, team=None, starred=0, folder='', business_type=None, after=None):
    from relay_core.inbox import directory
    page = directory(query=query, after=after, starred=starred, folder=folder, mode=mode, team=team, channel=channel,
                     business_type=business_type)
    return {'items': [brief(row, CHAT_FIELDS) for row in page['items']], 'next': page['next']}


@tool('messages_list_unread', READ, obj({'channel': CURSOR, 'limit': limit(50, 20), 'after': CONTACT}), {
    'summary': 'List unread incoming messages, grouped by chat, newest chats first.',
    'use_when': 'the user asks what is new, unanswered or waiting for a reply.',
    'avoid_when': 'you want a full chat history; use messages_list.',
    'returns': '{chats: [{contact, display_name, unread, channel, business, messages: [{name, content, message_type, '
               'creation}]}], next: {after} or null}. At most limit chats, 10 messages per chat and limit messages in '
               'total; chats whose newest unread are not incoming are left out.',
    'errors': '"Not permitted" without a Relay role.'})
def messages_list_unread(channel=None, limit=20, after=None):
    from relay_core import api
    from relay_core.inbox import directory
    page = directory(mode='unread', channel=channel, after=after)
    chats, left = [], limit
    for row in page['items'][:limit]:
        count = min(row.get('unread') or 0, UNREAD_PER_CHAT, left)
        incoming = [brief(item) for item in api.messages(row['name'], limit=count, channel=channel)['items']
                    if item.get('direction') == 'Incoming'] if count else []
        if incoming:
            left -= len(incoming)
            chats.append({'contact': row['name'], **brief(row, ('display_name', 'unread', 'channel', 'business')), 'messages': incoming})
        if left <= 0:
            break
    return {'chats': chats, 'next': page['next']}


@tool('messages_list', READ, obj({'contact': CONTACT, 'before': MESSAGE, 'channel': CURSOR, 'query': {'type': 'string', 'maxLength': 200},
                                  'limit': limit(100, 30)}, ('contact',)), {
    'summary': "Read one chat's messages, oldest first within the page.",
    'use_when': 'you need the conversation history of one contact.',
    'avoid_when': 'you need the messages of a whole business record; use records_messages.',
    'returns': '{items: messages with sent_by and via (mcp, automation, staff, system) on replies, has_more, first, last}. '
               'Page back with before=first.',
    'errors': '"Not permitted" or "Not found" for a chat outside the user\'s scope.'})
def messages_list(contact, before=None, channel=None, query='', limit=30):
    from relay_core.api import messages
    from relay_core.mcp_tools.coordination import with_actors
    page = messages(contact, before=before, channel=channel, limit=limit, query=query)
    return {'items': with_actors([brief(row) for row in page['items']]), 'has_more': page['has_more'], 'first': page['first'],
            'last': page['last']}


@tool('messages_read_one', READ, obj({'message': MESSAGE}, ('message',)), {
    'summary': 'Read one message with its media details, five messages around it and the reply window state.',
    'use_when': 'before you reply to a message, to see its context and if free text is still allowed.',
    'avoid_when': 'you only need a list of messages; use messages_list.',
    'returns': '{message: full message, contact, before: [5], after: [5], reply_window: {open, ...}, claim: the active '
               'claim or null}.',
    'errors': '"Not found" for an unknown id; "Not permitted" outside the user\'s scope.'})
def messages_read_one(message):
    from relay_core import api, messaging
    from relay_core.mcp_tools.coordination import active_claim, public_claim, with_actors
    context = api.message_context(message)
    items = with_actors(context['items'])
    index = next(position for position, row in enumerate(items) if row.get('name') == message)
    return {'message': items[index], 'contact': context['contact'], 'before': [brief(row) for row in items[max(0, index - 5):index]],
            'after': [brief(row) for row in items[index + 1:index + 6]], 'reply_window': messaging.reply_window(message),
            'claim': public_claim(context['contact'], claim) if (claim := active_claim(context['contact'])) else None}


@tool('chat_mark_read', WRITE, obj({'contact': CONTACT, 'read': FLAG}, ('contact', 'read')), {
    'summary': "Mark a chat read (1) or its newest incoming message unread (0) for the current user only.",
    'use_when': 'you handled a chat, or want to leave it for a person to answer.',
    'avoid_when': 'you expect the customer to see blue ticks; this sends no read receipt.',
    'returns': '{contact, unread}.',
    'errors': '"Not permitted" outside the user\'s scope.'})
def chat_mark_read(contact, read):
    from relay_core.message_reads import mark_chat
    return mark_chat(contact=contact, read=read)


@tool('chat_update', WRITE, obj({'contact': CONTACT, 'starred': FLAG, 'folder': {'type': 'string', 'maxLength': 140}},
                                ('contact',)), {
    'summary': "Star or unstar a chat, or move it to one of the user's folders (empty folder removes it).",
    'use_when': 'the user asks to flag or file a chat.',
    'avoid_when': 'you want to change read state; use chat_mark_read.',
    'returns': '{starred, folder, unread, assignment}.',
    'errors': '"folders" feature off; unknown folder; "Not permitted" outside the user\'s scope.'})
def chat_update(contact, starred=None, folder=None):
    from relay_core.inbox import update
    return update(contact, starred=starred, folder=folder)


@tool('chat_comment_add', WRITE, obj({'contact': CONTACT, 'body': {'type': 'string', 'minLength': 1, 'maxLength': 4000},
                                      'request_key': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{16,100}$'},
                                      'messages': {'type': 'array', 'items': MESSAGE, 'maxItems': 20},
                                      'mentions': {'type': 'array', 'items': NAME_FIELD, 'maxItems': 10}},
                                     ('contact', 'body', 'request_key')), {
    'summary': 'Add an internal note to a chat for colleagues. The customer never sees it.',
    'use_when': 'you want to leave a summary, a hand-over or mention a colleague.',
    'avoid_when': 'you want to answer the customer; use chat_send_text.',
    'returns': 'the saved note.',
    'errors': '"Comment request key was already used" when a key is reused for other text; request_key needs 16-100 characters.'})
def chat_comment_add(contact, body, request_key, messages=None, mentions=None):
    from relay_core.collaboration import add
    return add(contact, body, request_key, messages=messages, mentions=mentions)
