import frappe
from frappe.model.document import Document

class RelayDeliveryReceipt(Document):
    def validate(self):
        if not getattr(frappe.flags, 'relay_receipt_write', False):
            frappe.throw('Delivery receipts are maintained by the message service', frappe.PermissionError)
