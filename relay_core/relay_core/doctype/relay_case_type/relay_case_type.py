from frappe.model.document import Document

class RelayCaseType(Document):
    def validate(self):
        from relay_core.cases import validate_type
        validate_type(self)
