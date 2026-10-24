"""Reviewed Core actions. The shared executor supplies identity and journals writes."""
import frappe


PAYMENT_FIELDS = {
    'payment_type': {'type': 'string', 'enum': ['Pay', 'Receive']},
    'posting_date': {'type': 'string', 'minLength': 10, 'maxLength': 10},
    'paid_amount': {'type': 'number', 'minimum': 0.01},
    'received_amount': {'type': 'number', 'minimum': 0.01},
    'paid_from': {'type': 'string', 'minLength': 1, 'maxLength': 140},
    'paid_to': {'type': 'string', 'minLength': 1, 'maxLength': 140},
    'source_exchange_rate': {'type': 'number', 'minimum': 0.000001},
    'target_exchange_rate': {'type': 'number', 'minimum': 0.000001},
    'reference_no': {'type': 'string', 'maxLength': 140},
    'reference_date': {'type': 'string', 'minLength': 10, 'maxLength': 10},
    'remarks': {'type': 'string', 'maxLength': 1000},
}
PAYMENT_SCHEMA = dict(type='object', additionalProperties=False, properties=PAYMENT_FIELDS,
    required=['payment_type', 'posting_date', 'paid_amount', 'received_amount', 'paid_from', 'paid_to'])

CREATE_DRAFT = dict(label='Create draft', method='relay_core.ai.actions.create_draft',
    contexts=['ai'], replay_safe=True, ai_safe=True, effect='create_draft', approval_policy='None',
    permissions={'Payment Entry': 'create'}, parameters=PAYMENT_SCHEMA,
    scope_fields={'Payment Entry': {'company': 'company', 'business': 'party'}},
    targets={'Payment Entry': PAYMENT_SCHEMA}, output=dict(type='object', additionalProperties=False,
        properties={'doctype': {'type': 'string'}, 'name': {'type': 'string'}}, required=['doctype', 'name']))
REPLY = dict(label='Reply', method='relay_core.ai.actions.reply', contexts=['ai'], replay_safe=True, ai_safe=True,
    effect='reply', approval_policy='None', permissions={'Relay Message': 'read'},
    parameters=dict(type='object', additionalProperties=False,
        properties={'text': {'type': 'string', 'minLength': 1, 'maxLength': 2000}}, required=['text']),
    output=dict(type='object', additionalProperties=False,
        properties={'reply': {'type': 'string', 'minLength': 1, 'maxLength': 2000}}, required=['reply']))


def create_draft(*, action_input, idempotency_key, automation_run, ticket, execution_context, declaration):
    """Insert normally as the effective user; never bypass ERP validation or submit."""
    from relay_core.flows.action_contracts import ai_inputs
    from relay_core.flows.actions import definitions
    definition = definitions()[declaration['action']]
    values = ai_inputs(action_input, definition, declaration)
    doc = frappe.new_doc(declaration['doctype'])
    doc.update(values)
    # Scope fields are reviewed in the registration, never model-selected.
    mapping = definition['scope_fields'][doc.doctype]
    company, business = (doc.meta.get_field(mapping[key]) for key in ('company', 'business'))
    if (not company or company.fieldtype != 'Link' or company.options != 'Company' or not business
            or not (business.fieldtype == 'Link' and business.options == execution_context['business'][0]
                or business.fieldtype == 'Dynamic Link' and doc.meta.get_field(business.options).options == 'DocType')):
        raise ValueError('Draft requires declared company and business fields')
    doc.set(company.fieldname, execution_context['company'])
    if business.fieldtype == 'Dynamic Link':
        doc.set(business.options, execution_context['business'][0])
    doc.set(business.fieldname, execution_context['business'][1])
    doc.docstatus = 0
    doc.check_permission('create')
    levels = doc.meta.get_permlevel_access('write', user=frappe.session.user)
    if any((doc.meta.get_field(key).permlevel or 0) not in levels for key in values):
        raise frappe.PermissionError('Draft field permission denied')
    doc.insert()
    if doc.docstatus != 0:
        raise ValueError('Only draft documents may be created')
    from relay_core.realtime import changed
    changed(frappe.get_doc('Relay Ticket', ticket))
    return dict(doctype=doc.doctype, name=doc.name)


def reply(*, action_input, idempotency_key, automation_run, ticket, execution_context, declaration):
    """Journal the reply intent; the worker delivers it before executing the next step."""
    if not action_input['text'].strip():
        raise ValueError('An acknowledgement must contain text')
    return {'reply': action_input['text']}
