"""Support tickets."""
from relay_core.mcp_tools.inbox import MESSAGE
from relay_core.mcp_tools.registry import CURSOR, NAME_FIELD, READ, WRITE, ToolError, obj, tool

TICKET = {'type': 'string', 'pattern': '^TKT-[0-9]+$', 'description': 'Ticket id, TKT-#####.'}
ACTIONS = ('status', 'assign', 'claim', 'close', 'comment')


@tool('tickets_list', READ, obj({'query': {'type': 'string', 'maxLength': 80}, 'ticket_status': NAME_FIELD, 'mine': {'type': 'integer', 'enum': [0, 1]},
                                 'after': TICKET}), {
    'summary': 'List tickets, newest first, 30 per page.',
    'use_when': 'the user asks for open, own or matching support tickets.',
    'avoid_when': 'you know the ticket id; use tickets_read.',
    'returns': '{items: tickets, next: {after} or null}.',
    'errors': '"Invalid ticket search"; "Not permitted" without a Relay role.'})
def tickets_list(query='', ticket_status=None, mine=None, after=None):
    from relay_core.tickets import directory
    return directory(query=query, ticket_status=ticket_status, mine=mine, after=after)


@tool('tickets_read', READ, obj({'name': TICKET, 'after': MESSAGE}, ('name',)), {
    'summary': 'Read one ticket with its linked messages and a page of its transcript.',
    'use_when': 'you work on a ticket or need its history.',
    'avoid_when': 'you only need the list; use tickets_list.',
    'returns': '{ticket: the ticket, transcript: {items, next}}.',
    'errors': '"Not found" or "Not permitted" for a ticket outside the user\'s scope.'})
def tickets_read(name, after=None):
    from relay_core import tickets
    return {'ticket': tickets.read(name), 'transcript': tickets.transcript(name, after=after)}


@tool('tickets_create', WRITE, obj({'subject': {'type': 'string', 'minLength': 1, 'maxLength': 140},
                                    'messages': {'type': 'array', 'items': MESSAGE, 'minItems': 1, 'maxItems': 50},
                                    'brief': {'type': 'string', 'maxLength': 4000}, 'ticket_type': NAME_FIELD}, ('subject', 'messages')), {
    'summary': 'Create a ticket from 1-50 readable messages of one business scope.',
    'use_when': 'a customer request needs follow-up by the team.',
    'avoid_when': 'a ticket for these messages exists; check tickets_list.',
    'returns': '{name, ticket_status}.',
    'errors': '"Messages must be a list of 1-50 references"; messages of different business records.'})
def tickets_create(subject, messages, brief='', ticket_type=None):
    from relay_core.tickets import create
    return create(subject, messages, brief=brief, ticket_type=ticket_type)


@tool('tickets_update', WRITE, obj({'name': TICKET, 'action': {'type': 'string', 'enum': list(ACTIONS)}, 'value': CURSOR | {'maxLength': 4000}},
                                   ('name', 'action')), {
    'summary': 'Change a ticket: set status, assign to a user, claim it from AI, close it, or add an internal comment.',
    'use_when': 'the user asks to move, hand over, take or close a ticket.',
    'avoid_when': 'you want to message the customer; use chat_send_text.',
    'returns': 'the updated ticket fields.',
    'errors': 'value is required for status (a status name), assign (a user email) and comment (text); '
              '"Not permitted" when assigning without the manager role.'})
def tickets_update(name, action, value=None):
    from relay_core import ticket_tags, tickets
    if action in ('status', 'comment') and not value:
        raise ToolError(f'action {action} needs value')
    handlers = {'status': lambda: tickets.update_status(name, value), 'assign': lambda: tickets.assign(name, value or ''),
                'claim': lambda: tickets.claim(name), 'close': lambda: tickets.close_and_release(name),
                'comment': lambda: ticket_tags.add_comment(name, value)}
    return handlers[action]()
