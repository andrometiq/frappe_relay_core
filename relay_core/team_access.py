"""Team record scope. While Teams are on, a Relay Communication User reaches only the records their teams cover.

A team covers all records of a business type, the records in picked groups of the type's first grouping field,
or picked records. Managers, System Managers and read-only users are never limited. business_access applies this scope.
"""
import frappe

ALL = 'All records'
GROUP = 'Group'
RECORD = 'Record'
ACCESS = (ALL, GROUP, RECORD)


def restricted(user: str) -> bool:
    from relay_core import features
    from relay_core.permissions import can_manage, is_read_only
    return not can_manage(user) and not is_read_only(user, frappe.get_roles(user)) and features.is_enabled('teams')


def coverage(user: str) -> dict:
    """{business type: access kinds} over the user's teams."""
    rows = frappe.db.sql("""SELECT DISTINCT b.business_doctype, b.access FROM `tabRelay Team Business` b
        JOIN `tabRelay Team Member` m ON m.parent=b.parent AND m.parenttype='Relay Team'
        WHERE b.parenttype='Relay Team' AND m.user=%s""", user)
    result = {}
    for doctype, access in rows:
        result.setdefault(doctype, set()).add(access)
    return result


def group_field(doctype: str) -> str:
    """The grouping field that team groups use: the type's first configured level."""
    from relay_core.business_groups import configuration
    return next(iter(configuration(doctype)), '')


def covered_query(doctype: str, user: str):
    """SQL for the names of `doctype` records the user's teams cover, or None when no team limit applies."""
    if not restricted(user):
        return None
    kinds = coverage(user).get(doctype, set())
    if ALL in kinds:
        return None
    from relay_core.business_groups import identifier
    table = identifier('tab' + doctype)
    picked = (f"SELECT tb.value FROM `tabRelay Team Business` tb JOIN `tabRelay Team Member` tm ON tm.parent=tb.parent "
              f"AND tm.parenttype='Relay Team' WHERE tb.parenttype='Relay Team' AND tm.user={frappe.db.escape(user)} "
              f"AND tb.business_doctype={frappe.db.escape(doctype)}")
    parts = []
    if RECORD in kinds:
        parts.append(f"SELECT tr.name FROM {table} tr WHERE tr.name IN ({picked} AND tb.access='{RECORD}')")
    field = group_field(doctype) if GROUP in kinds else ''
    if field:
        # Groups saved under another grouping field no longer match anything.
        parts.append(f"SELECT tr.name FROM {table} tr WHERE tr.{identifier(field)} IN "
                     f"({picked} AND tb.access='{GROUP}' AND tb.grouping_field={frappe.db.escape(field)})")
    return ' UNION ALL '.join(parts) or f'SELECT tr.name FROM {table} tr WHERE 1=0'
