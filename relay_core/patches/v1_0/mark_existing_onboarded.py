import frappe


def execute():
    """A site that already has an enabled channel of any kind was set up by hand, so it skips Get started."""
    if frappe.db.exists('Relay Channel', {'enabled': 1}):
        frappe.db.set_single_value('Relay Settings', {'onboarding_completed': 1, 'enrolment_source': 'Manual'})
