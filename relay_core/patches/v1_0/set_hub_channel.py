import frappe


def execute():
    """A legacy Hub account has one channel per type, and the Hub keys it by the account id.

    The first enabled channel of each type and account takes that key; duplicates stay unkeyed."""
    frappe.reload_doc('relay_core', 'doctype', 'relay_channel')
    frappe.reload_doc('relay_core', 'doctype', 'relay_hub_event')
    rows = frappe.get_all('Relay Channel', fields=['name', 'channel', 'account', 'hub_channel'],
                          order_by='enabled desc, creation asc')
    keyed = {(row.channel, row.hub_channel) for row in rows if row.hub_channel}
    for row in rows:
        if not row.hub_channel and row.account and (row.channel, row.account) not in keyed:
            frappe.db.set_value('Relay Channel', row.name, 'hub_channel', row.account, update_modified=False)
            keyed.add((row.channel, row.account))
