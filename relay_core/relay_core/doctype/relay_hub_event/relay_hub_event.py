import frappe
from frappe.model.document import Document


class RelayHubEvent(Document):
    def validate(self):
        from relay_core.inbound import callback_write
        if not callback_write.get():
            frappe.throw('Hub events require an authenticated callback', frappe.PermissionError)
