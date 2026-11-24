"""Team membership and System-Manager-only health endpoints, with an isolated Frappe boundary."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


def load(path, frappe):
    spec = importlib.util.spec_from_file_location('tested_' + Path(path).stem, Path(path))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, frappe=frappe):
        spec.loader.exec_module(module)
    return module


def denied(*args):
    raise PermissionError(args[0] if args else '')


class TeamTests(unittest.TestCase):
    def setUp(self):
        self.roles = {'agent@example.com': ['Relay Communication User'], 'viewer@example.com': ['Relay Communication Team User']}
        self.f = types.SimpleNamespace(whitelist=lambda **kwargs: lambda fn: fn, throw=denied, PermissionError=PermissionError,
                                       get_roles=lambda user=None: self.roles.get(user, ['Relay Communication Manager']),
                                       has_permission=lambda doctype, ptype='read', user=None, **kwargs: user != 'stranger@example.com',
                                       db=types.SimpleNamespace(get_value=lambda doctype, name, field: 1),
                                       parse_json=__import__('json').loads, session=types.SimpleNamespace(user='manager@example.com'))
        self.teams = load('relay_core/teams.py', self.f)
        self.teams.require_access = Mock()

    def team(self, members):
        row = lambda user: types.SimpleNamespace(user=user)
        return types.SimpleNamespace(title='Sales', members=[row(user) for user in members], get=lambda field: None)

    def test_members_need_a_relay_role(self):
        self.teams.validate_team(self.team(['agent@example.com', 'viewer@example.com']))
        with self.assertRaisesRegex(PermissionError, 'Relay communication role'):
            self.teams.validate_team(self.team(['stranger@example.com']))
        with self.assertRaisesRegex(PermissionError, 'once'):
            self.teams.validate_team(self.team(['agent@example.com', 'agent@example.com']))

    def test_save_and_read_return_members_only(self):
        doc = Mock(); doc.name = 'Sales-001'; doc.title = 'Sales'
        doc.members = [types.SimpleNamespace(user='agent@example.com')]
        doc.get = lambda field: []
        self.f.get_doc = Mock(return_value=doc)
        result = self.teams.save('Sales', '["agent@example.com"]', name='Sales-001')
        self.assertEqual([call.args[0] for call in doc.set.call_args_list], ['members'])
        self.assertEqual(result, {'name': 'Sales-001', 'title': 'Sales', 'members': ['agent@example.com'], 'business': []})
        self.assertEqual(self.teams.read('Sales-001'), result)
        self.teams.require_access.assert_called_with(manage=True)

    def test_filter_team_open_to_members_and_team_readers(self):
        doc = self.team(['agent@example.com'])
        doc.has_permission = lambda permission: False
        self.f.get_doc = Mock(return_value=doc)
        self.f.session.user = 'agent@example.com'
        self.assertIs(self.teams.readable_filter_team('Sales-001'), doc)
        self.f.session.user = 'viewer@example.com'
        with self.assertRaises(PermissionError):
            self.teams.readable_filter_team('Sales-001')
        doc.has_permission = lambda permission: True
        self.assertIs(self.teams.readable_filter_team('Sales-001'), doc)

    def test_assign_keeps_the_desk_team_while_teams_are_off_and_records_who_chose_the_agent(self):
        doc = types.SimpleNamespace(team='Sales', assigned_to=None, assigned_by=None, relay_contact='CON-1', save=Mock())
        self.f.get_doc = Mock(return_value=doc); self.teams.readable_contact = Mock()
        self.teams.features = Mock(); self.teams.features.is_enabled.return_value = False
        with patch('relay_core.queue_counts.invalidate'):
            result = self.teams.assign('CON-1', team='', assigned_to='agent@example.com')
            self.assertEqual(result, {'contact': 'CON-1', 'team': 'Sales', 'assigned_to': 'agent@example.com', 'assigned_by': 'manager@example.com'})
            self.teams.features.is_enabled.return_value = True
            self.f.session.user = 'other@example.com'
            self.teams.assign('CON-1', team='Support', assigned_to='agent@example.com')
            self.assertEqual((doc.team, doc.assigned_by), ('Support', 'manager@example.com'), 'The same agent keeps who chose them')
            self.teams.assign('CON-1', team='Support', assigned_to='')
            self.assertEqual((doc.assigned_to, doc.assigned_by), (None, None))
        self.teams.features.is_enabled.assert_called_with('teams')

    def test_an_agent_outside_the_team_is_refused_only_while_teams_are_on(self):
        team = types.SimpleNamespace(members=[types.SimpleNamespace(user='viewer@example.com')], check_permission=Mock())
        self.f.get_doc = Mock(return_value=team); self.teams.readable_contact = Mock()
        doc = types.SimpleNamespace(relay_contact='CON-1', team='Sales', assigned_to='agent@example.com')
        self.teams.features = Mock(); self.teams.features.is_enabled.return_value = False
        self.teams.validate_assignment(doc)
        self.teams.features.is_enabled.return_value = True
        with self.assertRaisesRegex(PermissionError, 'belong to the selected team'):
            self.teams.validate_assignment(doc)


class Row(dict):
    __getattr__ = dict.get

    def __setattr__(self, key, value):
        self[key] = value


class TeamBusinessTests(unittest.TestCase):
    """Which business records a team covers: all records, groups of the first grouping field or picked records."""
    def setUp(self):
        TeamTests.setUp(self)
        records = {'Customer': ['C1', 'C2'], 'Supplier': ['S1']}
        self.f.get_all = lambda doctype, filters, pluck: (
            ['Customer', 'Supplier'] if doctype == 'Relay Contact Type'
            else [name for name in records[doctype] if name in filters['name'][1]])
        self.teams.group_field = lambda doctype: 'customer_group' if doctype == 'Customer' else ''

    def test_groups_records_and_all_records_are_accepted(self):
        rows = [Row(business_doctype='Customer', access='Group', value='North'),
                Row(business_doctype='Customer', access='Record', value='C1'),
                Row(business_doctype='Supplier', access='All records', value='ignored')]
        self.teams.validate_business(rows)
        self.assertEqual(rows[0].grouping_field, 'customer_group')
        self.assertEqual((rows[2].value, rows[2].grouping_field), ('', ''))

    def test_invalid_rows_are_refused(self):
        cases = [([Row(business_doctype='Lead', access='Record', value='L1')], 'enabled business type'),
                 ([Row(business_doctype='Customer', access='Everything', value='')], 'All records, Group or Record'),
                 ([Row(business_doctype='Supplier', access='Group', value='Local')], 'no grouping field'),
                 ([Row(business_doctype='Customer', access='Group', value='North', grouping_field='territory')], 'changed'),
                 ([Row(business_doctype='Customer', access='Group', value='')], 'Choose a group or record'),
                 ([Row(business_doctype='Customer', access='Record', value='C9')], 'Unknown Customer: C9'),
                 ([Row(business_doctype='Customer', access='Record', value='C1')] * 2, 'only appear once'),
                 ([Row(business_doctype='Supplier', access='All records'), Row(business_doctype='Supplier', access='Record', value='S1')],
                  'cannot also pick')]
        for rows, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(PermissionError, message):
                self.teams.validate_business(rows)

    def test_save_replaces_business_rows_only_when_given_and_returns_them(self):
        doc = Mock(); doc.name = 'Sales-001'; doc.title = 'Sales'; doc.members = []
        doc.get = lambda field: [Row(business_doctype='Customer', access='Group', value='North')]
        self.f.get_doc = Mock(return_value=doc)
        result = self.teams.save('Sales', '[]', name='Sales-001',
                                 business='[{"business_doctype": "Customer", "access": "Group", "value": "North", "extra": 1}]')
        doc.set.assert_any_call('business_access', [{'business_doctype': 'Customer', 'access': 'Group', 'value': 'North'}])
        self.assertEqual(result['business'], [{'business_doctype': 'Customer', 'access': 'Group', 'value': 'North'}])
        with self.assertRaisesRegex(PermissionError, 'list of rows'):
            self.teams.save('Sales', '[]', name='Sales-001', business='{"business_doctype": "Customer"}')

    def test_directory_summarizes_members_and_business_per_team(self):
        team = Row(name='Sales-001', title='Sales')
        self.f.get_list = Mock(return_value=[team])
        members = [Row(parent='Sales-001', user='agent@example.com')]
        business = [Row(parent='Sales-001', business_doctype='Customer', access='Group', total=3),
                    Row(parent='Sales-001', business_doctype='Customer', access='Record', total=2),
                    Row(parent='Sales-001', business_doctype='Supplier', access='All records', total=1)]
        self.f.get_all = lambda doctype, **kwargs: members if doctype == 'Relay Team Member' else business
        self.teams.features = Mock(); self.teams.features.is_enabled.return_value = True
        result = self.teams.directory()
        self.assertEqual(result['items'][0]['members'], ['agent@example.com'])
        self.assertEqual(result['items'][0]['business'], [
            {'business_doctype': 'Customer', 'all': False, 'groups': 3, 'records': 2},
            {'business_doctype': 'Supplier', 'all': True, 'groups': 0, 'records': 0}])
        self.assertTrue(result['teams_enabled'])
        self.teams.require_access.side_effect = PermissionError('Only communication managers')
        with self.assertRaises(PermissionError):
            self.teams.directory()
        self.teams.require_access.assert_called_with(manage=True)


class HealthEndpointTests(unittest.TestCase):
    def test_activity_and_health_need_system_manager(self):
        f = types.SimpleNamespace(whitelist=lambda **kwargs: lambda fn: fn)
        operations = load('relay_core/operations.py', f)
        operations.require_access = Mock(side_effect=PermissionError)
        for endpoint in (operations.recovery_status, operations.callback_status):
            with self.assertRaises(PermissionError):
                endpoint()
            operations.require_access.assert_called_with(configure=True)
