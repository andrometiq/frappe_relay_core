from frappe.model.document import Document


class RelayEmailPreference(Document):
    def validate(self):
        from relay_core.email_preferences import validate_preference
        validate_preference(self)
