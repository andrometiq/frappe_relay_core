import sys
import types
import unittest
from unittest.mock import patch
from relay_core.permissions import require_access, MANAGER, USER

class PermissionsTest(unittest.TestCase):
    def test_config_is_system_manager_only(self):
        def denied(*args): raise PermissionError()
        for role in (MANAGER, USER, 'Guest'):
            fake=types.SimpleNamespace(get_roles=lambda user:[role],session=types.SimpleNamespace(user='test'),throw=denied,PermissionError=PermissionError)
            with patch.dict(sys.modules,frappe=fake):
                with self.assertRaises(PermissionError):require_access(configure=True)
                if role!='Guest':require_access()
        fake.get_roles=lambda user:['System Manager']
        with patch.dict(sys.modules,frappe=fake):require_access(configure=True)

    def test_user_cannot_manage(self):
        def denied(*args):raise PermissionError()
        fake=types.SimpleNamespace(get_roles=lambda user:[USER],session=types.SimpleNamespace(user='test'),throw=denied,PermissionError=PermissionError)
        with patch.dict(sys.modules,frappe=fake):
            with self.assertRaises(PermissionError):require_access(manage=True)

    def test_doctype_metadata_uses_series_and_protects_configuration(self):
        import json
        from pathlib import Path
        for path in Path('relay_core/relay_core/doctype').glob('*/*.json'):
            doc=json.loads(path.read_text())
            self.assertTrue(doc['name'].startswith('Relay '))
            self.assertTrue(doc['autoname'].endswith('.##########'))
            if doc['name']=='Relay Channel':
                for permission in doc['permissions']:
                    if permission['role']!='System Manager':
                        self.assertFalse(permission.get('write'))
                        self.assertFalse(permission.get('create'))
