from frappe.model.document import Document


class RelayEmailRule(Document):
    def validate(self):
        from relay_core.email_preferences import validate_rule
        validate_rule(self)
