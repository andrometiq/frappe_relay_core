"""Plain users' inbox rows and queue counts equal the conversations the per-contact check allows.

Runs on RELAY_TEST_SITE (default yrp.site) inside one transaction that is always rolled back."""
import os
import sys

import frappe

SITE = os.environ.get('RELAY_TEST_SITE', 'yrp.site')
SITES = os.environ.get('SITES_PATH', '/home/sakthi/development/pilot/benches/version_16/sites')
MODES = ('all', 'mine', 'unread', 'unassigned')
PLAIN_ROLES = ['Sales User', 'Purchase User']


class Fixtures:
    """Hook-free inserts so no document event can commit; the caller rolls back."""

    def __init__(self):
        self.tag = 'zz-inbox-rows-' + frappe.generate_hash(length=6)
        self.count = 0

    def insert(self, doctype, **values):
        self.count += 1
        now = frappe.utils.now()
        values = {'name': f'{self.tag}-{self.count}', **values, 'creation': now, 'modified': now,
                  'owner': 'Administrator', 'modified_by': 'Administrator', 'docstatus': 0}
        columns = ','.join(f'`{column}`' for column in values)
        frappe.db.sql(f"insert into `tab{doctype}` ({columns}) values ({','.join(['%s'] * len(values))})", list(values.values()))
        return values['name']

    def user(self, key, roles):
        name = f'{self.tag}-{key}@example.invalid'
        self.insert('User', name=name, email=name, first_name=key, enabled=1, user_type='System User')
        for index, role in enumerate(roles + PLAIN_ROLES, 1):
            self.insert('Has Role', parent=name, parenttype='User', parentfield='roles', role=role, idx=index)
        return name

    def team(self, members=()):
        team = self.insert('Relay Team', title=self.tag + '-team-' + str(self.count))
        for index, user in enumerate(members, 1):
            self.insert('Relay Team Member', parent=team, parenttype='Relay Team', parentfield='members', user=user, idx=index)
        return team


def build(fixtures):
    from relay_core.business_groups import key
    users = {'team': fixtures.user('team', ['WhatsApp User']), 'restricted': fixtures.user('restricted', ['WhatsApp User']),
             'multi': fixtures.user('multi', ['WhatsApp Multi-Channel User']), 'claim': fixtures.user('claim', ['WhatsApp User']),
             'none': fixtures.user('none', [])}
    rows = frappe.db.sql("""select r.name, group_concat(l.link_name) from `tabRelay Contact` r
        left join `tabDynamic Link` l on l.parent=r.contact and l.parenttype='Contact' and l.link_doctype='Customer'
        group by r.name order by coalesce(r.last_message_at, r.creation) desc limit 300""")
    contacts = [row[0] for row in rows]
    assert len(contacts) >= 100, 'The site needs at least 100 Relay Contacts'
    frappe.db.delete('Relay Conversation Assignment', {'relay_contact': ['in', contacts]})
    shared = fixtures.team(members=[users['team'], users['restricted']])
    own = fixtures.team(members=[users['multi']])
    other = fixtures.team()
    plan = ([(shared, None)] * 40 + [(shared, 'someone@example.invalid')] * 15 + [(own, users['team'])] * 15
            + [(own, None)] * 15 + [(other, None)] * 15)
    for contact, (team, assigned_to) in zip(contacts, plan, strict=False):
        fixtures.insert('Relay Conversation Assignment', relay_contact=contact, team=team, assigned_to=assigned_to)
    # Business-link-only access: the claim user owns the largest customer group.
    frappe.db.set_value('Relay Contact Type', {'business_doctype': 'Customer'}, 'grouping_field', 'customer_group', update_modified=False)
    group = frappe.db.sql("""select c.customer_group from `tabRelay Contact` r join `tabDynamic Link` l on l.parent=r.contact
        and l.parenttype='Contact' and l.link_doctype='Customer' join tabCustomer c on c.name=l.link_name
        where c.customer_group is not null group by 1 order by count(*) desc limit 1""")
    if group:
        claim = key('Customer', 'customer_group', group[0][0])
        fixtures.insert('Relay Business Group Claim', name=claim, claim_key=claim, business_doctype='Customer',
                        grouping_field='customer_group', group_value=group[0][0], assigned_to=users['claim'])
    # User permissions narrow the restricted user to half of its team's customers.
    customers = sorted({name for row in rows[:55] if row[1] for name in row[1].split(',')})[::2]
    for customer in customers:
        fixtures.insert('User Permission', user=users['restricted'], allow='Customer', for_value=customer, apply_to_all_doctypes=1)
    return users, contacts


def directory_rows(medium, mode):
    from relay_core import inbox
    rows, after = [], None
    while True:
        page = inbox.directory(mode=mode, medium=medium, **({'after': after} if after else {}))
        rows += page['items']
        if not page['next']:
            return rows
        after = page['next']['after']


def denied(call):
    try:
        call()
    except frappe.PermissionError:
        return True
    return False


def check_user(name, user, contacts):
    from relay_core import inbox, queue_counts
    from relay_core.permissions import readable_contact
    frappe.set_user(user)
    readable = {}

    def allowed(contact):
        if contact not in readable:
            readable[contact] = not denied(lambda: readable_contact(contact))
        return readable[contact]
    for medium in (None, 'WhatsApp'):
        listed = {mode: directory_rows(medium, mode) for mode in MODES}
        names = {row['name'] for row in listed['all']}
        assert all(allowed(contact) for contact in names), f'{name}: a listed conversation fails the per-contact check'
        assert all(allowed(contact) == (contact in names) for contact in contacts if not medium), f'{name}: rows differ from the per-contact check'
        assert {row['name'] for mode in MODES for row in listed[mode]} <= names
        if not medium:
            assert all(row['unread'] == inbox.read(row['name'])['unread'] for row in listed['all'][:10])
        counts = queue_counts.get_counts(medium)
        assert {mode: counts[mode] for mode in MODES} == {mode: len(listed[mode]) for mode in MODES}, f'{name}: counts differ from rows'
        print(f'PASS {name} {medium or "all channels"}: ' + ' '.join(f'{mode}={len(listed[mode])}' for mode in MODES))
    return names


def main():
    frappe.init(site=SITE, sites_path=SITES)
    frappe.connect()

    def refuse_commit(*args, **kwargs):
        raise AssertionError('This test must not commit')
    frappe.db.commit = refuse_commit
    fixtures = Fixtures()
    users = {}
    try:
        users, contacts = build(fixtures)
        frappe.clear_cache(doctype='Relay Contact Type')
        visible = {name: check_user(name, user, contacts) for name, user in users.items() if name != 'none'}
        assert visible['team'] and visible['multi'] and visible['claim'], 'Every scenario must show some conversations'
        assert visible['restricted'] < visible['team'], 'User permissions must narrow the team rows'
        assert visible['multi'] - visible['team'], 'Viewer access must add the shared team without its members'
        frappe.set_user(users['none'])
        from relay_core import inbox, queue_counts
        assert denied(inbox.directory) and denied(queue_counts.read)
        print('PASS a user without a Relay role is denied rows and counts')
    finally:
        frappe.set_user('Administrator')
        frappe.db.rollback()
        frappe.clear_cache(doctype='Relay Contact Type')
        for user in users.values():
            frappe.clear_cache(user=user)
        assert not frappe.db.exists('User', {'name': ['like', fixtures.tag + '%']})
        print('CLEANUP rolled back; no fixture rows remain')
        frappe.destroy()


if __name__ == '__main__':
    sys.exit(main())
