import frappe

# Names of the removed agent bridge. Its delivery rows were test rows only.
OLD_DOCTYPE = 'Relay Genie Delivery'
OLD_SETTINGS = ('genie_enabled', 'genie_url', 'genie_secret', 'genie_user', 'genie_business_types')


def execute():
    """Drop the old agent delivery log and its Relay Settings values; agents now come from Relay AI skills."""
    frappe.delete_doc('DocType', OLD_DOCTYPE, ignore_missing=True, force=True)
    frappe.db.sql_ddl(f'drop table if exists `tab{OLD_DOCTYPE}`')
    frappe.db.delete('Singles', {'doctype': 'Relay Settings', 'field': ('in', OLD_SETTINGS)})
    frappe.db.delete('__Auth', {'doctype': 'Relay Settings', 'fieldname': 'genie_secret'})
