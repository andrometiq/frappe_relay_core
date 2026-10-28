from frappe.model.document import Document
from relay_core import ticket_settings


class RelayTicketType(Document):
    def validate(self):
        ticket_settings.validate_setting(self)

    def on_update(self):
        ticket_settings.after_setting_saved(self)

    def on_trash(self):
        ticket_settings.block_used_setting(self)
