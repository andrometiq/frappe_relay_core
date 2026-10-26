"""Business DocTypes whose records a contact can be linked to."""
import frappe
from relay_core.permissions import require_access

FIELDS = ['business_doctype', 'label', 'enabled', 'grouping_field']


@frappe.whitelist(methods=['GET'])
def list_types():
    """Configured types the user can read; System Managers also see disabled ones."""
    require_access()
    filters = {} if 'System Manager' in frappe.get_roles() else {'enabled': 1}
    rows = frappe.get_all('Relay Contact Type', filters=filters, fields=FIELDS,
                          order_by='business_doctype asc', limit_page_length=200)
    return [row for row in rows if frappe.has_permission(row.business_doctype, 'read')]


@frappe.whitelist(methods=['POST'])
def save(business_doctype, enabled=1, label=None, grouping_field=None):
    require_access(configure=True)
    if not isinstance(business_doctype, str) or not frappe.db.exists('DocType', business_doctype):
        frappe.throw('Choose a business DocType')
    meta = frappe.get_meta(business_doctype)
    if meta.istable or meta.issingle:
        frappe.throw('Choose a DocType that has records')
    if not frappe.has_permission(business_doctype, 'read'):
        frappe.throw('Business type is not readable', frappe.PermissionError)
    if str(enabled) not in ('0', '1', 'True', 'False'):
        frappe.throw('Enabled must be 0 or 1')
    for value in (label, grouping_field):
        if value is not None and (not isinstance(value, str) or len(value) > 140):
            frappe.throw('Label and grouping field must be text of at most 140 characters')
    exists = frappe.db.exists('Relay Contact Type', business_doctype)
    doc = frappe.get_doc('Relay Contact Type', business_doctype) if exists else frappe.new_doc('Relay Contact Type')
    doc.business_doctype = business_doctype
    doc.enabled = int(str(enabled) in ('1', 'True'))
    if label is not None: doc.label = label.strip()
    if grouping_field is not None: doc.grouping_field = grouping_field.strip()
    doc.save()
    return {field: doc.get(field) for field in FIELDS}
