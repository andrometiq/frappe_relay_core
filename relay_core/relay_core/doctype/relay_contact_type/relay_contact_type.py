import re

import frappe
from frappe.model.document import Document
from relay_core.permissions import require_access

class RelayContactType(Document):
    def validate(self):
        require_access(manage=True)
        configure = validate_configuration_access(self)
        validate_business_doctype(self.business_doctype)
        users = [row.user for row in self.get('users') or []]
        if len(users) != len(set(users)):
            frappe.throw('Each user can be assigned only once per business type.')
        rows = self.get('grouping_fields') or []
        if len(rows) > 6:
            frappe.throw('Choose at most six grouping fields.')
        seen = set()
        for row in rows:
            field = frappe.get_meta(self.business_doctype).get_field(row.fieldname)
            if not _is_grouping_field(field) or row.fieldname in seen:
                frappe.throw(
                    f"Choose distinct available grouping fields from {frappe.bold(self.business_doctype)}."
                )
            if isinstance(row.priority, bool) or not str(row.priority).isdigit() or int(row.priority) < 1:
                frappe.throw('Grouping priority must be a positive integer.')
            seen.add(row.fieldname)
        # After editing the table, clearing its last row must mean no grouping.
        if configure:
            self.grouping_field = ''

    def on_update(self):
        from relay_core.queue_counts import invalidate
        invalidate()
        # Each level groups a direct business field; the chat join already has a unique record index.
        from relay_core.business_groups import install_indexes
        # MariaDB index DDL commits implicitly; finish saving the configuration first.
        frappe.db.after_commit.add(lambda: install_indexes(self.business_doctype, config=self))


def _is_grouping_field(field):
    return bool(
        field
        and field.fieldtype in ("Link", "Select", "Data")
        and not field.permlevel
        and not field.hidden
    )


def validate_configuration_access(doc):
    """Managers may change only assignments, including through Desk/resource saves."""
    if frappe.session.user == 'Administrator' or 'System Manager' in frappe.get_roles():
        return True
    previous = None if doc.is_new() else doc.get_doc_before_save()
    fields = ('business_doctype', 'enabled', 'label', 'grouping_field')
    groups = lambda value: [(row.fieldname, row.priority) for row in value.get('grouping_fields') or []]
    if (not previous or any(doc.get(field) != previous.get(field) for field in fields)
            or groups(doc) != groups(previous)):
        frappe.throw('Only System Manager can configure business types; managers may edit users only', frappe.PermissionError)
    return False


def validate_business_doctype(doctype):
    meta = frappe.get_meta(doctype)
    if (meta.issingle or meta.istable or meta.module in ('Core', 'Integrations', 'Email')
            or doctype in ('User', 'Role', 'Has Role', 'DocType', 'DocPerm', 'Custom DocPerm', 'User Permission')
            or re.search(r'token|key|password|secret', doctype, re.IGNORECASE)):
        frappe.throw('Choose a business DocType with non-security records')
