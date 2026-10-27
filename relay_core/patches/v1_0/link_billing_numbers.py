import frappe


def execute():
    """Billing rows from before numbers were split belong to the account's legacy WhatsApp channel."""
    frappe.reload_doc('relay_core', 'doctype', 'relay_whatsapp_billing_month')
    for account in frappe.get_all('Relay WhatsApp Billing Month', filters={'relay_channel': ['is', 'not set']},
                                  pluck='account', distinct=True):
        channels = frappe.get_all('Relay Channel', fields=['name', 'hub_channel'], order_by='creation asc',
                                  filters={'channel': 'WhatsApp', 'account': account})
        legacy = [row.name for row in channels if row.hub_channel == account] or [row.name for row in channels]
        if len(legacy) == 1:
            frappe.db.set_value('Relay WhatsApp Billing Month', {'account': account, 'relay_channel': ['is', 'not set']},
                                'relay_channel', legacy[0], update_modified=False)
