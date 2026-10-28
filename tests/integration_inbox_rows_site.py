"""Plain users' inbox rows and queue counts equal the conversations the per-contact check allows.

Runs on RELAY_TEST_SITE (default yrp.site) inside one transaction that is always rolled back."""
import os
import sys

import frappe

SITE = os.environ.get('RELAY_TEST_SITE', 'yrp.site')
SITES = os.environ.get('SITES_PATH', '/home/sakthi/development/pilot/benches/version_16/sites')
MODES = ('all', 'unread', 'read')
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
    users = {'team': fixtures.user('team', ['Relay Communication User']), 'restricted': fixtures.user('restricted', ['Relay Communication User']),
             'multi': fixtures.user('multi', ['Relay Communication Team User']), 'claim': fixtures.user('claim', ['Relay Communication User']),
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


def directory_rows(medium, mode, **filters):
    from relay_core import inbox
    rows, after = [], None
    while True:
        page = inbox.directory(mode=mode, medium=medium, **filters, **({'after': after} if after else {}))
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
        check_counts(name, medium, listed, queue_counts.read(medium))
    return names


def check_counts(name, medium, listed, counts):
    """Counts equal the rows of each tab, and Unread and Read split All."""
    assert {mode: counts[mode] for mode in MODES} == {mode: len(listed[mode]) for mode in MODES}, f'{name}: counts differ from rows'
    unread, read = ({row['name'] for row in listed[mode]} for mode in ('unread', 'read'))
    assert not unread & read and unread | read == {row['name'] for row in listed['all']}, f'{name}: Unread and Read do not split All'
    assert all(row['unread'] for row in listed['unread']) and not any(row['unread'] for row in listed['read'])
    print(f'PASS {name} {medium or "all channels"}: ' + ' '.join(f'{mode}={len(listed[mode])}' for mode in MODES))


def check_business_rows(name, user, contacts):
    """Business rows: every record row is readable, a record the user cannot read is never shown, and counts equal rows."""
    from relay_core import queue_counts
    from relay_core.permissions import readable_contact
    frappe.set_user(user)
    listed = {mode: directory_rows('WhatsApp', mode, rows='business') for mode in ('all', 'unread', 'unlinked')}
    records = {(row['doctype'], row['record']) for row in listed['all'] if row['kind'] == 'business'}
    assert all(frappe.get_doc(*record).has_permission('read') for record in records), f'{name}: a listed record is not readable'
    assert all(not denied(lambda contact=row['name']: readable_contact(contact)) for row in listed['all'] if row['kind'] == 'contact')
    assert len(records) == len([row for row in listed['all'] if row['kind'] == 'business']), f'{name}: a record is listed twice'
    hidden = frappe.db.sql("""select distinct l.link_name from `tabRelay Contact` r join `tabDynamic Link` l on l.parent=r.contact
        and l.parenttype='Contact' and l.parentfield='links' and l.link_doctype='Customer' where r.name in %(contacts)s""", {'contacts': contacts})
    denied_records = [row[0] for row in hidden if not frappe.get_doc('Customer', row[0]).has_permission('read')]
    assert not {('Customer', record) for record in denied_records} & records, f'{name}: a record the user cannot read is listed'
    assert all(row['kind'] == 'contact' and row['unlinked'] for row in listed['unlinked'])
    counts = queue_counts.read('WhatsApp', rows='business')
    assert (counts['all'], counts['unread'], counts['unlinked']) == tuple(len(listed[mode]) for mode in ('all', 'unread', 'unlinked')), f'{name}: counts differ from rows'
    print(f'PASS {name} business rows: records={len(records)} all={len(listed["all"])} unlinked={len(listed["unlinked"])} denied records hidden={len(denied_records)}')
    return records


def check_filters(user):
    """Channel and business filters narrow rows and counts alike, alone and together."""
    from relay_core import queue_counts
    frappe.set_user(user)
    customer = frappe.db.sql("""select l.link_name from `tabRelay Contact` r join `tabDynamic Link` l on l.parent=r.contact
        and l.parenttype='Contact' and l.link_doctype='Customer' group by 1 order by count(*) desc, 1 limit 1""")[0][0]
    whatsapp = frappe.get_list('Relay Channel', filters={'channel': 'WhatsApp'}, pluck='name', limit_page_length=0)
    cases = {'customer type': {'business_type': 'Customer'}, 'one customer': {'business_type': 'Customer', 'business_name': customer},
             'no record': {'business_type': 'none'}, 'channels': {'channels': frappe.as_json(whatsapp[:2])},
             'channels and customers': {'channels': frappe.as_json(whatsapp[:2]), 'business_type': 'Customer'}}
    everything = {row['name'] for row in directory_rows(None, 'all')}
    for label, filters in cases.items():
        listed = {mode: directory_rows(None, mode, **filters) for mode in MODES}
        assert {row['name'] for row in listed['all']} <= everything
        check_counts(f'{user} {label}', None, listed, queue_counts.read(**filters))
    linked = {row['name'] for row in directory_rows(None, 'all', business_type='Customer')}
    unlinked = {row['name'] for row in directory_rows(None, 'all', business_type='none')}
    assert linked and not linked & unlinked, 'A chat with a customer is never in No record'


def chat(fixtures, customers, primary=None):
    """A Relay Contact whose Frappe Contact links to these customers."""
    person = fixtures.insert('Contact', first_name=fixtures.tag)
    for index, customer in enumerate(customers, 1):
        fixtures.insert('Dynamic Link', parent=person, parenttype='Contact', parentfield='links', link_doctype='Customer',
                        link_name=customer, idx=index)
    return fixtures.insert('Relay Contact', contact=person, display_name=fixtures.tag, primary_doctype=primary and 'Customer',
                           primary_name=primary)


def message(fixtures, contact, channel, minute, business=None):
    sent = frappe.utils.add_to_date('2030-01-01 10:00:00', minutes=minute)
    name = fixtures.insert('Relay Message', relay_contact=contact, channel=channel, direction='Incoming', content=f'{fixtures.tag} {minute}',
                           sent_at=sent, business_doctype=business and 'Customer', business_name=business)
    frappe.db.set_value('Relay Contact', contact, {'last_message': name, 'last_message_at': sent}, update_modified=False)
    return name


def record_row(customer):
    from relay_core import inbox
    rows = inbox.directory(rows='business', business_type='Customer', business_name=customer)['items']
    return next(row for row in rows if row['kind'] == 'business' and row['record'] == customer)


def check_record_ownership(fixtures):
    """A record shows the preview, activity and unread count of its own thread: unstamped history belongs only to the
    chat's primary record, and every chat counts, not only the first 20."""
    from relay_core import business_inbox
    frappe.set_user('Administrator')
    channel = frappe.get_all('Relay Channel', filters={'channel': 'WhatsApp'}, pluck='name', limit_page_length=1)[0]
    owner, other, crowded = (fixtures.insert('Customer', customer_name=fixtures.tag + suffix) for suffix in ('-owner', '-other', '-crowded'))
    shared = chat(fixtures, [owner, other], primary=owner)
    stamped = message(fixtures, shared, channel, 1, business=other)
    message(fixtures, shared, channel, 2)
    newest = message(fixtures, shared, channel, 3)
    for customer, preview, unread in ((owner, newest, 2), (other, stamped, 1)):
        thread = business_inbox.messages('Customer', customer)['items']
        row = record_row(customer)
        assert [item['name'] for item in thread][-1] == preview and len(thread) == unread, f'{customer}: unexpected thread'
        assert row['latest_preview'] == frappe.db.get_value('Relay Message', preview, 'content'), f'{customer}: preview is not from its thread'
        assert row['unread'] == unread, f'{customer}: unread {row["unread"]} differs from its thread {unread}'
    assert record_row(other)['last_message_at'].startswith('2030-01-01 10:01'), 'Unstamped history moves only its owner'
    members = [chat(fixtures, [crowded]) for _ in range(25)]
    for minute, member in enumerate(members, 10):
        message(fixtures, member, channel, minute)
    row = record_row(crowded)
    assert (row['contact_count'], row['unread']) == (25, 25), f'A record counts every chat: {row["contact_count"]}, {row["unread"]}'
    assert row['contact'] == members[-1], 'The newest chat gives the preview'
    print('PASS record previews and unread follow thread ownership; 25 chats all count')


def unread_records(customer):
    from relay_core import inbox
    rows = inbox.directory(mode='unread', rows='business', business_type='Customer', business_name=customer)['items']
    return [row['record'] for row in rows if row['kind'] == 'business']


def check_link_rules(fixtures):
    """Unstamped ownership in rows, unread tab and counts uses the thread's candidates: more than 50 raw links of any
    type give no owner, and a link whose record is gone is not a candidate."""
    from relay_core import business_inbox, queue_counts
    frappe.set_user('Administrator')
    channel = frappe.get_all('Relay Channel', filters={'channel': 'WhatsApp'}, pluck='name', limit_page_length=1)[0]
    enabled = set(frappe.get_all('Relay Contact Type', filters={'enabled': 1}, pluck='business_doctype'))
    disabled = next(doctype for doctype in ('Lead', 'Project', 'Address', 'Note') if doctype not in enabled)
    crowded, valid = (fixtures.insert('Customer', customer_name=fixtures.tag + suffix) for suffix in ('-capped', '-valid'))
    capped = chat(fixtures, [crowded], primary=crowded)
    person = frappe.db.get_value('Relay Contact', capped, 'contact')
    for index in range(2, 52):
        fixtures.insert('Dynamic Link', parent=person, parenttype='Contact', parentfield='links', link_doctype=disabled,
                        link_name=f'{fixtures.tag}-{disabled}-{index}', idx=index)
    stale = chat(fixtures, [valid, fixtures.tag + '-deleted'])
    for contact in (capped, stale):
        message(fixtures, contact, channel, 40)
    for customer, unread in ((crowded, 0), (valid, 1)):
        thread = business_inbox.messages('Customer', customer)['items']
        assert len(thread) == unread, f'{customer}: thread has {len(thread)} messages, expected {unread}'
        assert record_row(customer)['unread'] == unread, f'{customer}: row unread differs from its thread'
        assert unread_records(customer) == ([customer] if unread else []), f'{customer}: Unread tab differs from its thread'
        counts = queue_counts.read(rows='business', business_type='Customer', business_name=customer)
        assert counts['unread'] == unread, f'{customer}: unread count {counts["unread"]} differs from its thread {unread}'
    print('PASS 51 raw links give no unstamped owner; a deleted link target is not a candidate')


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
        shown = {name: check_business_rows(name, users[name], contacts) for name in ('team', 'restricted')}
        assert shown['restricted'] < shown['team'], 'User permissions must hide some of the team records'
        check_filters('Administrator')
        check_filters(users['team'])
        check_record_ownership(fixtures)
        check_link_rules(fixtures)
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
