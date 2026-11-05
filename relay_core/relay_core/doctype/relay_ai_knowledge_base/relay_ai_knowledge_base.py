import frappe
from frappe.model.document import Document

MAX_DESCRIPTION = 300


class RelayAIKnowledgeBase(Document):
    def validate(self):
        if len(self.description or '') > MAX_DESCRIPTION:
            frappe.throw(f'Keep the description within {MAX_DESCRIPTION} characters')
        if not self.flags.events_base:
            # Only ingest.events_base marks the knowledge base that holds the event sources.
            self.is_events = 0 if self.is_new() else self.get_db_value('is_events')

    def on_trash(self):
        """Relay links never block a delete, so the sources and their chunks go with the knowledge base."""
        for name in frappe.get_all('Relay AI Knowledge Source', filters={'knowledge_base': self.name}, pluck='name'):
            frappe.delete_doc('Relay AI Knowledge Source', name, ignore_permissions=True)
