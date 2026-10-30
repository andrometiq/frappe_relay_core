"""Role-filtered execution users retain caller-level User permissions."""
import unittest
from unittest.mock import Mock, patch
from frappe import _dict
from relay_core.automation import settings


class ExecutionUserOptionsTests(unittest.TestCase):
    def test_role_lookup_is_internal_and_users_remain_permission_filtered(self):
        framework = Mock()
        framework.get_all.return_value = ['manager', 'admin', 'Guest', 'Administrator', 'ordinary']
        framework.get_list.return_value = [_dict(name=name, full_name=name.title())
            for name in framework.get_all.return_value]
        framework.get_roles.side_effect = lambda name: ['System Manager'] if name == 'admin' else []
        with patch.object(settings, 'frappe', framework), \
                patch.object(settings, 'manager_roles', return_value=['Relay Communication Manager']), \
                patch.object(settings, 'can_manage', side_effect=lambda name: name == 'manager'):
            self.assertEqual(settings.reference_options('execution_user', 'man'),
                [{'value': 'manager', 'label': 'manager · Manager'}])
        framework.get_all.assert_called_once_with('Has Role', filters={
            'parenttype': 'User', 'parentfield': 'roles', 'role': ['in', ['Relay Communication Manager']]}, pluck='parent')
        args = framework.get_list.call_args
        self.assertEqual(args.args, ('User',))
        self.assertEqual(args.kwargs['filters'], {'enabled': 1, 'name': ['in', framework.get_all.return_value]})
        self.assertEqual(args.kwargs['page_length'], 30)

    def test_user_permission_errors_are_not_bypassed(self):
        with patch.object(settings, 'frappe', Mock()) as framework, \
                patch.object(settings, 'manager_roles', return_value=['Relay Communication Manager']):
            framework.get_list.side_effect = PermissionError
            with self.assertRaises(PermissionError):
                settings.reference_options('execution_user')
