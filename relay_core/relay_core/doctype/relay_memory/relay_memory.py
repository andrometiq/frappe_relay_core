import frappe

from relay_core.automation.documents import InternalRecord


class RelayMemory(InternalRecord):
    pass


def on_doctype_update():
    frappe.db.add_unique('Relay Memory', ['business_doctype', 'business_name', 'address', 'company', 'provider',
                                          'level', 'period_start'], 'relay_memory_key')
