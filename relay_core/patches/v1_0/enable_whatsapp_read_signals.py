import frappe

FIELDS = ('send_whatsapp_read_receipts', 'send_whatsapp_typing')


def execute():
    """Saved settings have no row for new Check fields; store their default of on."""
    frappe.reload_doc('relay_core', 'doctype', 'relay_settings')
    saved = set(frappe.db.sql_list("select field from tabSingles where doctype='Relay Settings'"))
    if not saved:
        return  # Unsaved settings read the field defaults.
    for field in FIELDS:
        if field not in saved:
            frappe.db.set_single_value('Relay Settings', field, 1)
