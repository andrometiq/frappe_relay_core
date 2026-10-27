from frappe.model.document import Document
from relay_core.flows.service import clear_keywords, validate_flow

class RelayFlow(Document):
    def validate(self):
        validate_flow(self)

    def on_update(self):
        clear_keywords()

    def on_trash(self):
        clear_keywords()
