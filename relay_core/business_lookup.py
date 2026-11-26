"""Business lookups for the AI agent: only the search fields, share fields and fixed filters a manager configured."""
import json
import re

import frappe
from relay_core.business_types import is_profile_field
from relay_core.permissions import require_access

MAX_LIMIT = 10
MAX_FILTERS = 6
MAX_FIELDS = 12
TEXT_FIELDTYPES = frozenset({'Data', 'Small Text', 'Link', 'Phone'})
SECRET = re.compile(r'token|key|password|secret', re.IGNORECASE)


def is_lookup_field(meta, fieldname):
    """A visible, unrestricted plain field (or the record name) that holds no secret."""
    if not isinstance(fieldname, str) or SECRET.search(fieldname):
        return False
    return fieldname == 'name' or is_profile_field(meta.get_field(fieldname))


def is_text(meta, fieldname):
    return fieldname == 'name' or meta.get_field(fieldname).fieldtype in TEXT_FIELDTYPES


def is_filter_value(value):
    if isinstance(value, list):
        return bool(value) and all(isinstance(item, (str, int, float)) for item in value)
    return isinstance(value, (str, int, float))


def fixed_filters(doc) -> dict:
    try:
        value = json.loads(doc.get('lookup_filters') or '{}')
    except ValueError:
        value = None
    if not isinstance(value, dict) or not all(map(is_filter_value, value.values())):
        frappe.throw('Fixed lookup filters must be a JSON object of field and value, or field and list of values')
    return value


def configuration(doc) -> dict:
    """The checked lookup of one business type; the save and every lookup run the same checks."""
    rows = doc.get('lookup_fields') or []
    search = [row.fieldname for row in rows if row.search]
    share = [row.fieldname for row in rows if row.share]
    filters = fixed_filters(doc)
    fields = [row.fieldname for row in rows]
    if len(fields) > MAX_FIELDS or len(set(fields)) != len(fields):
        frappe.throw(f'Choose at most {MAX_FIELDS} distinct lookup fields.')
    names = [*fields, *filters]
    meta = frappe.get_meta(doc.business_doctype) if names else None
    unsafe = [name for name in names if not is_lookup_field(meta, name)]
    if unsafe:
        frappe.throw(f'{unsafe[0]} is not an available lookup field of {frappe.bold(doc.business_doctype)}.')
    if doc.get('lookup_enabled') and not share:
        frappe.throw('Choose at least one share field for the agent lookup.')
    return {'business_type': doc.business_doctype, 'description': doc.get('lookup_description') or '',
            'search_fields': search, 'share_fields': share, 'fixed_filters': filters}


def enabled(business_type) -> dict:
    if not isinstance(business_type, str) or not frappe.db.get_value(
            'Relay Contact Type', {'name': business_type, 'enabled': 1, 'lookup_enabled': 1}):
        frappe.throw(f'{business_type} has no agent lookup; use business_lookup_types.')
    return configuration(frappe.get_doc('Relay Contact Type', business_type))


def types() -> dict:
    require_access()
    names = frappe.get_all('Relay Contact Type', filters={'enabled': 1, 'lookup_enabled': 1}, pluck='name', order_by='name asc')
    items = [enabled(name) for name in names]
    return {'items': [{key: item[key] for key in ('business_type', 'description', 'search_fields', 'share_fields')}
                      for item in items]}


def like(value):
    return '%' + re.sub(r'([\\%_])', r'\\\1', value) + '%'


def search(business_type, filters=None, query='', limit=5) -> dict:
    """Matching records with only the configured share fields.

    get_all skips DocType permissions on purpose: the agent may lack read on the DocType, and only share fields leave."""
    require_access()
    config = enabled(business_type)
    filters = filters or {}
    meta = frappe.get_meta(business_type)
    refused = sorted(set(filters) - set(config['search_fields']))
    if refused:
        frappe.throw(f'Cannot search {business_type} by {refused[0]}; search fields: '
                     f'{", ".join(config["search_fields"]) or "none"}.')
    if len(filters) > MAX_FILTERS or any(not isinstance(value, (str, int, float)) or len(str(value)) > 140
                                         for value in filters.values()):
        frappe.throw(f'Give at most {MAX_FILTERS} filters, each a text or number of at most 140 characters.')
    conditions = [[field, 'like', like(str(value))] if is_text(meta, field) else [field, '=', value]
                  for field, value in filters.items()]
    conditions += [[field, 'in' if isinstance(value, list) else '=', value] for field, value in config['fixed_filters'].items()]
    text_fields = [field for field in config['share_fields'] if is_text(meta, field)]
    if query and not text_fields:
        frappe.throw(f'{business_type} has no text share field to search by query.')
    rows = frappe.get_all(business_type, filters=conditions, fields=config['share_fields'],
                          or_filters=[[field, 'like', like(query)] for field in text_fields] if query else None,
                          order_by=f'{config["share_fields"][0]} asc', limit_page_length=min(int(limit), MAX_LIMIT))
    return {'business_type': business_type, 'items': rows}
