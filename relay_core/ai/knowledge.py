"""Standing owner instructions, stored separately from facts and conversation memory."""
import frappe
from relay_core import ai_features
from relay_core.permissions import require_access
from relay_core.business_access import document_name

DOCTYPE = 'Relay AI Knowledge'
FIELDS = ('title', 'enabled', 'company', 'business_doctype', 'instructions')


def prompt(business, company):
    rows = frappe.get_all(DOCTYPE, filters={'enabled': 1}, fields=['name', *FIELDS],
                          order_by='name asc', limit_page_length=101)
    if len(rows) > 100:
        raise ValueError('Too many knowledge instructions; consolidate the knowledge base')
    selected = [row for row in rows if (not row.company or row.company == company)
                and (not row.business_doctype or row.business_doctype == business[0])]
    text = '\n\n'.join(f'{row.title}\n{row.instructions}' for row in selected)
    if len(text) > 8000:
        raise ValueError('Knowledge instructions exceed the 8000 character prompt budget')
    return text


@frappe.whitelist(methods=['GET'])
@ai_features.required
def directory(after=None):
    require_access(DOCTYPE)
    rows = frappe.get_list(DOCTYPE, filters={'name': ['>', after]} if after else {},
        fields=['name', *FIELDS], order_by='name asc', page_length=31)
    return {'items': rows[:30], 'next': rows[29].name if len(rows) > 30 else None}


@frappe.whitelist(methods=['POST'])
@ai_features.required
def save(values, name=None):
    require_access(DOCTYPE, 'write')
    if name:
        document_name(name)
    values = frappe.parse_json(values) if isinstance(values, str) else values
    if not isinstance(values, dict) or set(values) - set(FIELDS):
        raise ValueError('Invalid knowledge fields')
    doc = frappe.get_doc(DOCTYPE, name) if name else frappe.new_doc(DOCTYPE)
    doc.update(values)
    doc.save()
    return {'name': doc.name}
