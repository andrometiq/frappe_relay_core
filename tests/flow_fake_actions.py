"""Stand-ins for the Andrometiq /help business actions, registered only inside flow site tests."""
CALLS = []


def record(name, action_input, idempotency_key):
    CALLS.append((name, action_input, idempotency_key))


def resolve_customer(*, action_input, idempotency_key, **context):
    record('resolve_customer', action_input, idempotency_key)
    return {'authorized': True, 'contact_name': 'Asha', 'message': ''}


def create_ticket(*, action_input, idempotency_key, **context):
    record('create_ticket', action_input, idempotency_key)
    return {'created': True, 'ticket': '0043'}


def lookup_ticket(*, action_input, idempotency_key, **context):
    record('lookup_ticket', action_input, idempotency_key)
    return {'ticket': action_input['ticket'], 'editable': True, 'message': 'Ticket #' + action_input['ticket'] + ' is open.'}


def append_ticket_content(*, action_input, idempotency_key, **context):
    record('append_ticket_content', action_input, idempotency_key)
    return {'ticket': action_input['ticket'], 'kind': action_input['content']['type']}


def finalize_ticket(*, action_input, idempotency_key, **context):
    record('finalize_ticket', action_input, idempotency_key)
    return {'ticket': action_input['ticket'], 'message': 'Ticket #' + action_input['ticket'] + ' is saved.'}


def definitions(hook='relay_flow_actions', *, context=None):
    loose = {'type': 'object', 'properties': {}, 'additionalProperties': {'type': 'json'}}
    names = {'resolve_customer': 'resolve_customer', 'create_ticket': 'create_ticket', 'lookup_ticket': 'lookup_ticket',
             'append_ticket_content': 'append_ticket_content', 'finalize_ticket': 'finalize_ticket'}
    return {'custom_andrometiq.support.' + key: {'key': 'custom_andrometiq.support.' + key, 'label': key,
            'method': 'flow_fake_actions.' + method, 'replay_safe': True, 'parameters': loose}
            for key, method in names.items()}
