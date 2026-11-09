import frappe
from frappe.model.document import Document

from relay_core.ai.persona import MAX_INSTRUCTIONS


class RelayAIPersona(Document):
    def validate(self):
        if len(self.instructions or '') > MAX_INSTRUCTIONS:
            frappe.throw(f'Use at most {MAX_INSTRUCTIONS} instruction characters')
        company = self.company or ['is', 'not set']
        if frappe.db.exists(self.doctype, {'company': company, 'name': ['!=', self.name or '']}):
            frappe.throw('This company already has a persona; change that one' if self.company
                         else 'A persona for every company already exists; change that one', frappe.DuplicateEntryError)
