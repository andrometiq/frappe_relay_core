"""Who can use Relay: each person's Relay role, teams and business types.

Roles are Frappe Has Role rows, teams are Relay Team Member rows and business types are Relay Contact Type User rows.
Everyone reads their own access; communication managers read everyone's and change it.
"""
import frappe
from relay_core.permissions import MANAGER, TEAM_USER, USER, can_manage, require_access

ROLES = {'': None, 'User': USER, 'Manager': MANAGER}
RELAY_ROLES = (USER, TEAM_USER, MANAGER)
LISTED_ROLES = RELAY_ROLES + ('System Manager',)
HIDDEN_USERS = ('Administrator', 'Guest')
MAX_USERS = 500


def role_label(roles):
    if 'System Manager' in roles: return 'System Manager'
    if MANAGER in roles: return 'Manager'
    return 'User' if USER in roles else ''


def listed_users():
    """Enabled staff who hold a Relay role or System Manager, by name."""
    holders = frappe.get_all('Has Role', filters={'parenttype': 'User', 'role': ['in', LISTED_ROLES]},
                             pluck='parent', distinct=True, limit=0)
    return frappe.get_all('User', filters={'name': ['in', [*holders, '']], 'enabled': 1}, pluck='name',
                          order_by='full_name asc, name asc', limit=MAX_USERS)


def role_lock(user, profiled):
    """Why the role of this user cannot be changed here, or an empty string."""
    if user == frappe.session.user: return 'You cannot change your own role.'
    if profiled: return 'This user gets roles from a role profile. Change them in Desk.'
    return ''


def access_rows(users):
    """One row per user, read in a fixed number of queries."""
    users = [user for user in users if user not in HIDDEN_USERS]
    keys = users or ['']
    accounts = {row.name: row for row in frappe.get_all('User', filters={'name': ['in', keys]},
                                                         fields=['name', 'full_name', 'user_image'])}
    roles, teams, types = {}, {}, {}
    for row in frappe.get_all('Has Role', filters={'parenttype': 'User', 'parent': ['in', keys], 'role': ['in', LISTED_ROLES]},
                              fields=['parent', 'role'], limit=0):
        roles.setdefault(row.parent, set()).add(row.role)
    for row in frappe.get_all('Relay Team Member', filters={'parenttype': 'Relay Team', 'user': ['in', keys]},
                              fields=['parent', 'user'], order_by='parent asc', limit=0):
        teams.setdefault(row.user, []).append(row.parent)
    for row in frappe.get_all('Relay Contact Type User', filters={'parenttype': 'Relay Contact Type', 'parentfield': 'users',
                              'user': ['in', keys]}, fields=['parent', 'user'], order_by='parent asc', limit=0):
        types.setdefault(row.user, []).append(row.parent)
    profiled = set(frappe.get_all('User Role Profile', filters={'parenttype': 'User', 'parent': ['in', keys]}, pluck='parent', limit=0))
    return [{'user': user, 'full_name': accounts[user].full_name or user, 'image': accounts[user].user_image or '',
             'role': role_label(roles.get(user, set())), 'team_user': TEAM_USER in roles.get(user, set()),
             'teams': teams.get(user, []), 'business_types': types.get(user, []),
             'role_locked': role_lock(user, user in profiled)} for user in users if user in accounts]


@frappe.whitelist(methods=['GET'])
def directory():
    """Managers read everyone with Relay access; other users read only their own row."""
    require_access()
    manager = can_manage()
    users = listed_users() if manager else [frappe.session.user]
    teams = frappe.get_all('Relay Team', fields=['name', 'title'], order_by='title asc', limit=500)
    types = frappe.get_all('Relay Contact Type', fields=['business_doctype', 'label', 'enabled'], order_by='business_doctype asc', limit=200)
    return {'can_edit': manager, 'items': access_rows(users),
            'teams': [{'value': row.name, 'label': row.title or row.name} for row in teams],
            'business_types': [{'value': row.business_doctype, 'label': row.label or row.business_doctype, 'enabled': bool(row.enabled)}
                               for row in types]}


