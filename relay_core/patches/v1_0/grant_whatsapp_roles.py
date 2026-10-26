import frappe
from relay_core.permissions import MANAGER, USER, WA_MANAGER, WA_USER, install_roles

ALIASES = {MANAGER: WA_MANAGER, USER: WA_USER}


def execute():
    """Give holders of the old Relay roles the matching WhatsApp role; the old roles stay."""
    install_roles()
    for old, new in ALIASES.items():
        holders = set(frappe.get_all('Has Role', filters={'parenttype': 'User', 'role': old}, pluck='parent'))
        holders -= set(frappe.get_all('Has Role', filters={'parenttype': 'User', 'role': new}, pluck='parent'))
        for user in sorted(holders):
            frappe.get_doc({'doctype': 'Has Role', 'parent': user, 'parenttype': 'User',
                            'parentfield': 'roles', 'role': new}).db_insert()
            frappe.clear_cache(user=user)
