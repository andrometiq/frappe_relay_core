import frappe
from frappe.model.document import Document
from relay_core.ai.capabilities import LOADER_FIELDS


class RelayAICapability(Document):
    def validate(self):
        """Only the loader and approve() write manifest state; owners switch Enabled."""
        if self.flags.from_loader:
            return
        previous = self.get_doc_before_save()
        if not previous or any(self.get(field) != previous.get(field) for field in LOADER_FIELDS):
            frappe.throw('Only Enabled can be changed; approve a capability from Relay', frappe.PermissionError)
