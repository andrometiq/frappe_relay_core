import json

import frappe


def execute():
    """The create_draft hook became the erpnext.payment_entry_draft capability; saved skills name the pack."""
    for skill in frappe.get_all('Relay AI Skill', filters={'allowed_actions': ['like', '%"create_draft"%']},
                                fields=['name', 'allowed_actions']):
        rows = json.loads(skill.allowed_actions)
        for row in rows:
            if isinstance(row, dict) and row.get('action') == 'create_draft':
                row['action'] = 'erpnext.payment_entry_draft'
        frappe.db.set_value('Relay AI Skill', skill.name, 'allowed_actions', json.dumps(rows), update_modified=False)
