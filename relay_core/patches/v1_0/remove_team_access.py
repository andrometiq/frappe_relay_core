import frappe


def execute():
    """Drop the unused Relay Team Access child table."""
    frappe.delete_doc('DocType', 'Relay Team Access', ignore_missing=True, force=True)
