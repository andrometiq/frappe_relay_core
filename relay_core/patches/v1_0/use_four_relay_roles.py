import frappe
from relay_core.permissions import MANAGER, TEAM_USER, USER, install_roles

# Multi-Channel User let a user see other teams' conversations; Team User sees every team.
ROLE_MAP = {'WhatsApp User': USER, 'WhatsApp Manager': MANAGER, 'WhatsApp Multi-Channel User': TEAM_USER}


def execute():
    """Give holders of the frappe_whatsapp_core roles the matching Relay role. No role is removed."""
    install_roles()
    for old, new in ROLE_MAP.items():
        holders = set(frappe.get_all('Has Role', filters={'parenttype': 'User', 'role': old}, pluck='parent'))
        holders -= set(frappe.get_all('Has Role', filters={'parenttype': 'User', 'role': new}, pluck='parent'))
        for user in sorted(holders):
            frappe.get_doc({'doctype': 'Has Role', 'parent': user, 'parenttype': 'User',
                            'parentfield': 'roles', 'role': new}).db_insert()
            frappe.clear_cache(user=user)
