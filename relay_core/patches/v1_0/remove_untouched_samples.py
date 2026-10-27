import frappe

# (doctype, sample_key, title) exactly as the removed sample installers created them.
SAMPLES = (
    ('Relay Business Event Rule', 'Delivery Note', 'We have delivered {name}: {items_summary}'),
    ('Relay Business Event Rule', 'Sales Order', 'Order {name} received: {total_qty}'),
    ('Relay AI Skill', 'supplier_ledger', 'Supplier ledger'),
)


def execute():
    """Delete sample rules and skills that are still disabled and were never saved after creation."""
    for doctype, sample_key, title in SAMPLES:
        rows = frappe.get_all(doctype, filters={'sample_key': sample_key, 'title': title, 'enabled': 0},
            fields=['name', 'creation', 'modified'])
        for row in rows:
            if row.modified != row.creation:
                continue
            try:
                frappe.delete_doc(doctype, row.name, ignore_permissions=True)
            except frappe.LinkExistsError:
                continue
