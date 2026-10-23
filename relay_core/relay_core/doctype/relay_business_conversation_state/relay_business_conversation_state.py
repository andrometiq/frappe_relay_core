from frappe.model.document import Document


class RelayBusinessConversationState(Document):
    def validate(self):
        from relay_core.business_inbox import validate_state
        validate_state(self)
