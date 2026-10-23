import re
import frappe
from frappe.model.document import Document
from relay_core.permissions import require_access
from relay_core.hub import HubClient

class RelaySettings(Document):
    def validate(self):
        require_access(configure=True)
        if self.hub_url:
            HubClient(self.hub_url,'validation-only-placeholder-token-32-characters')

        if self.hub_account and not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',self.hub_account):
            frappe.throw('Hub account must contain 1–100 letters, numbers, underscores or hyphens')
        for field,maximum in (('hub_token',4096),('callback_secret',512)):
            value=self.get(field)
            if value and not set(value)=={'*'} and (not 32<=len(value)<=maximum or any(ord(c)<32 for c in value)):
                frappe.throw('Credentials must contain at least 32 printable characters')
