import frappe


def execute():
    """identity.bindings reads canonical_endpoint, so every stored endpoint, including legacy aliases, gets one."""
    from relay_core.identity import canonical_endpoint
    providers = dict(frappe.get_all('Relay Channel', fields=['name', 'channel'], as_list=True))
    for row in frappe.get_all('Relay Contact Endpoint', fields=['name', 'channel', 'endpoint', 'canonical_endpoint']):
        value = canonical_endpoint(providers.get(row.channel), row.endpoint)
        if value != row.canonical_endpoint:
            frappe.db.set_value('Relay Contact Endpoint', row.name, 'canonical_endpoint', value, update_modified=False)
