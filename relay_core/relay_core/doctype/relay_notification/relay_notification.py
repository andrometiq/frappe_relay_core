import frappe
from frappe.model.document import Document


class RelayNotification(Document):
    def validate(self):
        if not getattr(frappe.flags,"relay_collaboration_write",False):
            frappe.throw("Notifications are maintained by the collaboration service",frappe.PermissionError)
