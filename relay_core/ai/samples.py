"""Editable starter skills; upgrade known defaults without replacing custom tools."""
import json
import frappe

LEDGER_TOOL = {'name': 'supplier_ledger', 'method': 'get_list', 'doctype': 'GL Entry',
    'scope_field': 'party', 'fields': ['company', 'posting_date', 'voucher_type', 'voucher_no', 'debit', 'credit', 'remarks']}
# The shipped contract before ledger totals required company metadata.
LEGACY_LEDGER_TOOL = {**LEDGER_TOOL,
    'fields': ['posting_date', 'voucher_type', 'voucher_no', 'debit', 'credit', 'remarks']}
TARGET = "Help a supplier understand their ledger entries and totals for a confirmed date range."
REPLY_STYLE = "Use plain language, state the date range and company, and explain partial results."
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
    name = frappe.db.exists('Relay AI Skill', {'sample_key': 'supplier_ledger'})
    if name:
        skill = frappe.get_doc('Relay AI Skill', name, for_update=True)
        try:
            tools = json.loads(skill.allowed_tools or '[]')
        except (TypeError, ValueError):
            return
        changed = False
        if (skill.business_doctype == 'Supplier' and skill.instructions == INSTRUCTIONS
                and tools == [LEGACY_LEDGER_TOOL]):
            skill.allowed_tools = json.dumps([LEDGER_TOOL])
            # Old samples have no authenticated identity/company contract. Keep
            # the editable draft, but require explicit owner configuration to enable it.
            skill.enabled = 0
            changed = True
        if (skill.business_doctype == 'Supplier' and skill.instructions == INSTRUCTIONS
                and tools in ([LEDGER_TOOL], [LEGACY_LEDGER_TOOL])
                and skill.get('execution_policy') == 'Execute'
                and skill.get('allowed_actions') in (None, '', '[]')):
            skill.allowed_actions = '[{"action":"reply"}]'
            skill.enabled = 0
            changed = True
        if changed:
            skill.save(ignore_permissions=True)
        return
    frappe.get_doc({'doctype': 'Relay AI Skill', 'title': 'Supplier ledger',
        'sample_key': 'supplier_ledger', 'enabled': 0, 'mode': 'Shadow', 'daily_limit': 100,
        'business_doctype': 'Supplier', 'target': TARGET, 'instructions': INSTRUCTIONS,
        'reply_style': REPLY_STYLE, 'search_confirmation': 'Always',
        'execution_policy': 'Execute', 'allowed_actions': '[{"action":"reply"}]',
        'allowed_tools': json.dumps([LEDGER_TOOL])}).insert(ignore_permissions=True)
