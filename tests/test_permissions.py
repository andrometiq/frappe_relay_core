import sys
import types
import unittest
from unittest.mock import patch
from relay_core.permissions import require_access, MANAGER, USER

class PermissionsTest(unittest.TestCase):
    def test_internal_business_records_require_administrator_roles(self):
        import json
        from pathlib import Path
        from relay_core import hooks, permissions
        for role in (MANAGER, USER, 'Guest', 'System Manager'):
            fake = types.SimpleNamespace(get_roles=lambda user: [role], session=types.SimpleNamespace(user='reader'))
            with patch.dict(sys.modules, frappe=fake):
                self.assertFalse(permissions.internal_record_permission(user='reader'))
                self.assertEqual(permissions.internal_record_query('reader'), '1=0')
                self.assertEqual(permissions.internal_record_query('Administrator'), '')
                self.assertTrue(permissions.internal_record_permission(user='Administrator'))
        for doctype in ('Relay Automation Run', 'Relay Business Event Delivery', 'Relay Hub Event', 'Relay Business Routing'):
            slug = doctype.lower().replace(' ', '_')
            meta = json.loads(Path(f'relay_core/relay_core/doctype/{slug}/{slug}.json').read_text())
            self.assertTrue(meta['permissions'])
            if doctype in ('Relay Automation Run', 'Relay Business Event Delivery'):
                self.assertTrue(all(row['role'] == 'System Manager' for row in meta['permissions']))
            self.assertEqual(hooks.has_permission[doctype], 'relay_core.permissions.internal_record_permission')
            self.assertEqual(hooks.permission_query_conditions[doctype], 'relay_core.permissions.internal_record_query')

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
        field_names = {
            'Relay Automation Policy':'channel', 'Relay Email Rule':'channel',
            'Relay Email Preference':'user', 'Relay Contact Type':'business_doctype',
            'Relay Business Group Claim':'claim_key', 'Relay Pending Receipt':'record_key',
            'Relay WhatsApp Template':'record_key',
        }
        for path in Path('relay_core/relay_core/doctype').glob('*/*.json'):
            doc=json.loads(path.read_text())
            self.assertTrue(doc['name'].startswith('Relay '))
            if doc['name']=='Relay Delivery Receipt':
                self.assertEqual(doc['autoname'],'field:receipt_key')
                self.assertFalse(doc['permissions'])
                key=next(field for field in doc['fields'] if field['fieldname']=='receipt_key')
                self.assertTrue(key['unique'] and key['read_only'] and key['reqd'])
            elif doc['name']=='Relay Business Event Delivery':
                self.assertEqual(doc['autoname'],'format:RELAY-BED-{event_key}')
            elif doc['name'] in field_names:
                field = field_names[doc['name']]
                self.assertEqual(doc['autoname'], 'field:' + field)
                self.assertTrue(next(row for row in doc['fields'] if row['fieldname'] == field)['reqd'])
            elif doc['name'] in {'Relay Channel', 'Relay AI Skill', 'Relay Business Event Rule', 'Relay Canned Reply', 'Relay Team', 'Relay Case Type', 'Relay Learned Procedure'}:
                self.assertEqual(doc['autoname'], 'format:{title}-{###}')
                self.assertEqual(doc['title_field'], 'title')
                self.assertTrue(doc.get('modified'))
            elif not doc.get('issingle'):
                self.assertTrue(doc['autoname'].endswith('.##########'))
            if doc['name'] in ('Relay Channel', 'Relay Settings'):
                for permission in doc['permissions']:
                    if permission['role']!='System Manager':
                        self.assertFalse(permission.get('write'))
                        self.assertFalse(permission.get('create'))
