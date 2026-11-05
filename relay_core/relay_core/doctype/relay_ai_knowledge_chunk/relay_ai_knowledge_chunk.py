from frappe.model.document import Document


class RelayAIKnowledgeChunk(Document):
    pass


def on_doctype_update():
    from relay_core.ai.knowledge_base.store import install_indexes
    install_indexes()
