"""Tools for several agents on one inbox: claims, the change cursor and the activity log."""
import json

import frappe

from relay_core.mcp_tools import coordination
from relay_core.mcp_tools.inbox import CONTACT, MESSAGE, brief
from relay_core.mcp_tools.registry import NAME_FIELD, READ, WRITE, ToolError, limit, obj, tool

EVENT_FIELDS = ['name', 'relay_contact', 'direction', 'content', 'message_type', 'status', 'creation', 'channel',
                'business_doctype', 'business_name']


@tool('chat_claim', WRITE, obj({'contact': CONTACT, 'minutes': {'type': 'integer', 'minimum': 1, 'maximum': 30}},
                               ('contact', 'minutes')), {
    'summary': 'Claim a chat for up to 30 minutes so other MCP agents cannot send to it, and pause the Relay automation and AI.',
    'use_when': 'before you read and answer a chat, in a loop shared with other agents. Claim again to extend.',
    'avoid_when': 'you only read; reads never need a claim.',
    'returns': '{contact, claimed_by, until (UTC), ai_paused}. ai_paused is false when your user cannot pause automation '
               '(it needs the Relay Communication Manager role).',
    'errors': '"Chat claimed by <user> until <time>" when another agent holds it.'})
def chat_claim(contact, minutes):
    return coordination.claim_chat(contact, minutes)


@tool('chat_release', WRITE, obj({'contact': CONTACT}, ('contact',)), {
    'summary': 'Release your claim on a chat and resume the automation your claim paused.',
    'use_when': 'you finished the chat. Claims also end by themselves at their until time.',
    'avoid_when': 'another agent holds the claim.',
    'returns': '{contact, released}.',
    'errors': '"Only <user> can release this claim".'})
def chat_release(contact):
    return coordination.release_chat(contact)


@tool('changes_since', READ, obj({'cursor': MESSAGE, 'limit': limit(100, 50)}), {
    'summary': 'Read what happened in all your chats after your own cursor: new incoming messages and replies by anyone '
               '(staff, Relay automation and AI, other MCP agents), plus the active claims.',
    'use_when': 'at the start of every poll. Keep the returned cursor and pass it next time; without a cursor you get '
                'the current cursor and no events.',
    'avoid_when': 'you need a full chat history; use messages_list.',
    'returns': '{events: [{type: inbound|reply, name, contact, content, status, creation, sent_by, via, client}], '
               'cursor, has_more, claims: [{contact, claimed_by, until}]}. Delivery status changes of older messages are '
               'not events; use send_status.',
    'errors': '"Not permitted" without a Relay role.'})
def changes_since(cursor=None, limit=50):
    if not cursor:
        head = frappe.get_list('Relay Message', fields=['name'], order_by='name desc', limit_page_length=1, pluck='name')
        return {'events': [], 'cursor': head[0] if head else 'RELAY-MSG-0000000000', 'has_more': False, 'claims': visible_claims()}
    rows = frappe.get_list('Relay Message', filters={'name': ['>', cursor]}, fields=EVENT_FIELDS, order_by='name asc',
                           limit_page_length=limit + 1)
    page = coordination.with_actors(rows[:limit])
    events = [dict(brief(row, ('name', 'content', 'message_type', 'status', 'creation', 'channel', 'business_doctype',
                                'business_name', 'sent_by', 'via', 'client')),
                   type='inbound' if row['direction'] == 'Incoming' else 'reply', contact=row['relay_contact']) for row in page]
    return {'events': events, 'cursor': page[-1]['name'] if page else cursor, 'has_more': len(rows) > limit,
            'claims': visible_claims()}


def visible_claims():
    from relay_core.permissions import readable_contact
    rows = []
    for contact, claim in coordination.claims().items():
        try:
            readable_contact(contact)
        except (frappe.PermissionError, frappe.DoesNotExistError):
            continue
        rows.append(coordination.public_claim(contact, claim))
    return rows


@tool('activity_log', READ, obj({'user': NAME_FIELD, 'contact': CONTACT, 'limit': limit(100, 50)}), {
    'summary': 'Read the audit log of MCP writes and sends: which agent did what, in which chat, and the reply time.',
    'use_when': 'the user asks who answered, how fast, or what an agent did.',
    'avoid_when': 'you need who sent one message; messages_list shows sent_by and via on each reply.',
    'returns': '{items: [{creation, user, tool, contact, action, client, request_key, message, response_seconds}]}. '
               'Managers see every agent; other users see their own rows.',
    'errors': '"Not permitted" for another user\'s rows without the manager role.'})
def activity_log(user=None, contact=None, limit=50):
    from relay_core.permissions import can_manage, readable_contact
    if user and user != frappe.session.user and not can_manage():
        raise frappe.PermissionError('Only communication managers can read other agents\' activity')
    filters = {'subject': ['like', coordination.SUBJECT + '%'], 'user': user or (None if can_manage() else frappe.session.user)}
    if contact:
        readable_contact(contact)
        filters.update(reference_doctype='Relay Contact', reference_name=contact)
    rows = frappe.get_all('Activity Log', filters={key: value for key, value in filters.items() if value},
                          fields=['creation', 'user', 'subject', 'reference_name', 'link_name', 'content'],
                          order_by='creation desc', limit_page_length=limit)
    return {'items': [log_row(row) for row in rows]}


def log_row(row):
    try:
        details = json.loads(row.content or '{}')
    except ValueError:
        raise ToolError('An activity row is not readable') from None
    return {'creation': row.creation, 'user': row.user, 'tool': row.subject[len(coordination.SUBJECT):],
            'contact': row.reference_name, 'action': row.link_name, **{key: value for key, value in details.items() if key != 'tool'}}
