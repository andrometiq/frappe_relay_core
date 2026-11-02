"""Conversation flows (slash-command workflows). Communication managers only."""
from relay_core.mcp_tools.registry import CONFIRM, CURSOR, NAME_FIELD, READ, SEND, WRITE, obj, tool

ACTIONS = ('publish', 'enable', 'disable')


@tool('flows_list', READ, obj({'query': {'type': 'string', 'maxLength': 140}, 'after': CURSOR}), {
    'summary': 'List saved conversation flows.',
    'use_when': 'finding a flow to read, change or publish.',
    'avoid_when': 'the flows feature is off (settings_read).',
    'returns': '{items: flows, next}.',
    'errors': '"Not permitted" for non-managers; flows feature off.'})
def flows_list(query='', after=None):
    from relay_core.flows import service
    return service.directory(after=after, query=query)


@tool('flows_read', READ, obj({'name': NAME_FIELD}, ('name',)), {
    'summary': 'Read one flow definition and its published version.',
    'use_when': 'before you change or publish a flow.',
    'avoid_when': 'you need its runs; use flows_runs.',
    'returns': 'the flow definition.',
    'errors': '"Not found"; "Not permitted" for non-managers.'})
def flows_read(name):
    from relay_core.flows import service
    return service.read(name)


@tool('flows_runs', READ, obj({'flow': NAME_FIELD, 'after': CURSOR}, ('flow',)), {
    'summary': 'Read pages of runs of one flow.',
    'use_when': 'checking whether a flow works for customers.',
    'avoid_when': 'you need the definition; use flows_read.',
    'returns': '{items: runs, next}.',
    'errors': '"Not found"; "Not permitted".'})
def flows_runs(flow, after=None):
    from relay_core.flows import service
    return service.runs(flow, after=after)


@tool('flows_validate', READ, obj({'values': {'type': 'object'}, 'name': NAME_FIELD}, ('values',)), {
    'summary': 'Check a flow draft without saving it.',
    'use_when': 'before flows_save.',
    'avoid_when': 'the draft is already saved and unchanged.',
    'returns': '{valid, problems}.',
    'errors': '"Invalid flow fields".'})
def flows_validate(values, name=None):
    from relay_core.flows import service
    return service.validate_draft(values, name=name)


@tool('flows_save', WRITE, obj({'values': {'type': 'object'}, 'name': NAME_FIELD}, ('values',)), {
    'summary': 'Save a flow draft. Customers see nothing until it is published and enabled.',
    'use_when': 'flows_validate passed and the user wants it kept.',
    'avoid_when': 'you want it live; then also use flows_publish.',
    'returns': 'the saved flow.',
    'errors': '"Invalid flow fields"; "Not permitted".'})
def flows_save(values, name=None):
    from relay_core.flows import service
    return service.save(values, name=name)


@tool('flows_publish', SEND, obj({'name': NAME_FIELD, 'action': {'type': 'string', 'enum': list(ACTIONS)}, 'confirm': CONFIRM},
                                 ('name', 'action', 'confirm')), {
    'summary': 'Publish a saved flow, or enable or disable its published version. A live flow answers customers.',
    'use_when': 'the user explicitly asked to make the flow live or to stop it.',
    'avoid_when': 'the draft was not validated.',
    'returns': 'the flow state.',
    'errors': '"arguments.confirm must be true"; "Published workflow version is invalid".'})
def flows_publish(name, action, confirm):
    from relay_core.flows import service
    if action == 'publish':
        return service.publish(name)
    return service.set_enabled(name, int(action == 'enable'))
