"""Team membership and assignment enforce the same boundary in Desk and APIs."""
import frappe
from relay_core.business_access import document_name
from relay_core import features
from relay_core.permissions import require_access, readable_contact, sees_all_teams, ALL_TEAMS_ROLES
from relay_core.team_access import ACCESS, ALL, GROUP, RECORD, group_field

MAX_BUSINESS_ROWS = 5000


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
    validate_business(doc.get('business_access') or [])


def validate_business(rows):
    """Each row gives all records of an enabled type, one group of its first grouping field or one record."""
    if not rows:
        return
    if len(rows) > MAX_BUSINESS_ROWS:
        frappe.throw(f'A team can have at most {MAX_BUSINESS_ROWS} business rows')
    enabled = set(frappe.get_all('Relay Contact Type', filters={'enabled': 1}, pluck='business_doctype'))
    seen, picked = set(), {}
    for row in rows:
        if row.business_doctype not in enabled:
            frappe.throw('Choose an enabled business type')
        if row.access not in ACCESS:
            frappe.throw('Business access must be All records, Group or Record')
        validate_row(row)
        if (row.business_doctype, row.access, row.value) in seen:
            frappe.throw('A group or record can only appear once in a team')
        seen.add((row.business_doctype, row.access, row.value))
        if row.access == RECORD:
            picked.setdefault(row.business_doctype, set()).add(row.value)
    whole = {doctype for doctype, access, value in seen if access == ALL}
    if any(doctype in whole and access != ALL for doctype, access, value in seen):
        frappe.throw('A business type with all records cannot also pick groups or records')
    for doctype, names in picked.items():
        missing = names - set(frappe.get_all(doctype, filters={'name': ['in', list(names)]}, pluck='name'))
        if missing:
            frappe.throw(f'Unknown {doctype}: {", ".join(sorted(missing)[:5])}')


def validate_row(row):
    if row.access == ALL:
        row.value, row.grouping_field = '', ''
        return
    if not isinstance(row.value, str) or not row.value.strip() or len(row.value) > 140:
        frappe.throw('Choose a group or record of at most 140 characters')
    if row.access == RECORD:
        row.grouping_field = ''
        return
    field = group_field(row.business_doctype)
    if not field:
        frappe.throw(f'{row.business_doctype} has no grouping field. Pick records instead.')
    if row.get('grouping_field') and row.grouping_field != field:
        frappe.throw(f'The grouping field of {row.business_doctype} changed. Pick its groups again.')
    row.grouping_field = field


def validate_assignment(doc):
    require_access('Relay Conversation Assignment', 'write')
    readable_contact(doc.relay_contact)
    if doc.team:
        team = frappe.get_doc('Relay Team', doc.team); team.check_permission('read')
    if doc.assigned_to:
        validate_agent(doc.assigned_to)
        if doc.team and features.is_enabled('teams') and not any(row.user == doc.assigned_to for row in team.members):
            frappe.throw('The assigned agent must belong to the selected team')


@frappe.whitelist(methods=['GET'])
def directory(query='', after=None):
    require_access(manage=True)
    if not isinstance(query, str) or len(query) > 80:
        frappe.throw('Invalid team search')
    filters = {'title': ['like', '%' + query.replace('%','\\%').replace('_','\\_') + '%']}
    if after: filters['name'] = ['>', after]
    rows = frappe.get_list('Relay Team', filters=filters, fields=['name','title'], order_by='name asc', page_length=31)
    summarize(rows[:30])
    return {'items': rows[:30], 'next': rows[29].name if len(rows)>30 else None,
            'teams_enabled': features.is_enabled('teams')}


def summarize(rows):
    """Add each team's members and, per business type, whether it has all records and how many groups or records."""
    names = [row.name for row in rows] or ['']
    members, business = {}, {}
    for row in frappe.get_all('Relay Team Member', filters={'parenttype': 'Relay Team', 'parent': ['in', names]},
                              fields=['parent', 'user'], order_by='idx asc', limit=0):
        members.setdefault(row.parent, []).append(row.user)
    for row in frappe.get_all('Relay Team Business', filters={'parenttype': 'Relay Team', 'parent': ['in', names]},
                              fields=['parent', 'business_doctype', 'access', {'COUNT': 'name', 'as': 'total'}],
                              group_by='parent, business_doctype, access', order_by='parent asc', limit=0):
        summary = business.setdefault(row.parent, {}).setdefault(row.business_doctype, {
            'business_doctype': row.business_doctype, 'all': False, 'groups': 0, 'records': 0})
        if row.access == ALL: summary['all'] = True
        else: summary['groups' if row.access == GROUP else 'records'] = row.total
    for row in rows:
        row['members'] = members.get(row.name, [])
        row['business'] = list(business.get(row.name, {}).values())


