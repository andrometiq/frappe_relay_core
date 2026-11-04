import frappe

from relay_core.ai.playbooks import DOCTYPE, applies, global_text

LEGACY = 'Relay AI Knowledge'
FIELDS = ['name', 'title', 'enabled', 'company', 'business_doctype', 'instructions', 'migrated_to']


def execute():
    """Copy each standing instruction to a global desk playbook named `desk/<old name>`, then prove that the row
    count and every prompt are unchanged. The patch runner rolls the whole move back when the proof fails."""
    rows = frappe.get_all(LEGACY, fields=FIELDS, order_by='name asc', limit_page_length=0)
    pending = [row for row in rows if not row.migrated_to]
    if not pending:
        return
    expected = {pair: outcome(legacy_text, rows, *pair) for pair in scopes(rows)}
    for row in pending:
        key = f'desk/{row.name}'
        if not frappe.db.exists(DOCTYPE, key):
            # An empty string keeps a blank scope blank; None would take the user's default company on insert.
            frappe.get_doc({'doctype': DOCTYPE, 'playbook_key': key, 'title': row.title, 'enabled': row.enabled or 0,
                            'company': row.company or '', 'business_doctype': row.business_doctype or '',
                            'instructions': row.instructions, 'is_global': 1, 'audience': 'customer',
                            'is_system_generated': 0}).insert(ignore_permissions=True)
        frappe.db.set_value(LEGACY, row.name, 'migrated_to', key, update_modified=False)
    moved = frappe.db.count(LEGACY, {'migrated_to': ['is', 'set']})
    if moved != len(rows):
        raise AssertionError(f'Moved {moved} of {len(rows)} knowledge instructions')
    for pair, text in expected.items():
        if outcome(global_text, *pair) != text:
            raise AssertionError(f'The playbook prompt differs from the knowledge prompt for {pair}')


def scopes(rows) -> set:
    """One (business, company) pair per combination of row scopes, plus pairs that match no scoped row."""
    companies = {row.company for row in rows if row.company} | {''}
    doctypes = {row.business_doctype for row in rows if row.business_doctype} | {''}
    return {((doctype, ''), company) for doctype in doctypes for company in companies}


def legacy_text(rows, business, company) -> str:
    """What `knowledge.prompt` returned before the move."""
    enabled = [row for row in rows if row.enabled]
    if len(enabled) > 100:
        raise ValueError('Too many knowledge instructions')
    text = '\n\n'.join(f'{row.title}\n{row.instructions}' for row in enabled if applies(row, business, company))
    if len(text) > 8000:
        raise ValueError('Knowledge instructions are too long')
    return text


def outcome(build, *args) -> str | None:
    """The prompt, or None where it refuses to build (too many rows or too much text)."""
    try:
        return build(*args)
    except ValueError:
        return None
