from frappe.model.document import Document
from relay_core import ticket_settings


class RelayTicketType(Document):
    def on_trash(self):
        ticket_settings.block_used_setting(self)
