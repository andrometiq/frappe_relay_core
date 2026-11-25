"""Business DocTypes whose records a contact can be linked to."""
import frappe
from relay_core.business_access import document_name
from relay_core.permissions import require_access, can_manage

FIELDS = ['business_doctype', 'label', 'enabled']
MAX_PROFILE_FIELDS = 12
PROFILE_FIELDTYPES = frozenset({'Data', 'Link', 'Select', 'Int', 'Float', 'Currency', 'Date', 'Datetime', 'Check',
                                'Small Text', 'Phone'})


def is_profile_field(field):
    return bool(field and field.fieldtype in PROFILE_FIELDTYPES and not field.hidden and not field.permlevel)


def type_label(doctype):
    """The configured caption of a business type, such as "Retailer" for "YRP Retailer"."""
    return frappe.db.get_value('Relay Contact Type', doctype, 'label') or doctype


def profile(doc):
    """Configured profile fields of a business record as label and display value rows. The caller checks access.
    A field that became hidden or restricted after it was picked is left out."""
    meta = frappe.get_meta(doc.doctype)
    rows = frappe.get_all('Relay Business Profile Field', filters={
        'parent': doc.doctype, 'parenttype': 'Relay Contact Type', 'parentfield': 'profile_fields'},
        fields=['fieldname', 'label'], order_by='idx asc', limit_page_length=MAX_PROFILE_FIELDS)
    picked = [(row, meta.get_field(row.fieldname)) for row in rows]
    return [{'label': row.label or field.label or field.fieldname, 'value': display_value(doc, field)}
            for row, field in picked if is_profile_field(field)]


def display_value(doc, field):
    value = doc.get(field.fieldname)
    if field.fieldtype == 'Check':
        return 'Yes' if value else 'No'
    if value in (None, ''):
        return ''
    if field.fieldtype == 'Link':
        return link_title(field.options, value)
    return str(frappe.format_value(value, field, doc))


def link_title(doctype, name):
    """A linked record's title, such as a sales person's name instead of SP-00013."""
    title_field = frappe.get_meta(doctype).title_field
    return str((title_field and frappe.db.get_value(doctype, name, title_field)) or name)


def picker_options():
    """Enabled Relay-visible types and captions, independent of Desk permissions."""
    from relay_core.business_access import allowed_types
    visible = allowed_types()
    rows = frappe.get_all('Relay Contact Type', filters={'enabled': 1},
                          fields=['business_doctype', 'label'], order_by='business_doctype asc')
    return [dict(value=row.business_doctype, label=row.label or row.business_doctype)
            for row in rows if row.business_doctype in visible]


def with_groups(row, config=None):
    from relay_core.business_groups import configuration
    fields = configuration(row['business_doctype'], config=config)
    result = frappe._dict(row, grouping_field=fields[0] if fields else '', grouping_fields=fields)
    if can_manage():
        config = config or frappe.get_doc('Relay Contact Type', row['business_doctype'])
        result.users = [item.user for item in config.get('users') or []]
    return result


@frappe.whitelist(methods=['GET'])
def list_types():
    """Assigned types for users; managers also see disabled types for configuration."""
    require_access()
    filters = {} if can_manage() else {'enabled': 1}
    rows = frappe.get_all('Relay Contact Type', filters=filters, fields=FIELDS,
                          order_by='business_doctype asc', limit_page_length=200)
    from relay_core.business_access import allowed_types
    visible = allowed_types()
    return [with_groups(row) for row in rows if can_manage() or row.business_doctype in visible]


@frappe.whitelist(methods=['POST'])
def save(business_doctype, enabled=None, label=None, grouping_field=None, grouping_fields=None, users=None):
    document_name(business_doctype)
    require_access(manage=True)
    if not isinstance(business_doctype, str) or not frappe.db.exists('DocType', business_doctype):
        frappe.throw('Choose a business DocType')
    meta = frappe.get_meta(business_doctype)
    if meta.istable or meta.issingle:
        frappe.throw('Choose a DocType that has records')
    if enabled is not None and str(enabled) not in ('0', '1', 'True', 'False'):
        frappe.throw('Enabled must be 0 or 1')
    for value in (label, grouping_field):
        if value is not None and (not isinstance(value, str) or len(value) > 140):
            frappe.throw('Label and grouping field must be text of at most 140 characters')
    exists = frappe.db.exists('Relay Contact Type', business_doctype)
    doc = frappe.get_doc('Relay Contact Type', business_doctype) if exists else frappe.new_doc('Relay Contact Type')
    doc.business_doctype = business_doctype
    if enabled is not None: doc.enabled = int(str(enabled) in ('1', 'True'))
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
    if users is not None:
        users = frappe.parse_json(users) if isinstance(users, str) else users
        if not isinstance(users, list) or any(not isinstance(user, str) or not user for user in users):
            frappe.throw('Users must be a list of user names')
        doc.set('users', [{'user': user} for user in users])
    doc.save()
    return with_groups({field: doc.get(field) for field in FIELDS}, config=doc)
