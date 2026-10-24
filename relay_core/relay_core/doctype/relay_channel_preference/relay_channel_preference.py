from frappe.model.document import Document
from relay_core.channel_preferences import validate


class RelayChannelPreference(Document):
    def validate(self):
        validate(self)
