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
            'Relay WhatsApp Template':'record_key', 'Relay Campaign':'title',
            'Relay WhatsApp Billing Month':'record_key',
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


class WhatsAppRoleTests(unittest.TestCase):
    """New WhatsApp roles and the old Relay roles grant the same access."""

    def fake(self, roles, assignment=None, members=(), viewers=()):
        def denied(*args): raise PermissionError()
        def exists(doctype, filters):
            rows = members if doctype == 'Relay Team Member' else viewers
            return (filters['parent'], filters['user']) in rows
        db = types.SimpleNamespace(get_value=lambda *args, **kwargs: assignment, exists=exists, escape=lambda value: repr(value))
        return types.SimpleNamespace(get_roles=lambda user=None: list(roles), session=types.SimpleNamespace(user='agent@example.com'),
                                     throw=denied, PermissionError=PermissionError, db=db)

    def scoped(self, frappe):
        groups = types.SimpleNamespace(responsible=lambda contact, user: False, responsibility_condition=lambda user, contact: '0=1')
        return patch.dict(sys.modules, frappe=frappe, **{'relay_core.business_groups': groups})

    def test_require_access_tiers_per_role(self):
        from relay_core import permissions
        cases = {
            'WhatsApp User': (True, False, False), 'Relay Communication User': (True, False, False),
            'WhatsApp Multi-Channel User': (True, False, False), 'WhatsApp Manager': (True, True, False),
            'Relay Communication Manager': (True, True, False), 'System Manager': (True, True, True),
            'Guest': (False, False, False),
        }
        for role, (use, manage, configure) in cases.items():
            with patch.dict(sys.modules, frappe=self.fake([role])):
                for allowed, kwargs in ((use, {}), (manage, {'manage': True}), (configure, {'configure': True})):
                    if allowed:
                        permissions.require_access(**kwargs)
                    else:
                        with self.assertRaises(PermissionError, msg=(role, kwargs)):
                            permissions.require_access(**kwargs)

    def test_install_roles_creates_whatsapp_roles(self):
        from relay_core import permissions
        created = []
        fake = types.SimpleNamespace(db=types.SimpleNamespace(exists=lambda doctype, name: name == permissions.MANAGER),
                                     get_doc=lambda values: types.SimpleNamespace(insert=lambda: created.append(values['role_name'])))
        with patch.dict(sys.modules, frappe=fake):
            permissions.install_roles()
        self.assertEqual(created, [permissions.USER, permissions.WA_MANAGER, permissions.WA_USER,
                                   permissions.WA_MULTI, 'Relay Hub Service'])

    def test_manager_sees_all_and_user_only_own_team(self):
        from relay_core import permissions
        team_row = types.SimpleNamespace(team='Sales-001', assigned_to=None)
        for role in ('WhatsApp Manager', 'Relay Communication Manager'):
            with self.scoped(self.fake([role], team_row)):
                self.assertTrue(permissions.assignment_allowed('RELAY-CON-1', 'agent@example.com'))
                self.assertEqual(permissions.assignment_condition('agent@example.com'), '')
        for role in ('WhatsApp User', 'Relay Communication User'):
            with self.scoped(self.fake([role], team_row, members={('Sales-001', 'agent@example.com')})):
                self.assertTrue(permissions.assignment_allowed('RELAY-CON-1', 'agent@example.com'))
            with self.scoped(self.fake([role], team_row)):
                self.assertFalse(permissions.assignment_allowed('RELAY-CON-1', 'agent@example.com'))
        with self.scoped(self.fake(['Guest'], team_row)):
            self.assertFalse(permissions.assignment_allowed('RELAY-CON-1', 'agent@example.com'))
            self.assertEqual(permissions.assignment_condition('agent@example.com'), '1=0')

    def test_multi_channel_user_sees_listed_teams_only(self):
        from relay_core import permissions
        assigned = types.SimpleNamespace(team='Support-001', assigned_to='other@example.com')
        viewers = {('Support-001', 'agent@example.com')}
        with self.scoped(self.fake([permissions.WA_MULTI], assigned, viewers=viewers)):
            self.assertTrue(permissions.assignment_allowed('RELAY-CON-1', 'agent@example.com'))
            condition = permissions.assignment_condition('agent@example.com')
            self.assertIn('`tabRelay Team Access`', condition)
        with self.scoped(self.fake([permissions.WA_MULTI], assigned)):
            self.assertFalse(permissions.assignment_allowed('RELAY-CON-1', 'agent@example.com'))
        # Access rows count only for the Multi-Channel role.
        with self.scoped(self.fake([permissions.WA_USER], assigned, viewers=viewers)):
            self.assertFalse(permissions.assignment_allowed('RELAY-CON-1', 'agent@example.com'))
            self.assertNotIn('`tabRelay Team Access`', permissions.assignment_condition('agent@example.com'))

    def test_has_app_permission_for_every_relay_role(self):
        from relay_core import permissions
        for role in permissions.RELAY_ROLES:
            with patch.dict(sys.modules, frappe=self.fake([role])):
                self.assertTrue(permissions.has_app_permission())
        with patch.dict(sys.modules, frappe=self.fake(['Employee'])):
            self.assertFalse(permissions.has_app_permission())

    def test_whatsapp_roles_follow_the_old_roles_on_doctypes(self):
        import json
        from pathlib import Path
        aliases = {'Relay Communication Manager': ['WhatsApp Manager'],
                   'Relay Communication User': ['WhatsApp User', 'WhatsApp Multi-Channel User']}
        for path in Path('relay_core/relay_core').glob('**/*.json'):
            doc = json.loads(path.read_text())
            rows = doc.get('permissions') or doc.get('roles') or []
            if not isinstance(rows, list):
                continue
            by_role = {row.get('role'): row for row in rows if isinstance(row, dict)}
            for old, news in aliases.items():
                for new in news:
                    if old in by_role:
                        self.assertEqual({**by_role[old], 'role': new}, by_role.get(new), (path, new))

    def test_grant_patch_is_registered(self):
        from pathlib import Path
        self.assertIn('relay_core.patches.v1_0.grant_whatsapp_roles', Path('relay_core/patches.txt').read_text().split())
