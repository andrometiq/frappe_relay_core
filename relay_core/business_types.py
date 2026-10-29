"""Business DocTypes whose records a contact can be linked to."""
import frappe
from relay_core.permissions import require_access, can_configure

FIELDS = ['business_doctype', 'label', 'enabled']


def with_groups(row, config=None):
    from relay_core.business_groups import configuration
    fields = configuration(row['business_doctype'], config=config)
    return frappe._dict(row, grouping_field=fields[0] if fields else '', grouping_fields=fields)


@frappe.whitelist(methods=['GET'])
def list_types():
    """Configured types the user can read; System Managers also see disabled ones."""
    require_access()
    filters = {} if can_configure() else {'enabled': 1}
    rows = frappe.get_all('Relay Contact Type', filters=filters, fields=FIELDS,
                          order_by='business_doctype asc', limit_page_length=200)
    return [with_groups(row) for row in rows if frappe.has_permission(row.business_doctype, 'read')]


@frappe.whitelist(methods=['POST'])
def save(business_doctype, enabled=1, label=None, grouping_field=None, grouping_fields=None):
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
    if grouping_fields is not None:
        rows = frappe.parse_json(grouping_fields) if isinstance(grouping_fields, str) else grouping_fields
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            frappe.throw('Grouping fields must be a list of fieldname and priority rows')
        doc.set('grouping_fields', [{'fieldname': row.get('fieldname'), 'priority': row.get('priority')} for row in rows])
        doc.grouping_field = ''
    elif grouping_field is not None:
        # The old API remains writable, but its value is stored in the new table.
        doc.set('grouping_fields', [{'fieldname': grouping_field.strip(), 'priority': 1}] if grouping_field.strip() else [])
        doc.grouping_field = ''
    doc.save()
    return with_groups({field: doc.get(field) for field in FIELDS}, config=doc)
