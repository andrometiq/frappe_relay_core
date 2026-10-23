from frappe.model.document import Document
from relay_core.business_events import clear_rule_cache, validate_rule


class RelayBusinessEventRule(Document):
    def validate(self):
        validate_rule(self)

    def on_update(self):
        clear_rule_cache()

    def on_trash(self):
        clear_rule_cache()
