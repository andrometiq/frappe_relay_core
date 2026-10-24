"""Disabled, editable starter skills; existing configuration is never overwritten."""
import json
import frappe

LEDGER_TOOL = {'name': 'supplier_ledger', 'method': 'get_list', 'doctype': 'GL Entry',
    'scope_field': 'party', 'fields': ['company', 'posting_date', 'voucher_type', 'voucher_no', 'debit', 'credit', 'remarks']}
INSTRUCTIONS = """Help suppliers with questions about their ledger.
Supplier types we manage: configure this text to describe your supplier groups and what your team handles.
For a ledger doubt, offer an explicit start and end date and ask the supplier to confirm.
Read the ledger only after confirmation of that range. Use the supplier_ledger read tool with a posting_date range.
The tool is restricted to the supplier in this conversation. Never ask for or switch to another supplier's records.
Use only the returned rows and code-computed totals. These are totals for the returned rows, not an opening or closing balance.
If rows were truncated, explain that the totals are partial and offer a narrower date range or a person.
If the request is unclear, outside this skill, data is unavailable, or the supplier asks for a person, hand off to the configured owner.
"""


def install_samples():
    if not all(frappe.db.exists('DocType', name) for name in ('Supplier', 'GL Entry', 'Relay AI Skill')):
        return
    if frappe.db.exists('Relay AI Skill', {'sample_key': 'supplier_ledger'}):
        return
    frappe.get_doc({'doctype': 'Relay AI Skill', 'title': 'Supplier ledger',
        'sample_key': 'supplier_ledger', 'enabled': 0, 'mode': 'Shadow', 'daily_limit': 100,
        'business_doctype': 'Supplier', 'instructions': INSTRUCTIONS,
        'allowed_tools': json.dumps([LEDGER_TOOL])}).insert(ignore_permissions=True)
