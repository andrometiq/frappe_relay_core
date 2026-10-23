import frappe
from frappe.model.document import Document
from relay_core.permissions import require_access

class RelayContactType(Document):
    def validate(self):
        require_access(configure=True)
        if self.get('grouping_field'):
            field = frappe.get_meta(self.business_doctype).get_field(self.grouping_field)
            if not _is_grouping_field(field):
                frappe.throw(
                    f"Choose an available grouping field from {frappe.bold(self.business_doctype)}."
                )


def _is_grouping_field(field):
    return bool(
        field
        and field.fieldtype in ("Link", "Select", "Data")
        and not field.permlevel
        and not field.hidden
    )
