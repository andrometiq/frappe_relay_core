"""Standing owner instructions: the global desk playbooks, behind the original knowledge API shape."""
import frappe
from frappe.model.naming import make_autoname

from relay_core import ai_features
from relay_core.ai import playbooks
from relay_core.permissions import require_access
from relay_core.business_access import document_name

DOCTYPE = playbooks.DOCTYPE
FIELDS = ('title', 'enabled', 'company', 'business_doctype', 'instructions')
STANDING = {'is_system_generated': 0, 'is_global': 1, 'audience': 'customer'}


def prompt(business, company):
    return playbooks.global_text(business, company)


@frappe.whitelist(methods=['GET'])
@ai_features.required
def directory(after=None):
    require_access(DOCTYPE)
    filters = dict(STANDING, **({'name': ['>', after]} if after else {}))
    rows = frappe.get_list(DOCTYPE, filters=filters, fields=['name', *FIELDS], order_by='name asc', page_length=31)
    return {'items': rows[:30], 'next': rows[29].name if len(rows) > 30 else None}


@frappe.whitelist(methods=['POST'])
@ai_features.required
def save(values, name=None):
    require_access(DOCTYPE, 'write')
    values = frappe.parse_json(values) if isinstance(values, str) else values
    if not isinstance(values, dict) or set(values) - set(FIELDS):
        raise ValueError('Invalid knowledge fields')
    if name:
        doc = frappe.get_doc(DOCTYPE, document_name(name))
        if any(doc.get(key) != value for key, value in STANDING.items()):
            raise ValueError('Edit this playbook in Relay AI Playbook')
    else:
        doc = frappe.new_doc(DOCTYPE)
        doc.update(dict(STANDING, playbook_key='desk/' + make_autoname('RELAY-KB-.##########')))
    doc.update(values)
    doc.save()
    return {'name': doc.name}
