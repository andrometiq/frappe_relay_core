import json
import frappe

CAPABILITIES = {'customer_ledger': 'erpnext.customer_ledger', 'supplier_ledger': 'erpnext.supplier_ledger'}


def execute():
    """Skill read rows name a capability. Rows without an installed report could never read; they are dropped."""
    for skill in frappe.get_all('Relay AI Skill', fields=['name', 'allowed_tools']):
        rows = json.loads(skill.allowed_tools or '[]')
        if not isinstance(rows, list) or all(isinstance(row, dict) and set(row) == {'capability'} for row in rows):
            continue
        converted = [{'capability': CAPABILITIES[row['report']]} for row in rows
                     if isinstance(row, dict) and row.get('report') in CAPABILITIES]
        frappe.db.set_value('Relay AI Skill', skill.name, 'allowed_tools', json.dumps(converted), update_modified=False)
