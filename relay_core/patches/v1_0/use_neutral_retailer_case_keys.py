import frappe

from relay_core.flows.retailer import TYPE_PREFIX, TYPES

MARKER = '.retailer_connect.'


def execute():
    """Move retailer case types from the old business prefix to the neutral Relay prefix."""
    rows = frappe.get_all('Relay Case Type', filters={'type_key': ['like', '%' + MARKER + '%']},
                          fields=['name', 'type_key'])
    for row in rows:
        suffix = row.type_key.split(MARKER, 1)[1]
        key = TYPE_PREFIX + suffix
        if row.type_key == key or suffix not in TYPES or frappe.db.exists('Relay Case Type', {'type_key': key}):
            continue
        frappe.db.set_value('Relay Case Type', row.name, 'type_key', key, update_modified=False)
