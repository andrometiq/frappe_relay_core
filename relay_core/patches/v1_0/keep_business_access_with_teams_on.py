import frappe
from relay_core.permissions import MANAGER, USER
from relay_core.team_access import ALL, coverage

MAX_MEMBERS = 100


def execute():
    """Teams now limit business records. Where Teams are already on, each Relay user whose teams give no records gets
    a team with all records of the business types assigned to them today, so they keep what they see."""
    from relay_core import features
    if not features.is_enabled('teams'):
        return
    for types, users in assigned_users().items():
        for start in range(0, len(users), MAX_MEMBERS):
            add_team(types, users[start:start + MAX_MEMBERS], start // MAX_MEMBERS + 1)


def assigned_users() -> dict:
    """{assigned enabled business types: users} of enabled Relay users that Teams would limit and that no team covers."""
    candidates = holders([USER]) - holders([MANAGER, 'System Manager']) - {'Administrator'}
    enabled = set(frappe.get_all('User', filters={'enabled': 1, 'name': ['in', list(candidates) or ['']]}, pluck='name'))
    types = set(frappe.get_all('Relay Contact Type', filters={'enabled': 1}, pluck='business_doctype'))
    assigned = {}
    for row in frappe.get_all('Relay Contact Type User', filters={'parenttype': 'Relay Contact Type', 'parentfield': 'users'},
                              fields=['user', 'parent']):
        if row.user in enabled and row.parent in types:
            assigned.setdefault(row.user, set()).add(row.parent)
    groups = {}
    for user in sorted(assigned):
        if not coverage(user):
            groups.setdefault(tuple(sorted(assigned[user])), []).append(user)
    return groups


def holders(roles: list) -> set:
    return set(frappe.get_all('Has Role', filters={'parenttype': 'User', 'role': ['in', roles]}, pluck='parent'))


def add_team(types: tuple, users: list, part: int):
    title = ' and '.join(types)[:80] + ' access' + (f' {part}' if part > 1 else '')
    frappe.get_doc({'doctype': 'Relay Team', 'title': title, 'members': [{'user': user} for user in users],
                    'business_access': [{'business_doctype': doctype, 'access': ALL} for doctype in types]}).insert(
        ignore_permissions=True)
