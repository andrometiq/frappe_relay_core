import frappe
from frappe.model.document import Document


class RelayAIKnowledge(Document):
    def validate(self):
        if not isinstance(self.instructions, str) or not 1 <= len(self.instructions.strip()) <= 8000:
            frappe.throw('Use 1–8000 standing instruction characters')
