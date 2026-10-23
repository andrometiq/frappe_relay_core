from frappe.model.document import Document
from relay_core.ai.configuration import validate_skill


class RelayAISkill(Document):
    def validate(self):
        validate_skill(self)
