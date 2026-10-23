import frappe
from frappe.model.document import Document

class RelayInternalComment(Document):
    def validate(self):
        if not getattr(frappe.flags, "relay_collaboration_write", False):
            frappe.throw("Use the conversation comments service", frappe.PermissionError)
