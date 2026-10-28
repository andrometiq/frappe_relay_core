import frappe


def execute():
    """Flows now sit behind Relay Settings > Enable flows (off by default). Keep sites that already run a flow working."""
    if frappe.db.table_exists('Relay Flow') and frappe.db.exists('Relay Flow', {'enabled': 1}):
        frappe.db.set_single_value('Relay Settings', 'enable_flows', 1)
