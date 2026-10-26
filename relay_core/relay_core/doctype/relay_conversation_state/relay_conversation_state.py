import frappe
from frappe.model.document import Document


class RelayConversationState(Document):
    def validate(self):
        from relay_core.inbox import validate_state
        validate_state(self)


def on_doctype_update():
    # Unread queries join each message to the current user's read position.
    frappe.db.add_index('Relay Conversation State', ['user', 'relay_contact'], 'relay_user_states')
