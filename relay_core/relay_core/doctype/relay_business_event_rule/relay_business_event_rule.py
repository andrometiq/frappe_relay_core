from frappe.model.document import Document
from relay_core.business_events import validate_rule


class RelayBusinessEventRule(Document):
    def validate(self):
        validate_rule(self)
