from frappe.model.document import Document
from relay_core.tickets import validate_ticket


class RelayTicket(Document):
    def validate(self):
        validate_ticket(self)
