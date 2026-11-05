import frappe
from frappe.model.document import Document


class RelayAIMemory(Document):
    def validate(self):
        from relay_core.ai.fact_memory import MAX_LENGTH, check_limit
        self.content = ' '.join((self.content or '').split())
        if not 1 <= len(self.content) <= MAX_LENGTH:
            frappe.throw(f'Write one fact of at most {MAX_LENGTH} characters')
        if self.scope == 'Skill':
            self.business_doctype = self.business_name = None
        elif not (self.business_doctype and self.business_name):
            frappe.throw('A Business fact needs its business record')
        if self.status == 'Active' and (self.is_new() or self.has_value_changed('status')):
            check_limit(self)


def on_doctype_update():
    from relay_core.ai.fact_memory import install_indexes
    install_indexes()
