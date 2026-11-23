"""Access page API: rows per user, manager-only changes and role locks, with an isolated Frappe boundary."""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

USER, TEAM_USER, MANAGER = 'Relay Communication User', 'Relay Communication Team User', 'Relay Communication Manager'


def load(frappe):
    spec = importlib.util.spec_from_file_location('tested_access', Path('relay_core/access.py'))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, frappe=frappe):
        spec.loader.exec_module(module)
    return module


class Doc(types.SimpleNamespace):
    """A parent document with one child table, recording saves."""
    def __init__(self, field, rows, **values):
        super().__init__(field=field, saved=0, flags=types.SimpleNamespace(), **values)
        self.rows = [types.SimpleNamespace(**row) for row in rows]

    def get(self, field):
        return self.rows if field == self.field else self.__dict__.get(field)

    def set(self, field, rows):
        self.rows = [types.SimpleNamespace(**row) for row in rows]

    def remove(self, row):
        self.rows.remove(row)

    def append_roles(self, *roles):
        self.rows += [types.SimpleNamespace(role=role) for role in roles]

    @property
    def roles(self):
        return self.rows

    def save(self):
        self.saved += 1


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.users = {'me@example.com': ('Me', 'System User'), 'agent@example.com': ('Agent', 'System User'),
                      'boss@example.com': ('Boss', 'System User'), 'shop@example.com': ('Shop', 'Website User')}
        self.docs = {
            ('User', 'agent@example.com'): Doc('roles', [{'role': USER}, {'role': 'Accounts User'}]),
            ('User', 'me@example.com'): Doc('roles', [{'role': MANAGER}]),
            ('User', 'boss@example.com'): Doc('roles', [{'role': USER}], role_profiles=[{'role_profile': 'Sales'}]),
            ('Relay Team', 'Sales'): Doc('members', [{'user': 'me@example.com'}]),
            ('Relay Team', 'Dispatch'): Doc('members', [{'user': 'agent@example.com'}, {'user': 'me@example.com'}]),
            ('Relay Contact Type', 'Customer'): Doc('users', [{'user': 'agent@example.com'}]),
            ('Relay Contact Type', 'Supplier'): Doc('users', []),
        }

        def get_all(doctype, filters=None, pluck=None, fields=None, **kwargs):
            filters = filters or {}
            rows = self.rows(doctype)
            for key, value in filters.items():
                if isinstance(value, list) and value[0] == 'in':
                    rows = [row for row in rows if row.get(key) in value[1]]
                elif not isinstance(value, list):
                    rows = [row for row in rows if row.get(key) == value]
            rows = [Row(row) for row in rows]
            return [row[pluck] for row in rows] if pluck else rows

        self.f = types.SimpleNamespace(
            whitelist=lambda **kwargs: lambda fn: fn, throw=self.denied, PermissionError=PermissionError,
            session=types.SimpleNamespace(user='me@example.com'), parse_json=json.loads, get_all=get_all,
            get_doc=lambda doctype, name: self.docs[(doctype, name)],
            db=types.SimpleNamespace(get_value=lambda doctype, name, fields, as_dict=False: Row(
                enabled=1, user_type=self.users[name][1]) if name in self.users else None))
        self.access = load(self.f)
        self.access.require_access = Mock()
        self.access.can_manage = Mock(return_value=True)

    @staticmethod
    def denied(message, *args):
        raise PermissionError(message)

    def rows(self, doctype):
        if doctype == 'User':
            return [{'name': name, 'full_name': full, 'user_image': '', 'enabled': 1} for name, (full, _) in self.users.items()]
        if doctype == 'Has Role':
            return [{'parent': name, 'parenttype': 'User', 'role': row.role} for (kind, name), doc in self.docs.items()
                    if kind == 'User' for row in doc.rows]
        if doctype == 'User Role Profile':
            return [{'parent': name, 'parenttype': 'User'} for (kind, name), doc in self.docs.items()
                    if kind == 'User' and doc.get('role_profiles')]
        if doctype in ('Relay Team Member', 'Relay Contact Type User'):
            parent = 'Relay Team' if doctype == 'Relay Team Member' else 'Relay Contact Type'
            return [{'parent': name, 'parenttype': parent, 'parentfield': doc.field, 'user': row.user}
                    for (kind, name), doc in self.docs.items() if kind == parent for row in doc.rows]
        if doctype == 'Relay Team':
            return [{'name': name, 'title': name} for kind, name in self.docs if kind == doctype]
        if doctype == 'Relay Contact Type':
            return [{'name': name, 'business_doctype': name, 'label': '', 'enabled': 1} for kind, name in self.docs if kind == doctype]
        raise AssertionError(doctype)

    def roles_of(self, user):
        return sorted(row.role for row in self.docs[('User', user)].rows)

    def test_managers_read_everyone_with_relay_access_and_users_read_themselves(self):
        result = self.access.directory()
        self.assertTrue(result['can_edit'])
        rows = {row['user']: row for row in result['items']}
        self.assertEqual(set(rows), {'me@example.com', 'agent@example.com', 'boss@example.com'})
        self.assertEqual((rows['agent@example.com']['role'], rows['agent@example.com']['teams'],
                          rows['agent@example.com']['business_types']), ('User', ['Dispatch'], ['Customer']))
        self.assertEqual(rows['me@example.com']['role_locked'], 'You cannot change your own role.')
        self.assertIn('role profile', rows['boss@example.com']['role_locked'])
        self.assertEqual(rows['agent@example.com']['role_locked'], '')
        self.assertEqual([row['value'] for row in result['business_types']], ['Customer', 'Supplier'])

        self.access.can_manage.return_value = False
        result = self.access.directory()
        self.assertFalse(result['can_edit'])
        self.assertEqual([row['user'] for row in result['items']], ['me@example.com'])

    def test_save_needs_the_manager_check(self):
        self.access.require_access.side_effect = PermissionError('Only communication managers can perform this action')
        with self.assertRaises(PermissionError):
            self.access.save('agent@example.com', role='Manager')
        self.assertEqual(self.roles_of('agent@example.com'), ['Accounts User', USER])

    def test_role_change_keeps_other_roles(self):
        row = self.access.save('agent@example.com', role='Manager', team_user='1')
        self.assertEqual(self.roles_of('agent@example.com'), sorted(['Accounts User', TEAM_USER, MANAGER]))
        self.assertTrue(self.docs[('User', 'agent@example.com')].flags.ignore_permissions)
        self.assertEqual((row['role'], row['team_user']), ('Manager', True))
        self.access.save('agent@example.com', role='', team_user='0')
        self.assertEqual(self.roles_of('agent@example.com'), ['Accounts User'])

    def test_own_role_and_role_profile_roles_are_locked(self):
        with self.assertRaisesRegex(PermissionError, 'own role'):
            self.access.save('me@example.com', role='User')
        with self.assertRaisesRegex(PermissionError, 'role profile'):
            self.access.save('boss@example.com', role='Manager')
        self.access.save('me@example.com', role='Manager', teams='["Dispatch"]')
        self.assertEqual(self.docs[('User', 'me@example.com')].saved, 0)
        self.assertEqual([row.user for row in self.docs[('Relay Team', 'Sales')].rows], [])

    def test_teams_and_business_types_change_only_where_needed(self):
        self.access.save('agent@example.com', teams='["Sales"]', business_types=['Supplier'])
        self.assertEqual([row.user for row in self.docs[('Relay Team', 'Sales')].rows], ['me@example.com', 'agent@example.com'])
        self.assertEqual([row.user for row in self.docs[('Relay Team', 'Dispatch')].rows], ['me@example.com'])
        self.assertEqual([row.user for row in self.docs[('Relay Contact Type', 'Supplier')].rows], ['agent@example.com'])
        self.assertEqual(self.docs[('Relay Contact Type', 'Customer')].rows, [])
        self.assertEqual(self.docs[('User', 'agent@example.com')].saved, 0)
        self.access.save('agent@example.com', teams='["Sales"]')
        self.assertEqual(self.docs[('Relay Team', 'Sales')].saved, 1)

    def test_invalid_values_are_refused(self):
        for values in ({'role': 'Owner'}, {'team_user': 'yes'}, {'teams': '["Ghost"]'}, {'business_types': 'Customer'}):
            with self.assertRaises(PermissionError, msg=values):
                self.access.save('agent@example.com', **values)
        for user in ('shop@example.com', 'Administrator', 'nobody@example.com', None):
            with self.assertRaisesRegex(PermissionError, 'staff user'):
                self.access.save(user, role='User')


class Row(dict):
    def __init__(self, values=None, **more):
        super().__init__(values or {}, **more)

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error


if __name__ == '__main__':
    unittest.main()
