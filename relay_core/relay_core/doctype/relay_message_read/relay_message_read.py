import frappe
from frappe.model.document import Document

class RelayMessageRead(Document):
    def validate(self):
        if not getattr(frappe.flags, 'relay_read_write', False):
            frappe.throw('Message reads are maintained by the inbox service', frappe.PermissionError)
