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
        self.f.get_doc = Mock(return_value=doc)
        result = self.teams.save('Sales', '["agent@example.com"]', name='Sales-001')
        self.assertEqual([call.args[0] for call in doc.set.call_args_list], ['members'])
        self.assertEqual(result, {'name': 'Sales-001', 'title': 'Sales', 'members': ['agent@example.com']})
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


class HealthEndpointTests(unittest.TestCase):
    def test_activity_and_health_need_system_manager(self):
        f = types.SimpleNamespace(whitelist=lambda **kwargs: lambda fn: fn)
        operations = load('relay_core/operations.py', f)
        operations.require_access = Mock(side_effect=PermissionError)
        for endpoint in (operations.recovery_status, operations.callback_status):
            with self.assertRaises(PermissionError):
                endpoint()
            operations.require_access.assert_called_with(configure=True)
