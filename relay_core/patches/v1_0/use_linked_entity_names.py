import frappe
from frappe.model.rename_doc import (
    get_link_fields,
    rename_parent_and_child,
    rename_versions,
    update_attachments,
    update_link_field_values,
)


LINKED_NAME_FIELDS = (
    ("Relay Contact Type", "business_doctype"),
    ("Relay Automation Policy", "channel"),
    ("Relay Email Rule", "channel"),
    ("Relay Email Preference", "user"),
)


def execute():
    for doctype, fieldname in LINKED_NAME_FIELDS:
        if not frappe.db.exists("DocType", doctype):
            continue

        rows = frappe.get_all(doctype, fields=["name", fieldname])
        for row in rows:
            linked_name = row.get(fieldname)
            if not linked_name or row.name == linked_name:
                continue
            if frappe.db.exists(doctype, linked_name):
                frappe.throw(
                    f"Cannot rename {doctype} {row.name} to {linked_name}: that name already exists."
                )
            _rename_linked_record(doctype, row.name, linked_name)


def _rename_linked_record(doctype, old_name, new_name):
    """Rename app configuration without Frappe's site-wide dynamic-link scan.

    The standard rename path discovers dynamic links by scanning every dynamic
    type column on the site. Large ERP ledgers make that unsuitable for a
    migration. Relay configuration can only be referenced by ordinary Link
    fields and Frappe's common timeline tables, which are updated explicitly.
    """
    meta = frappe.get_meta(doctype)
    rename_parent_and_child(doctype, old_name, new_name, meta)
    update_link_field_values(get_link_fields(doctype), old_name, new_name, doctype)

    dynamic_references = (
        ("Comment", "reference_doctype", "reference_name"),
        ("Communication", "reference_doctype", "reference_name"),
        ("Communication Link", "link_doctype", "link_name"),
        ("ToDo", "reference_type", "reference_name"),
        ("Document Follow", "ref_doctype", "ref_docname"),
        ("Tag Link", "document_type", "document_name"),
    )
    for parent, type_field, name_field in dynamic_references:
        if not frappe.db.exists("DocType", parent):
            continue
        table = frappe.qb.DocType(parent)
        (
            frappe.qb.update(table)
            .set(table[name_field], new_name)
            .where((table[type_field] == doctype) & (table[name_field] == old_name))
            .run()
        )

    update_attachments(doctype, old_name, new_name)
    rename_versions(doctype, old_name, new_name)
