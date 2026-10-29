"""Preserve the legacy first level after the child table has been synced."""
import frappe


def execute():
    from relay_core.business_groups import configuration, install_indexes
    for name in frappe.get_all('Relay Contact Type', pluck='name'):
        doc = frappe.get_doc('Relay Contact Type', name)
        if not doc.get('grouping_fields'):
            for field in configuration(doc.business_doctype, config=doc):
                row = doc.append('grouping_fields', {'fieldname': field, 'priority': 1})
                row.db_insert()
        # Also index configurations already converted before this patch runs.
        install_indexes(doc.business_doctype, config=doc)
        frappe.clear_document_cache('Relay Contact Type', name)
