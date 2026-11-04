import frappe
from frappe.model.document import Document


class RelayAIKnowledge(Document):
    """Read only: the patch move_ai_knowledge_to_playbooks moved each row to Relay AI Playbook."""

    def validate(self):
        frappe.throw('Standing instructions moved to Relay AI Playbook')
