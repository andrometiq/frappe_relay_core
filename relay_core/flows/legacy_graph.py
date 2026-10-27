"""Convert supported WhatsApp Core flow graphs into reviewable Relay steps; never activates them."""
import re
from copy import deepcopy
from relay_core.flows.contracts import LAST_INPUT, definition, text_value

# Old answer and action references become Relay paths: answers.x -> x, actions.ticket.number -> ticket.number.
LEGACY_REFERENCE = re.compile(r'\{\{\s*([^{}]*?)\s*\}\}')
INPUT_TYPES = {'radio': 'choice', 'select': 'choice', 'multi_select': 'multi_choice', 'attachment': 'content'}
OPERATORS = {'eq': 'eq', 'ne': 'ne', 'contains': 'contains', 'gt': 'gt', 'gte': 'gte', 'lt': 'lt', 'lte': 'lte'}
MEDIA = ['audio', 'document', 'image', 'sticker', 'video']
SUPPORTED = {
    'start': {'label'},
    'ask_input': {'label', 'message', 'answer_key', 'input_type', 'options', 'minimum', 'maximum', 'integer_only',
                  'optional', 'required', 'button_label', 'min_length', 'max_length', 'validation_message',
                  'accepted_media_types'},
    'condition': {'label'},
    'action': {'label', 'action', 'input', 'output_key'},
    'send_message': {'label', 'message'},
    'human_handoff': {'label', 'message', 'reason'},
    'end': {'label', 'message'},
}


def path(reference):
    if reference == 'last_input.value':
        return LAST_INPUT
    for prefix in ('answers.', 'actions.'):
        if isinstance(reference, str) and reference.startswith(prefix):
            return reference.removeprefix(prefix)
    raise ValueError('Only collected answers and action results can be migrated: ' + str(reference))


def answer_ref(value):
    if isinstance(value, dict):
        if set(value) == {'var'}:
            return {'var': path(value['var'])}
        return {k: answer_ref(v) for k, v in value.items()}
    if isinstance(value, list):
        return [answer_ref(v) for v in value]
    return value


def text(value):
    if not isinstance(value, str):
        return ''
    return LEGACY_REFERENCE.sub(lambda match: '{{' + path(match[1]) + '}}', value)


def media_types(config, input_type):
    accepted = config.get('accepted_media_types') or MEDIA
    if not isinstance(accepted, list) or set(accepted) - set(MEDIA):
        raise ValueError('Unsupported legacy media types')
    accepted = list(accepted) + (['voice'] if 'audio' in accepted else [])
    # A content answer also takes text, a location or a contact card; an attachment takes media only.
    return accepted + ['text', 'location', 'contacts'] if input_type == 'content' else accepted


def input_step(row, config):
    input_type = INPUT_TYPES.get(config.get('input_type'), config.get('input_type'))
    row.update(kind='input', text=text(config.get('message', '')), variable=config.get('answer_key'), input_type=input_type)
    if 'required' in config:
        if type(config['required']) is not bool:
            raise ValueError('Legacy required flag must be boolean')
        row['optional'] = not config['required']
    for field in ('minimum', 'maximum', 'integer_only', 'optional', 'min_length', 'max_length'):
        if field in config:
            row[field] = config[field]
    if config.get('validation_message'):
        row['error_text'] = config['validation_message']
    if config.get('button_label'):
        row['button'] = config['button_label'][:20]
    if input_type in ('choice', 'multi_choice'):
        row['choices'] = deepcopy(config.get('options'))
    if input_type == 'content':
        row['accept'] = media_types(config, config.get('input_type'))


def action_step(row, config):
    values = answer_ref(config.get('input', {}))
    action = config.get('action')
    if not isinstance(values, dict):
        raise ValueError('Legacy action input must be an object')
    if action == 'topic.upsert':
        if set(values) - {'topic_key', 'title', 'summary', 'category', 'status', 'confidence'}:
            raise ValueError('Unsupported legacy topic action fields')
        if values.get('confidence', 100) != 100:
            raise ValueError('Non-default topic confidence needs manual conversion')
        row.update(kind='topic', title=values.get('title', ''), text=values.get('summary') or values.get('title', ''),
                   category=values.get('category', ''), status=values.get('status', 'Open'))
        return
    row.update(kind='action', text='', action=action, arguments=values)
    if config.get('output_key'):
        row['variable'] = config['output_key']


