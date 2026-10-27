from frappe.model.document import Document
from relay_core.document_actions import clear_cache, validate_action


class RelayDocumentAction(Document):
    def validate(self):
        validate_action(self)

    def on_update(self):
        clear_cache()

    def on_trash(self):
        clear_cache()
