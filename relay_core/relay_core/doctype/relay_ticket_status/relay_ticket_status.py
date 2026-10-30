from frappe.model.document import Document
from relay_core import ticket_settings


class RelayTicketStatus(Document):
    def validate(self):
        ticket_settings.validate_status(self)

    def on_trash(self):
        ticket_settings.block_used_setting(self)
