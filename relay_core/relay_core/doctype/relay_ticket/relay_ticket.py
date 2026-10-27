from frappe.model.document import Document
from relay_core import ticket_tags
from relay_core.tickets import validate_ticket


class RelayTicket(Document):
    def validate(self):
        validate_ticket(self)

    def on_update(self):
        ticket_tags.on_update(self)
