"""Permission-checked choices for business event rules, independent of AI enablement."""
import frappe
from relay_core.permissions import require_access, can_manage
from relay_core.business_references import RELAY_DOCTYPES


@frappe.whitelist(methods=['GET'])
def search(kind, query='', doctype=None, business_doctype=None, selected=None):
    require_access('Relay Business Event Rule', 'write')
    if not isinstance(query, str) or len(query) > 80:
        raise ValueError('Use at most 80 search characters')
    selected = frappe.parse_json(selected) if isinstance(selected, str) else selected
    if selected is not None and (not isinstance(selected, list) or len(selected) > 20
            or any(not isinstance(value, str) or len(value) > 140 for value in selected)):
        raise ValueError('Invalid selected options')
    if doctype and (not isinstance(doctype, str) or doctype in RELAY_DOCTYPES
            or not frappe.has_permission(doctype, 'read')):
        raise frappe.PermissionError('Source DocType is not accessible')
    if kind == 'business_doctype':
        from relay_core.api import business_types
        items = [dict(value=name, label=name) for name in business_types()]
    elif kind in ('recipient_field', 'contact_field', 'field'):
        items = []
        if doctype:
            meta = frappe.get_meta(doctype)
            readable = set(meta.get_permitted_fieldnames(permission_type='read'))
            if kind == 'field':
                items.append(dict(value='name', label='Record name'))
            for field in meta.fields:
                if field.fieldname not in readable or field.hidden:
                    continue
                if kind == 'field':
                    allowed = field.fieldtype not in ('Table', 'Table MultiSelect', 'Password', 'Code', 'HTML',
                        'Section Break', 'Column Break', 'Tab Break', 'Button', 'Heading')
                else:
                    allowed = field.fieldtype == 'Link' and field.options == (
                        'Contact' if kind == 'contact_field' else business_doctype)
                if allowed:
                    items.append(dict(value=field.fieldname, label=field.label or field.fieldname.replace('_', ' ').title()))
            if kind == 'field' and 'items' in readable and meta.get_field('items').fieldtype == 'Table':
                items.append(dict(value='items_summary', label='Items summary'))
    else:
        choices = {
            'doctype': ('DocType', 'name', {'issingle': 0, 'istable': 0, 'is_virtual': 0}),
            'user': ('User', 'full_name', {'enabled': 1, 'name': ['!=', 'Guest']}),
            'print_format': ('Print Format', 'name', {'doc_type': doctype, 'disabled': 0}),
            'report': ('Report', 'name', {'ref_doctype': doctype, 'disabled': 0}),
        }
        if kind not in choices:
            raise ValueError('Unknown business event picker')
        if kind in ('print_format', 'report') and not doctype:
            return {'items': []}
        target, caption, filters = choices[kind]
        pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        filters['name' if selected is not None else caption] = ['in', selected] if selected is not None else ['like', pattern]
        rows = frappe.get_list(target, filters=filters, fields=list(dict.fromkeys(['name', caption])),
                               order_by=caption + ' asc', page_length=30)
        items = [dict(value=row.name, label=row.get(caption) or kind.replace('_', ' ').title()) for row in rows
                 if (kind != 'doctype' or row.name not in RELAY_DOCTYPES and frappe.has_permission(row.name, 'read'))
                 and (kind != 'user' or row.name != 'Guest' and can_manage(row.name))]
    if selected is not None:
        items = [row for row in items if row['value'] in selected]
    elif query:
        items = [row for row in items if query.casefold() in row['label'].casefold()]
    return {'items': items[:30]}
