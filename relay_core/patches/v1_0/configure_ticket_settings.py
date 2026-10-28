import frappe

from relay_core import ticket_settings


def execute():
    """Create the default ticket settings, keep the old category names as categories, and give each ticket its status.

    Safe to run again: it only creates what is missing and fills empty `ticket_status` values."""
    if not frappe.db.table_exists('Relay Ticket Status'):
        return
    ticket_settings.seed_defaults(extra_categories=ticket_settings.LEGACY_CATEGORIES)
    used = frappe.get_all('Relay Ticket', filters={'category': ['is', 'set']}, pluck='category', distinct=True)
    for label in used:
        if not frappe.db.exists('Relay Ticket Category', label):
            frappe.get_doc({'doctype': 'Relay Ticket Category', 'label': label, 'enabled': 1, 'colour': 'gray',
                            'sort_order': 50}).insert(ignore_permissions=True)
    for state in ticket_settings.STATES:
        status = ticket_settings.default_status(state)
        if status:
            frappe.db.sql("update `tabRelay Ticket` set ticket_status = %s where status = %s "
                          "and (ticket_status is null or ticket_status = '')", (status, state))
