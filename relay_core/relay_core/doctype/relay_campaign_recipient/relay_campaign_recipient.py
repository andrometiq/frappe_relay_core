import frappe
from relay_core.automation.documents import InternalRecord


class RelayCampaignRecipient(InternalRecord):
    pass


def on_doctype_update():
    frappe.db.add_index('Relay Campaign Recipient', ['campaign', 'status', 'sheet_row'], 'campaign_status_row')
    # Reply links and reply routing look up a number's sends; it replaces the single destination index.
    frappe.db.add_index('Relay Campaign Recipient', ['destination', 'provider_id'], 'destination_provider')
