import frappe
from frappe.model.document import Document
from relay_core.permissions import require_access

class RelayContactType(Document):
    def validate(self):
        require_access(configure=True)
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
        self.grouping_field = ''

    def on_update(self):
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
