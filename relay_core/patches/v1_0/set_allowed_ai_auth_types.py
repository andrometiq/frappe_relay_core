import frappe


def execute():
    """Relay AI uses only ChatGPT Login accounts until an owner allows another auth type."""
    if not frappe.db.get_single_value('Relay Settings', 'allowed_ai_auth_types'):
        frappe.db.set_single_value('Relay Settings', 'allowed_ai_auth_types', 'ChatGPT Login')
