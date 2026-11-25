import frappe
from frappe.model.document import Document


class RelayGenieDelivery(Document):
    """One customer message sent to Genie: its delivery and whether the chat was answered after it."""


def on_doctype_update():
    # The scheduler reads due retries and delivered messages that still wait for an answer by these keys.
    frappe.db.add_index('Relay Genie Delivery', ['status', 'next_try'], 'relay_genie_delivery_due')
    frappe.db.add_index('Relay Genie Delivery', ['status', 'delivered_at'], 'relay_genie_delivery_watch')
