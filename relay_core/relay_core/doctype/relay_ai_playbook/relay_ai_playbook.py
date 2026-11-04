import frappe
from frappe.model.document import Document

from relay_core.ai.playbooks import MAX_DESCRIPTION, MAX_GLOBAL_ROWS, MAX_INSTRUCTIONS

# An app playbook follows its SKILL.md file; owners still choose enabled, is_global, company and business type.
FILE_FIELDS = ('title', 'description', 'instructions', 'audience', 'app', 'is_system_generated')


class RelayAIPlaybook(Document):
    def validate(self):
        self.validate_file_fields()
        if not self.is_system_generated and not (self.playbook_key or '').startswith('desk/'):
            frappe.throw('A playbook made in Relay needs a key that starts with desk/')
        if len(self.description or '') > MAX_DESCRIPTION:
            frappe.throw(f'Use at most {MAX_DESCRIPTION} description characters')
        if not self.is_global and not (self.description or '').strip():
            frappe.throw('A playbook that is not in every prompt needs a description for the playbook index')
        if not isinstance(self.instructions, str) or not 1 <= len(self.instructions.strip()) <= MAX_INSTRUCTIONS:
            frappe.throw(f'Use 1–{MAX_INSTRUCTIONS} instruction characters')
        # The knowledge move copies every legacy row; over the cap, the prompt refuses as it did before the move.
        if self.enabled and self.is_global and not frappe.flags.in_patch and frappe.db.count(
                self.doctype, {'enabled': 1, 'is_global': 1, 'name': ['!=', self.name or '']}) >= MAX_GLOBAL_ROWS:
            frappe.throw(f'At most {MAX_GLOBAL_ROWS} playbooks can be in every prompt')

    def validate_file_fields(self):
        if frappe.flags.in_playbook_sync:
            return
        before = self.get_doc_before_save()
        locked = self.is_system_generated or (before and before.is_system_generated)
        if locked and any(self.has_value_changed(field) for field in FILE_FIELDS):
            frappe.throw('An app playbook changes only through its SKILL.md file')

    def on_trash(self):
        if self.is_system_generated and not frappe.flags.in_playbook_sync:
            frappe.throw('An app playbook is removed only by deleting its SKILL.md file')
