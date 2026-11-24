"""Team record scope against local-only SQL rows, without a site."""
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from frappe import _dict
from relay_core import business_access as access, permissions, team_access


class TeamScopeTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE `tabRelay Contact Type` (business_doctype TEXT, enabled INTEGER);
            CREATE TABLE `tabRelay Contact Type User` (parent TEXT, parenttype TEXT, parentfield TEXT, user TEXT);
            CREATE TABLE `tabRelay Team Member` (parent TEXT, parenttype TEXT, user TEXT);
            CREATE TABLE `tabRelay Team Business` (parent TEXT, parenttype TEXT, business_doctype TEXT, access TEXT,
                grouping_field TEXT, value TEXT);
            CREATE TABLE `tabCustomer` (name TEXT PRIMARY KEY, customer_group TEXT);
            CREATE TABLE `tabSupplier` (name TEXT PRIMARY KEY);
            CREATE TABLE `tabContact` (name TEXT PRIMARY KEY);
            CREATE TABLE `tabDynamic Link` (parent TEXT, parenttype TEXT, parentfield TEXT, link_doctype TEXT, link_name TEXT);
            INSERT INTO `tabRelay Contact Type` VALUES ('Customer', 1), ('Supplier', 1);
            INSERT INTO `tabRelay Contact Type User` VALUES ('Supplier', 'Relay Contact Type', 'users', 'agent');
            INSERT INTO `tabCustomer` VALUES ('C-NORTH', 'North'), ('C-SOUTH', 'South'), ('C-PICKED', 'East'), ('C-OTHER', 'East');
            INSERT INTO `tabSupplier` VALUES ('S1'), ('S2');
            INSERT INTO `tabRelay Team Member` VALUES ('North sales', 'Relay Team', 'agent'), ('Buyers', 'Relay Team', 'buyer');
            INSERT INTO `tabRelay Team Business` VALUES
                ('North sales', 'Relay Team', 'Customer', 'Group', 'customer_group', 'North'),
                ('North sales', 'Relay Team', 'Customer', 'Group', 'old_field', 'South'),
                ('North sales', 'Relay Team', 'Customer', 'Record', '', 'C-PICKED'),
                ('Buyers', 'Relay Team', 'Supplier', 'All records', '', '');
            INSERT INTO `tabContact` VALUES ('north'), ('south'), ('unlinked');
            INSERT INTO `tabDynamic Link` VALUES ('north', 'Contact', 'links', 'Customer', 'C-NORTH'),
                ('south', 'Contact', 'links', 'Customer', 'C-SOUTH');
        ''')
        self.roles = {'agent': [permissions.USER], 'buyer': [permissions.USER], 'manager': [permissions.MANAGER]}
        self.fake = SimpleNamespace(session=_dict(user='agent'), get_roles=lambda user=None: self.roles.get(user, []),
            get_all=self.get_all, qb=SimpleNamespace(get_query=lambda doctype, **kwargs: SimpleNamespace(
                get_sql=lambda: f'SELECT name FROM `tab{doctype}`')),
            db=SimpleNamespace(escape=lambda value: "'" + value.replace("'", "''") + "'", sql=self.sql,
                               exists=lambda doctype, name: bool(self.sql(f'SELECT 1 FROM `tab{doctype}` WHERE name=%s', name))))
        for module in (access, team_access):
            self.enterContext(patch.object(module, 'frappe', self.fake))
        self.teams_on = self.enterContext(patch('relay_core.features.is_enabled', return_value=True))
        self.enterContext(patch('relay_core.permissions.can_manage', side_effect=lambda user: user == 'manager'))
        self.enterContext(patch('relay_core.business_groups.configuration', return_value=['customer_group']))

    def get_all(self, doctype, filters, pluck=None):
        columns = ' AND '.join(f'`{key}`=?' for key in filters)
        return [row[0] for row in self.db.execute(f'SELECT `{pluck}` FROM `tab{doctype}` WHERE {columns}', tuple(filters.values()))]

    def sql(self, sql, values=()):
        return self.db.execute(sql.replace('%s', '?'), (values,) if isinstance(values, str) else values).fetchall()

    def covered(self, doctype, user):
        query = access.record_query(doctype, user)
        return {row[0] for row in self.sql(f'SELECT name FROM `tab{doctype}` WHERE name IN ({query})')}

    def test_a_user_reaches_the_groups_and_records_of_their_teams_only(self):
        self.assertEqual(self.covered('Customer', 'agent'), {'C-NORTH', 'C-PICKED'})
        self.assertTrue(access.record_covered('Customer', 'C-NORTH', 'agent'))
        self.assertTrue(access.record_covered('Customer', 'C-PICKED', 'agent'))
        self.assertFalse(access.record_covered('Customer', 'C-SOUTH', 'agent'), 'A group under an old grouping field')
        self.assertFalse(access.record_covered('Customer', 'C-OTHER', 'agent'))
        self.assertEqual(self.covered('Customer', 'buyer'), set(), 'A team without the type covers nothing')

    def test_all_records_managers_and_teams_off_are_not_limited(self):
        self.assertEqual(self.covered('Supplier', 'buyer'), {'S1', 'S2'})
        self.assertIsNone(team_access.covered_query('Customer', 'manager'))
        self.teams_on.return_value = False
        self.assertIsNone(team_access.covered_query('Customer', 'agent'))
        self.assertTrue(access.record_covered('Customer', 'C-OTHER', 'agent'))
        self.assertFalse(access.record_covered('Customer', 'C-MISSING', 'agent'))

    def test_teams_give_the_business_types_while_they_are_on(self):
        self.assertEqual(access.allowed_types('agent'), {'Customer'}, 'Direct type assignments wait while Teams are on')
        self.assertEqual(access.allowed_types('buyer'), {'Supplier'})
        self.assertEqual(access.allowed_types('manager'), {'Customer', 'Supplier'})
        self.teams_on.return_value = False
        self.assertEqual(access.allowed_types('agent'), {'Supplier'})

    def test_contacts_follow_their_covered_records_and_unlinked_contacts_stay_shared(self):
        condition = access.person_condition('`tabContact`.name', 'agent')
        visible = {row[0] for row in self.sql(f'SELECT name FROM `tabContact` WHERE {condition}')}
        self.assertEqual(visible, {'north', 'unlinked'})
        condition = access.person_condition('`tabContact`.name', 'manager')
        self.assertEqual({row[0] for row in self.sql(f'SELECT name FROM `tabContact` WHERE {condition}')},
                         {'north', 'south', 'unlinked'})

    def test_explicit_rows_use_the_same_record_scope(self):
        self.db.executescript('''CREATE TABLE `tabRelay Chat` (name TEXT, business_doctype TEXT, business_name TEXT);
            INSERT INTO `tabRelay Chat` VALUES ('chat-north', 'Customer', 'C-NORTH'), ('chat-south', 'Customer', 'C-SOUTH');''')
        condition = access.explicit_condition('Relay Chat', 'agent')
        self.assertEqual([row[0] for row in self.sql(f'SELECT name FROM `tabRelay Chat` WHERE {condition}')], ['chat-north'])


if __name__ == '__main__':
    unittest.main()
