import frappe


def execute():
    """Each Relay AI Event becomes one source of the Events knowledge base. Event memory stays pinned in replies,
    so replies do not change before the queued ingest finishes or a skill binds the knowledge base."""
    from relay_core.ai.knowledge_base.ingest import queue_event
    for event in frappe.get_all('Relay AI Event', pluck='name', order_by='creation asc'):
        queue_event(event)
