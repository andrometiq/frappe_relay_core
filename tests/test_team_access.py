"""Team viewers and System-Manager-only health endpoints, with an isolated Frappe boundary."""
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


class TeamAccessTests(unittest.TestCase):
    def setUp(self):
        self.roles = {'agent@example.com': ['WhatsApp User'], 'viewer@example.com': ['WhatsApp Multi-Channel User']}
        self.f = types.SimpleNamespace(whitelist=lambda **kwargs: lambda fn: fn, throw=denied, PermissionError=PermissionError,
                                       get_roles=lambda user=None: self.roles.get(user, ['WhatsApp Manager']),
                                       db=types.SimpleNamespace(get_value=lambda doctype, name, field: 1),
                                       parse_json=__import__('json').loads, session=types.SimpleNamespace(user='manager@example.com'))
        self.teams = load('relay_core/teams.py', self.f)
        self.teams.require_access = Mock()

    def team(self, members, access):
        row = lambda user: types.SimpleNamespace(user=user)
        return types.SimpleNamespace(title='Sales', members=[row(user) for user in members],
                                     get=lambda field: [row(user) for user in access] if field == 'access' else None)

    def test_viewers_need_the_multi_channel_role(self):
        self.teams.validate_team(self.team(['agent@example.com'], ['viewer@example.com']))
        with self.assertRaisesRegex(PermissionError, 'Multi-Channel'):
            self.teams.validate_team(self.team(['agent@example.com'], ['agent@example.com']))
        with self.assertRaisesRegex(PermissionError, 'once'):
            self.teams.validate_team(self.team(['agent@example.com'], ['viewer@example.com', 'viewer@example.com']))

    def test_save_keeps_viewers_unless_given_and_read_returns_them(self):
        doc = Mock(); doc.name = 'Sales-001'; doc.title = 'Sales'
        doc.members = [types.SimpleNamespace(user='agent@example.com')]
        doc.get.return_value = [types.SimpleNamespace(user='viewer@example.com')]
        self.f.get_doc = Mock(return_value=doc)
        result = self.teams.save('Sales', '["agent@example.com"]', name='Sales-001')
        self.assertEqual([call.args[0] for call in doc.set.call_args_list], ['members'])
        self.assertEqual(result['access'], ['viewer@example.com'])
        self.teams.save('Sales', ['agent@example.com'], name='Sales-001', access='["viewer@example.com"]')
        doc.set.assert_called_with('access', [{'user': 'viewer@example.com'}])
        with self.assertRaisesRegex(PermissionError, 'Invalid team viewers'):
            self.teams.save('Sales', ['agent@example.com'], name='Sales-001', access='"viewer@example.com"')
        self.assertEqual(self.teams.read('Sales-001')['access'], ['viewer@example.com'])
        self.teams.require_access.assert_called_with(manage=True)

    def test_filter_team_open_to_listed_viewer_only(self):
        doc = self.team(['agent@example.com'], ['viewer@example.com'])
        doc.has_permission = lambda permission: False
        self.f.get_doc = Mock(return_value=doc)
        self.f.get_roles = lambda user=None: ['WhatsApp Multi-Channel User']
        self.f.session.user = 'viewer@example.com'
        self.assertIs(self.teams.readable_filter_team('Sales-001'), doc)
        self.f.session.user = 'stranger@example.com'
        with self.assertRaises(PermissionError):
            self.teams.readable_filter_team('Sales-001')
        self.f.session.user = 'viewer@example.com'
        self.f.get_roles = lambda user=None: ['WhatsApp User']
        with self.assertRaises(PermissionError):
            self.teams.readable_filter_team('Sales-001')


class HealthEndpointTests(unittest.TestCase):
    def test_activity_and_health_need_system_manager(self):
        f = types.SimpleNamespace(whitelist=lambda **kwargs: lambda fn: fn)
        operations = load('relay_core/operations.py', f)
        operations.require_access = Mock(side_effect=PermissionError)
        for endpoint in (operations.recovery_status, operations.callback_status):
            with self.assertRaises(PermissionError):
                endpoint()
            operations.require_access.assert_called_with(configure=True)