def condition_steps(key, routes, nodes):
    defaults = [e for e in routes if e.get('default')]
    tests = [e for e in routes if not e.get('default')]
    if len(defaults) != 1 or not tests:
        raise ValueError('Legacy conditions need tests and exactly one default route')
    steps = {}
    for index, edge in enumerate(tests):
        test = edge.get('when', {})
        reference = answer_ref(test.get('left'))
        right = test.get('right')
        if (test.get('op') not in OPERATORS or not isinstance(reference, dict) or set(reference) != {'var'}
                or type(right) not in (str, bool, int, float)):
            raise ValueError('Only simple comparisons on answers and action results are supported')
        ident = key if index == 0 else key + '_test_' + str(index)
        if ident != key and ident in nodes:
            raise ValueError('Generated condition ID conflicts with source node')
        otherwise = key + '_test_' + str(index + 1) if index + 1 < len(tests) else defaults[0]['target']
        steps[ident] = {'id': ident, 'kind': 'condition', 'text': '', 'variable': reference['var'],
                        'operator': OPERATORS[test['op']], 'value': text_value(right),
                        'then': edge['target'], 'otherwise': otherwise}
    return steps


def convert(graph):
    if not isinstance(graph, dict) or graph.get('schema_version') != 1:
        raise ValueError('Choose a version 1 legacy graph')
    raw = graph.get('nodes', []); edges = graph.get('edges', [])
    if not isinstance(raw, list) or not 1 <= len(raw) <= 100 or not isinstance(edges, list) or len(edges) > 300:
        raise ValueError('Legacy graph exceeds conversion limits')
    nodes = {}; out = {}
    for node in raw:
        if not isinstance(node, dict) or not isinstance(node.get('id'), str) or node['id'] in nodes:
            raise ValueError('Legacy graph has invalid or duplicate node IDs')
        nodes[node['id']] = node; out[node['id']] = []
    for edge in edges:
        if not isinstance(edge, dict) or edge.get('source') not in nodes or edge.get('target') not in nodes:
            raise ValueError('Legacy edge points to an unknown node')
        out[edge['source']].append(edge)
    starts = [n['id'] for n in raw if n.get('type') == 'start']
    if len(starts) != 1 or len(out[starts[0]]) != 1:
        raise ValueError('Legacy graph needs one start with one successor')
    converted = {}; links = {}
    for key, node in nodes.items():
        config = node.get('config') or {}; kind = node.get('type'); routes = out[key]
        if kind not in SUPPORTED or not isinstance(config, dict) or set(config) - SUPPORTED[kind]:
            raise ValueError('Unsupported legacy configuration on ' + key)
        if kind == 'start':
            continue
        if kind == 'condition':
            steps = condition_steps(key, routes, nodes)
            converted.update(steps)
            links.update({ident: [step['then'], step['otherwise']] for ident, step in steps.items()})
            continue
        row = {'id': key}
        if kind == 'ask_input':
            input_step(row, config)
        elif kind == 'action':
            action_step(row, config)
        elif kind == 'send_message':
            row.update(kind='reply', text=text(config.get('message', '')))
        elif kind == 'human_handoff':
            row.update(kind='handoff', text=text(config.get('message') or config.get('reason') or 'A person will reply soon.'))
        else:
            row.update(kind='end', text=text(config.get('message', '')))
        if kind in ('end', 'human_handoff'):
            if routes:
                raise ValueError('Terminal legacy node has outgoing edges')
            links[key] = []
        else:
            if len(routes) != 1 or routes[0].get('when') or routes[0].get('default'):
                raise ValueError('Non-branch step needs one unconditional successor')
            row['next'] = routes[0]['target']; links[key] = [row['next']]
        converted[key] = row
    for edge in edges:
        limit = edge.get('max_traversals')
        if limit is not None and edge['target'] in converted:
            if type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError('Legacy loop limit must be 1–100')
            target = converted[edge['target']]
            target['max_visits'] = min(target.get('max_visits', limit), limit)
    first = out[starts[0]][0]['target']
    if first not in converted:
        raise ValueError('Legacy graph loops into its start')
    # Breadth-first from the start keeps related steps together; explicit next/then links carry the routing.
    ordered = []; queue = [first]; placed = {first}
    while queue:
        key = queue.pop(0); ordered.append(converted[key])
        for target in links[key]:
            if target not in converted:
                raise ValueError('Legacy graph loops into its start')
            if target not in placed:
                placed.add(target); queue.append(target)
    if len(ordered) != len(converted):
        raise ValueError('Legacy graph has disconnected steps')
    return {'nodes': definition(ordered), 'triggers': deepcopy(graph.get('triggers', [])),
            'requires_review': True, 'enabled': False}
