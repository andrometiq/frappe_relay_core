"""The persona: one name and voice for customer replies, used by external agents and the Relay AI alike.

It works while AI features are off. One per company; a persona without company covers every other company."""
import frappe

from relay_core.business_access import document_name
from relay_core.permissions import require_access

DOCTYPE = 'Relay AI Persona'
FIELDS = ('persona_name', 'enabled', 'company', 'instructions')
MAX_INSTRUCTIONS = 4000


def find(company=None, reader=None):
    """The enabled persona of the company, else the one for every company, or None. `reader` decides permissions."""
    reader = reader or frappe.get_all
    for scope in ([company] if company else []) + [['is', 'not set']]:
        rows = reader(DOCTYPE, filters={'enabled': 1, 'company': scope}, fields=['name', *FIELDS], limit_page_length=1)
        if rows:
            return rows[0]
    return None


def prompt(company) -> str:
    """The persona text of the internal AI reply prompt; empty without one."""
    row = find(company)
    return f'Name: {row.persona_name}\n{row.instructions or ""}'.strip() if row else ''


@frappe.whitelist(methods=['GET'])
def directory():
    require_access(DOCTYPE)
    rows = frappe.get_list(DOCTYPE, fields=['name', *FIELDS], order_by='company asc, name asc', page_length=100)
    return {'items': rows, 'next': None}


@frappe.whitelist(methods=['POST'])
def save(values, name=None):
    require_access(DOCTYPE, 'write')
    values = frappe.parse_json(values) if isinstance(values, str) else values
    if not isinstance(values, dict) or set(values) - set(FIELDS):
        raise ValueError('Invalid persona fields')
    if name:
        doc = frappe.get_doc(DOCTYPE, document_name(name))
    else:
        # A blank company means every company; it must not take the user's default company.
        doc = frappe.new_doc(DOCTYPE)
        values = {'company': '', **values}
    doc.update(values)
    doc.save()
    return {'name': doc.name}
