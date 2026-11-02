import frappe


def execute():
    """A site that already has an enabled WhatsApp channel was set up by hand, so it skips Get started."""
    if frappe.db.exists('Relay Channel', {'channel': 'WhatsApp', 'enabled': 1}):
        frappe.db.set_single_value('Relay Settings', {'onboarding_completed': 1, 'enrolment_source': 'Manual'})
