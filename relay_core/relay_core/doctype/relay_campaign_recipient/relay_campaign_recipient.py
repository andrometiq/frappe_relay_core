import frappe
from relay_core.automation.documents import InternalRecord


class RelayCampaignRecipient(InternalRecord):
    pass


def on_doctype_update():
    frappe.db.add_index('Relay Campaign Recipient', ['campaign', 'status', 'sheet_row'], 'campaign_status_row')
