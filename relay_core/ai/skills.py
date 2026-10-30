"""One owner-configured fallback; installing it grants no model or data access."""
import frappe

DEFAULT_KEY = 'relay-default-skill'


def is_default(skill):
    return skill.get('sample_key') == DEFAULT_KEY


def ensure_default():
    existing = frappe.db.get_value('Relay AI Skill', {'sample_key': DEFAULT_KEY}, 'name')
    if existing:
        return existing
    doc = frappe.get_doc(dict(doctype='Relay AI Skill', title='Default support', sample_key=DEFAULT_KEY,
        enabled=0, business_doctype='Contact', mode='Shadow', daily_limit=100,
        target='General customer support when no specific skill matches',
        instructions='Use the knowledge base for standing guidance and events for customer-facing facts. '
                     'Use configured reports for record data. If evidence is missing, hand off to staff.',
        execution_policy='Execute', search_confirmation='Always', allowed_tools='[]',
        allowed_actions='[{"action":"reply"}]'))
    doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
    return doc.name
