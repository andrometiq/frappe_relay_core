"""Permission-filtered captions for links, independent of their stored identifiers."""
import frappe
from relay_core.permissions import require_access


@frappe.whitelist(methods=['GET'])
def titles(records):
    require_access()
    records = frappe.parse_json(records) if isinstance(records, str) else records
    if not isinstance(records, list) or len(records) > 50:
        frappe.throw('Request at most 50 record titles')
    from relay_core.business_access import allowed_types, person_allowed
    business_types = allowed_types()
    items = []
    for row in records:
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip()
                or len(row[key]) > 140 or any(ord(c) < 32 for c in row[key]) for key in ('doctype', 'name')):
            frappe.throw('Invalid record title reference')
        doctype, name = row['doctype'], row['name']
        relay_read = doctype in business_types or doctype == 'Contact' and person_allowed(name)
        if (doctype == 'Contact' or frappe.db.exists('Relay Contact Type', doctype)) and not relay_read:
            continue
        if not relay_read and not frappe.has_permission(doctype, 'read'):
            continue
        meta = frappe.get_meta(doctype)
        from relay_core.business_groups import title_field
        field = title_field(doctype) if relay_read else meta.title_field or 'name'
        fields = ['name', field] if field != 'name' else ['name']
        if doctype == 'Relay Channel':
            fields.extend(['channel', 'account'])
        # get_list applies document/user permissions and field-level access.
        read = frappe.get_all if relay_read else frappe.get_list
        result = read(doctype, filters={'name': name}, fields=fields, page_length=1)
        if result:
            title = result[0].get(field)
            if doctype == 'Relay Channel':
                provider, account = result[0].get('channel'), result[0].get('account')
                # Old channel creation synthesized a title from the account key.
                # Only an independently configured human title is a caption.
                if not title or title in (name, account, f'{provider} {account}', f'{provider} · {account}'):
                    title = provider
            items.append({'doctype': doctype, 'name': name, 'title': title or doctype})
    return {'items': items}
