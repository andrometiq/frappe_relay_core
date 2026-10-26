import frappe
from relay_core.automation.documents import InternalRecord


class RelayWhatsAppBillingMonth(InternalRecord):
    pass


def on_doctype_update():
    frappe.db.add_unique('Relay WhatsApp Billing Month', ['account', 'period', 'category', 'pricing_type'],
                         'relay_billing_month_key')
