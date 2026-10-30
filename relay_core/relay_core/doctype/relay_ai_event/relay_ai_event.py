import frappe
from frappe.model.document import Document
from frappe.utils import getdate

MAX_LINKS = 10
MAX_DESCRIPTION = 10000


class RelayAIEvent(Document):
    def validate(self):
        if len(self.description or '') > MAX_DESCRIPTION:
            frappe.throw(f'Keep the description within {MAX_DESCRIPTION} characters. Attach a file for more detail.')
        for start, end, label in ((self.available_from, self.available_to, 'AI use'),
                                  (self.event_starts_on, self.event_ends_on, 'The event')):
            if start and end and getdate(end) < getdate(start):
                frappe.throw(f'{label} ends before it starts')
        self.validate_links()
        self.validate_audience()

    def validate_links(self):
        from relay_core.ai.event_sources import SourceError, check_url
        if len(self.links) > MAX_LINKS:
            frappe.throw(f'Add at most {MAX_LINKS} links')
        for row in self.links:
            try:
                check_url(row.url)
            except SourceError as error:
                frappe.throw(f'Row {row.idx}: {error}')

    def validate_audience(self):
        types = [row.business_doctype for row in self.audience]
        if len(types) != len(set(types)):
            frappe.throw('Each business type can appear only once in the audience')
        disabled = [name for name in types if not frappe.db.get_value('Relay Contact Type', name, 'enabled')]
        if disabled:
            frappe.throw(f'Enable these contact types first: {", ".join(disabled)}')

    def on_update(self):
        from relay_core.ai.event_memory import queue_build
        queue_build(self.name)

    def on_trash(self):
        """Builds go with the event. An event that informed a reply stays for the audit; archive it instead."""
        if frappe.db.exists('Relay Automation Run', {'ai_context': ['like', f'%"{self.name}"%']}):
            frappe.throw('The AI used this event in replies. Uncheck Enabled to archive it.')
        frappe.db.delete('Relay AI Event Build', {'event': self.name})
