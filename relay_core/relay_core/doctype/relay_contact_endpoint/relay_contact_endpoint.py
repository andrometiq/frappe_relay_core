import hashlib
import frappe
from frappe.model.document import Document
from relay_core.permissions import require_access


class RelayContactEndpoint(Document):
    def validate(self):
        if getattr(frappe.flags, "relay_business_contact_sync", False):
            require_access()
        elif getattr(frappe.flags, "relay_endpoint_enrollment", False):
            require_access(manage=True)
        else:
            require_access(configure=True)
        if not self.endpoint or len(self.endpoint) > 200 or any(ord(c) < 32 for c in self.endpoint):
            frappe.throw('Invalid endpoint')
        self.endpoint_key = hashlib.sha256((self.channel + ':' + self.endpoint).encode()).hexdigest()
