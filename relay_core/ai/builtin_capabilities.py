"""Core capability packs. No model SQL, Python, URLs or arbitrary methods."""
from relay_core.ai.actions import DRAFT_OUTPUT, PAYMENT_SCHEMA

LEDGER_FIELDS = [
    {'name': 'name', 'model': True, 'customer': False},
    {'name': 'company', 'model': True, 'customer': False},
    *({'name': name, 'model': True, 'customer': True}
      for name in ('posting_date', 'voucher_type', 'voucher_no', 'debit', 'credit')),
]


def ledger(party_type: str, render: str) -> dict:
    return {
        'kind': 'read', 'version': 1, 'label': party_type + ' ledger',
        'business_doctype': party_type, 'doctype': 'GL Entry', 'operation': 'get_list',
        'scope': {'business_field': 'party', 'company': {'kind': 'company_field', 'field': 'company'},
                  'fixed': {'party_type': party_type, 'is_cancelled': 0}},
        'fields': LEDGER_FIELDS,
        'filters': {'posting_date': {'type': 'date', 'operators': ['between'], 'required': True}},
        'order_by': 'name asc', 'limit': 20,
        'empty_result': 'handoff', 'confirmation': 'Always',
        'render': render,
        'data_notes': 'Totals cover returned rows only, never an opening or closing balance.',
    }


CAPABILITIES = {
    'erpnext.customer_ledger': ledger('Customer', 'relay_core.ai.ledger.render'),
    'erpnext.supplier_ledger': ledger('Supplier', 'relay_core.ai.ledger.supplier'),
    'erpnext.payment_entry_draft': {
        'kind': 'action', 'version': 1, 'label': 'Payment Entry draft', 'effect': 'create_draft',
        'method': 'relay_core.ai.actions.create_draft', 'approval_policy': 'Required',
        'permissions': {'Payment Entry': 'create'}, 'parameters': PAYMENT_SCHEMA,
        'targets': {'Payment Entry': PAYMENT_SCHEMA},
        'scope_fields': {'Payment Entry': {'company': 'company', 'business': 'party'}}, 'output': DRAFT_OUTPUT,
        'link_checks': {'Payment Entry': ['paid_from', 'paid_to']},
    },
}
