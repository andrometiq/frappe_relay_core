"""Team membership and assignment enforce the same boundary in Desk and APIs."""
import frappe
from relay_core.permissions import require_access, readable_contact, sees_all_teams, ALL_TEAMS_ROLES


def validate_agent(user):
    if not isinstance(user, str) or not frappe.db.get_value('User', user, 'enabled'):
        frappe.throw('Choose an enabled user')
    if not frappe.has_permission('Relay Contact', 'read', user=user):
        frappe.throw('The user needs a Relay communication role')


def validate_team(doc):
    require_access(manage=True)
    if not isinstance(doc.title, str) or not doc.title.strip() or len(doc.title) > 100:
        frappe.throw('Team name must contain 1–100 characters')
    if not doc.members or len(doc.members) > 100:
        frappe.throw('A team needs between 1 and 100 members')
    seen = set()
    for member in doc.members:
        validate_agent(member.user)
        if member.user in seen:
            frappe.throw('A user can only appear once in a team')
        seen.add(member.user)
    from relay_core.hub_channels import TEAM_DEFAULTS
    for medium, field in TEAM_DEFAULTS.items():
        if doc.get(field) and frappe.db.get_value('Relay Channel', doc.get(field), 'channel') != medium:
            frappe.throw(f'The default {medium} channel must be a {medium} channel')


def validate_assignment(doc):
    require_access('Relay Conversation Assignment', 'write')
    readable_contact(doc.relay_contact)
    if doc.team:
        team = frappe.get_doc('Relay Team', doc.team); team.check_permission('read')
    if doc.assigned_to:
        validate_agent(doc.assigned_to)
        if doc.team and not any(row.user == doc.assigned_to for row in team.members):
            frappe.throw('The assigned agent must belong to the selected team')


@frappe.whitelist(methods=['GET'])
def directory(query='', after=None):
    require_access(manage=True)
    if not isinstance(query, str) or len(query) > 80:
        frappe.throw('Invalid team search')
    filters = {'title': ['like', '%' + query.replace('%','\\%').replace('_','\\_') + '%']}
    if after: filters['name'] = ['>', after]
    rows = frappe.get_list('Relay Team', filters=filters, fields=['name','title'], order_by='name asc', page_length=31)
    return {'items': rows[:30], 'next': rows[29].name if len(rows)>30 else None}


@frappe.whitelist(methods=['GET'])
def agents(query=''):
    require_access(manage=True)
    if not isinstance(query,str) or len(query)>80: frappe.throw('Invalid user search')
    query = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return _agent_options(query)


def _agent_options(query, contact=None):
    """Filter candidates in SQL before applying the bounded search window."""
    user=frappe.qb.DocType('User');role=frappe.qb.DocType('Has Role')
    from frappe.permissions import get_doctype_roles
    roles=frappe.qb.from_(role).select(role.parent).where(
        (role.parenttype=='User') & role.role.isin(get_doctype_roles('Relay Contact')))
    condition=(user.enabled==1) & user.name.isin(roles)
    if contact:
        from relay_core.permissions import readable_contact
        readable_contact(contact)
        assignment=frappe.db.get_value('Relay Conversation Assignment',{'relay_contact':contact},['team','assigned_to'],as_dict=True) or {}
        managers=frappe.qb.from_(role).select(role.parent).where(
            (role.parenttype=='User') & role.role.isin(list(ALL_TEAMS_ROLES)))
        allowed=(user.name=='Administrator') | user.name.isin(managers)
        if assignment.get('assigned_to'):
            allowed=allowed | (user.name==assignment['assigned_to'])
        if assignment.get('team'):
            member=frappe.qb.DocType('Relay Team Member')
            members=frappe.qb.from_(member).select(member.user).where(
                (member.parent==assignment['team']) & (member.parenttype=='Relay Team'))
            allowed=allowed | user.name.isin(members)
        condition=condition & allowed
    rows=(frappe.qb.from_(user).select(user.name,user.full_name)
        .where(condition & (user.name.like('%'+query+'%') | user.full_name.like('%'+query+'%')))
        .orderby(user.name).limit(30).run(as_dict=True))
    return rows



@frappe.whitelist(methods=['POST'])
def save(title, members, name=None):
    require_access(manage=True)
    members=user_list(members,'Invalid team members')
    doc=frappe.get_doc('Relay Team',name) if name else frappe.new_doc('Relay Team')
    doc.title=title;doc.set('members',[{'user':user} for user in members])
    doc.save()
    return team_payload(doc)


def user_list(value, message):
    if isinstance(value,str): value=frappe.parse_json(value)
    if not isinstance(value,list) or any(not isinstance(user,str) for user in value): frappe.throw(message)
    return value


def team_payload(doc):
    return {'name':doc.name,'title':doc.title,'members':[row.user for row in doc.members]}


@frappe.whitelist(methods=['GET'])
def read(name):
    require_access(manage=True)
    doc=frappe.get_doc('Relay Team',name);doc.check_permission('read')
    return team_payload(doc)


@frappe.whitelist(methods=['POST'])
def assign(contact, team=None, assigned_to=None):
    require_access('Relay Conversation Assignment', 'write')
    readable_contact(contact)
    name=frappe.db.get_value('Relay Conversation Assignment',{'relay_contact':contact},'name')
    doc=frappe.get_doc('Relay Conversation Assignment',name) if name else frappe.new_doc('Relay Conversation Assignment')
    doc.relay_contact=contact;doc.team=team or None;doc.assigned_to=assigned_to or None;doc.save()
    from relay_core.queue_counts import invalidate
    invalidate()
    return {'contact':contact,'team':doc.team,'assigned_to':doc.assigned_to}


def readable_filter_team(name):
    require_access()
    doc = frappe.get_doc('Relay Team', name)
    user = frappe.session.user
    if not doc.has_permission('read') and not any(row.user == user for row in doc.members):
        frappe.throw('This team is not available to you', frappe.PermissionError)
    return doc


@frappe.whitelist(methods=['GET'])
def filter_options(query=''):
    """Expose only team labels; membership and assignment editing remain manager-only."""
    require_access()
    if not isinstance(query, str) or len(query) > 80:
        frappe.throw('Invalid team search')
    team = frappe.qb.DocType('Relay Team')
    member = frappe.qb.DocType('Relay Team Member')
    search = frappe.qb.from_(team).select(team.name, team.title).where(team.title.like('%' + query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'))
    if not sees_all_teams():
        search = search.where(team.name.isin(frappe.qb.from_(member).select(member.parent).where((member.user == frappe.session.user) & (member.parenttype == 'Relay Team'))))
    return [{'value': row.name, 'label': row.title} for row in search.orderby(team.name).limit(30).run(as_dict=True)]
