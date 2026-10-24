"""Permission-filtered captions for links, independent of their stored identifiers."""
import frappe
from relay_core.permissions import require_access


@frappe.whitelist(methods=['GET'])
def titles(records):
    require_access()
    records = frappe.parse_json(records) if isinstance(records, str) else records
    if not isinstance(records, list) or len(records) > 50:
        frappe.throw('Request at most 50 record titles')
    items = []
    for row in records:
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip()
                or len(row[key]) > 140 or any(ord(c) < 32 for c in row[key]) for key in ('doctype', 'name')):
            frappe.throw('Invalid record title reference')
        doctype, name = row['doctype'], row['name']
        if not frappe.has_permission(doctype, 'read'):
            continue
        meta = frappe.get_meta(doctype)
        field = meta.title_field or 'name'
        fields = ['name', field] if field != 'name' else ['name']
        if doctype == 'Relay Channel':
            fields.extend(['channel', 'account'])
        # get_list applies document/user permissions and field-level access.
        result = frappe.get_list(doctype, filters={'name': name}, fields=fields, page_length=1)
        if result:
            title = result[0].get(field)
            if not title and doctype == 'Relay Channel':
                title = ' · '.join(value for value in (result[0].get('channel'), result[0].get('account')) if value)
            items.append({'doctype': doctype, 'name': name, 'title': title or doctype})
    return {'items': items}
