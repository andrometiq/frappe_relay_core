from frappe.model.document import Document


class RelayConversationAssignment(Document):
    def validate(self):
        from relay_core.teams import validate_assignment
        validate_assignment(self)
