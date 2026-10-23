from frappe.model.document import Document
from relay_core.flows.service import validate_flow

class RelayFlow(Document):
    def validate(self):
        validate_flow(self)
