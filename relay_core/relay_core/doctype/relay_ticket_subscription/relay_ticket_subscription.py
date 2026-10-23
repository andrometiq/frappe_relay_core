from frappe.model.document import Document
from relay_core.ticket_notifications import validate_subscription

class RelayTicketSubscription(Document):
    def validate(self):
        validate_subscription(self)