@frappe.whitelist(methods=['GET'])
def agents(query=''):
    require_access(manage=True)
    if not isinstance(query,str) or len(query)>80: frappe.throw('Invalid user search')
    query = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return _agent_options(query)


def managers(user):
    """Administrator and the holders of a role that sees every team, as a condition on the User table."""
    role=frappe.qb.DocType('Has Role')
    holders=frappe.qb.from_(role).select(role.parent).where(
        (role.parenttype=='User') & role.role.isin(list(ALL_TEAMS_ROLES)))
    return (user.name=='Administrator') | user.name.isin(holders)


def team_members(teams):
    """The users of `teams`, a list of team names or a subquery of them."""
    member=frappe.qb.DocType('Relay Team Member')
    return frappe.qb.from_(member).select(member.user).where((member.parenttype=='Relay Team') & member.parent.isin(teams))


def user_teams(user):
    """The teams `user` belongs to, as a subquery."""
    mine=frappe.qb.DocType('Relay Team Member').as_('mine')
    return frappe.qb.from_(mine).select(mine.parent).where((mine.user==user) & (mine.parenttype=='Relay Team'))


def teams_limit(user):
    """Teams are on and `user` does not see every team, so colleagues are their teammates and managers."""
    return features.is_enabled('teams') and not sees_all_teams(user)


def colleagues_of(user, users):
    """The users among `users` that `user` may pick as colleagues on a ticket without a chat."""
    if not users or not teams_limit(user):
        return set(users)
    table=frappe.qb.DocType('User')
    return set(frappe.qb.from_(table).select(table.name).where(
        table.name.isin(list(users)) & (managers(table) | table.name.isin(team_members(user_teams(user))))).run(pluck=True))


def _agent_options(query, contact=None, colleague_of=None):
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
        allowed=managers(user)
        if assignment.get('assigned_to'):
            allowed=allowed | (user.name==assignment['assigned_to'])
        if assignment.get('team'):
            allowed=allowed | user.name.isin(team_members([assignment['team']]))
        condition=condition & allowed
    if colleague_of and teams_limit(colleague_of):
        condition=condition & (managers(user) | user.name.isin(team_members(user_teams(colleague_of))))
    rows=(frappe.qb.from_(user).select(user.name,user.full_name)
        .where(condition & (user.name.like('%'+query+'%') | user.full_name.like('%'+query+'%')))
        .orderby(user.name).limit(30).run(as_dict=True))
    return rows



@frappe.whitelist(methods=['POST'])
def save(title, members, name=None, business=None):
    """Business rows left out stay unchanged."""
    if name is not None and name != "":
        document_name(name)
    require_access(manage=True)
    members=user_list(members,'Invalid team members')
    doc=frappe.get_doc('Relay Team',name) if name else frappe.new_doc('Relay Team')
    doc.title=title;doc.set('members',[{'user':user} for user in members])
    if business is not None:
        doc.set('business_access', business_rows(business))
    doc.save()
    return team_payload(doc)


def business_rows(value):
    rows = frappe.parse_json(value) if isinstance(value, str) else value
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        frappe.throw('Business access must be a list of rows')
    return [{'business_doctype': row.get('business_doctype'), 'access': row.get('access'), 'value': row.get('value') or ''}
            for row in rows]


def user_list(value, message):
    if isinstance(value,str): value=frappe.parse_json(value)
    if not isinstance(value,list) or any(not isinstance(user,str) for user in value): frappe.throw(message)
    return value


def team_payload(doc):
    return {'name':doc.name,'title':doc.title,'members':[row.user for row in doc.members],
            'business':[{'business_doctype':row.business_doctype,'access':row.access,'value':row.value or ''}
                        for row in doc.get('business_access') or []]}


@frappe.whitelist(methods=['GET'])
def read(name):
    document_name(name)
    require_access(manage=True)
    doc=frappe.get_doc('Relay Team',name);doc.check_permission('read')
    return team_payload(doc)


@frappe.whitelist(methods=['POST'])
def assign(contact, team=None, assigned_to=None):
    require_access('Relay Conversation Assignment', 'write')
    readable_contact(contact)
    name=frappe.db.get_value('Relay Conversation Assignment',{'relay_contact':contact},'name')
    doc=frappe.get_doc('Relay Conversation Assignment',name) if name else frappe.new_doc('Relay Conversation Assignment')
    if (doc.assigned_to or None)!=(assigned_to or None):
        doc.assigned_by=frappe.session.user if assigned_to else None
    doc.relay_contact=contact;doc.assigned_to=assigned_to or None
    # While teams are off the team stays as set in Desk, so team visibility does not change.
    if features.is_enabled('teams'):doc.team=team or None
    doc.save()
    from relay_core.queue_counts import invalidate
    invalidate()
    return {'contact':contact,'team':doc.team,'assigned_to':doc.assigned_to,'assigned_by':doc.assigned_by}


def readable_filter_team(name):
    document_name(name)
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
