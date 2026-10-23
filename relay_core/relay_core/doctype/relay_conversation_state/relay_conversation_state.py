from frappe.model.document import Document


class RelayConversationState(Document):
    def validate(self):
        from relay_core.inbox import validate_state
        validate_state(self)
