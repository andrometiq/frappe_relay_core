"""Plain-text event editor; richer sources remain available in the existing Desk form."""
import frappe
from relay_core import ai_features
from relay_core.permissions import require_access
from relay_core.business_access import document_name

FIELDS = ('title', 'enabled', 'company', 'description', 'event_starts_on', 'event_ends_on',
          'available_from', 'available_to')


@frappe.whitelist(methods=['GET'])
@ai_features.required
def directory(after=None):
    require_access('Relay AI Event')
    rows = frappe.get_list('Relay AI Event', filters={'name': ['>', after]} if after else {},
        fields=['name', *FIELDS, 'memory_status'], order_by='name asc', page_length=31)
    for row in rows[:30]:
        doc = frappe.get_doc('Relay AI Event', row.name)
        doc.check_permission('read')
        row.audience = [entry.business_doctype for entry in doc.audience]
    return {'items': rows[:30], 'next': rows[29].name if len(rows) > 30 else None}


@frappe.whitelist(methods=['POST'])
@ai_features.required
def save(values, name=None):
    require_access('Relay AI Event', 'write')
    if name:
        document_name(name)
    values = frappe.parse_json(values) if isinstance(values, str) else values
    if not isinstance(values, dict) or set(values) - {*FIELDS, 'audience'}:
        raise ValueError('Invalid event fields')
    audience = values.get('audience', [])
    if not isinstance(audience, list) or not 1 <= len(audience) <= 20 or any(not isinstance(v, str) for v in audience):
        raise ValueError('Choose 1–20 audience business types')
    doc = frappe.get_doc('Relay AI Event', name) if name else frappe.new_doc('Relay AI Event')
    doc.update({key: value for key, value in values.items() if key != 'audience'})
    doc.set('audience', [{'business_doctype': value} for value in audience])
    doc.save()
    return {'name': doc.name}