@frappe.whitelist(methods=['GET'])
def user_options(query=''):
    """Enabled staff users a manager can give Relay access to."""
    require_access(manage=True)
    if not isinstance(query, str) or len(query) > 80:
        frappe.throw('Invalid user search')
    needle = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    user = frappe.qb.DocType('User')
    rows = (frappe.qb.from_(user).select(user.name, user.full_name)
            .where((user.enabled == 1) & (user.user_type == 'System User') & user.name.notin(HIDDEN_USERS)
                   & (user.name.like(needle) | user.full_name.like(needle)))
            .orderby(user.full_name).limit(20).run(as_dict=True))
    return [{'value': row.name, 'label': row.full_name or row.name} for row in rows]


def staff_user(user):
    if not isinstance(user, str) or user in HIDDEN_USERS:
        frappe.throw('Choose a staff user')
    account = frappe.db.get_value('User', user, ['enabled', 'user_type'], as_dict=True)
    if not account or not account.enabled or account.user_type != 'System User':
        frappe.throw('Choose an enabled staff user')
    return user


def known_names(value, doctype, label):
    if isinstance(value, str):
        try:
            value = frappe.parse_json(value)
        except ValueError:
            value = None
    if not isinstance(value, list) or len(value) > 200 or any(not isinstance(item, str) or not item for item in value):
        frappe.throw(f'{label} must be a list of names')
    known = set(frappe.get_all(doctype, filters={'name': ['in', value or ['']]}, pluck='name'))
    missing = [item for item in value if item not in known]
    if missing:
        frappe.throw(f'Unknown {label.lower()}: {", ".join(missing[:5])}')
    return set(value)


def set_roles(user, role=None, team_user=None):
    """Replace the user's Relay roles; None keeps that part and other roles stay as they are."""
    doc = frappe.get_doc('User', user)
    current = {row.role for row in doc.roles}
    wanted = set(current)
    if role is not None:
        wanted -= {USER, MANAGER}
        wanted |= {ROLES[role]} - {None}
    if team_user is not None:
        wanted = wanted | {TEAM_USER} if team_user else wanted - {TEAM_USER}
    if wanted == current:
        return
    lock = role_lock(user, bool(doc.get('role_profiles')))
    if lock:
        frappe.throw(lock)
    for row in [row for row in doc.roles if row.role not in wanted]:
        doc.remove(row)
    doc.append_roles(*sorted(wanted - current))
    doc.flags.ignore_permissions = True
    doc.save()


def set_members(user, wanted, doctype, child, field):
    """Add or remove the user in each record's member table; each record keeps its own validation."""
    parents = set(frappe.get_all(child, filters={'parenttype': doctype, 'parentfield': field, 'user': user}, pluck='parent'))
    for name in sorted(wanted ^ parents):
        doc = frappe.get_doc(doctype, name)
        members = [row.user for row in doc.get(field) if row.user != user] + ([user] if name in wanted else [])
        doc.set(field, [{'user': member} for member in members])
        doc.save()


def flag(value):
    if value is None:
        return None
    if str(value) not in ('0', '1', 'True', 'False', 'true', 'false'):
        frappe.throw('Team User must be 0 or 1')
    return str(value) in ('1', 'True', 'true')


@frappe.whitelist(methods=['POST'])
def save(user, role=None, team_user=None, teams=None, business_types=None):
    """Change one user's Relay role, Team User role, teams and business types. Values left out stay unchanged."""
    require_access(manage=True)
    staff_user(user)
    if role is not None and role not in ROLES:
        frappe.throw('Role must be User, Manager or empty')
    team_user = flag(team_user)
    wanted_teams = known_names(teams, 'Relay Team', 'Teams') if teams is not None else None
    wanted_types = known_names(business_types, 'Relay Contact Type', 'Business types') if business_types is not None else None
    set_roles(user, role, team_user)
    if wanted_teams is not None:
        set_members(user, wanted_teams, 'Relay Team', 'Relay Team Member', 'members')
    if wanted_types is not None:
        set_members(user, wanted_types, 'Relay Contact Type', 'Relay Contact Type User', 'users')
    return access_rows([user])[0]
