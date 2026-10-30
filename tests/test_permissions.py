import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from relay_core.permissions import MANAGER, TEAM_USER, USER, HUB_SERVICE

DOCTYPES = Path('relay_core/relay_core/doctype')
LETTERS = {'read': 'r', 'write': 'w', 'create': 'c', 'delete': 'd'}


def docperms():
    """DocType -> role -> rights letters, read from the shipped DocType JSON."""
    result = {}
    for path in DOCTYPES.glob('*/*.json'):
        doc = json.loads(path.read_text())
        if doc.get('doctype') == 'DocType' and not doc.get('istable'):
            result[doc['name']] = {row['role']: ''.join(letter for key, letter in LETTERS.items() if row.get(key))
                                   for row in doc['permissions']}
    return result


PERMS = docperms()


def fake_frappe(roles, user='agent@example.com', assignment=None, members=(), **extra):
    """A Frappe boundary whose has_permission follows the shipped DocPerm rows."""
    def has_permission(doctype, ptype='read', doc=None, user=None, **kwargs):
        rights = PERMS[doctype]
        return any(LETTERS[ptype] in rights.get(role, '') for role in roles)
    def denied(*args): raise PermissionError(args[0] if args else '')
    def exists(doctype, filters):
        return (filters['parent'], filters['user']) in members
    db = types.SimpleNamespace(get_value=lambda *args, **kwargs: assignment, exists=exists, escape=repr)
    return types.SimpleNamespace(get_roles=lambda user=None: list(roles), has_permission=has_permission,
                                 session=types.SimpleNamespace(user=user), throw=denied,
                                 PermissionError=PermissionError, db=db, **extra)


class RoleMatrixTests(unittest.TestCase):
    """DocPerm is the source of truth: each role reads and writes only its own DocTypes."""

    def can(self, role, doctype, rights):
        return all(letter in PERMS[doctype].get(role, '') for letter in rights)

    def test_agents_work_conversations_but_not_manager_or_config_records(self):
        for role in (USER, TEAM_USER):
            for doctype in ('Relay Contact', 'Relay Message', 'Relay Channel', 'Relay Contact Type'):
                self.assertTrue(self.can(role, doctype, 'r'), (role, doctype))
            self.assertTrue(self.can(role, 'Relay Ticket', 'rwc'))
            for doctype in ('Relay Campaign', 'Relay WhatsApp Billing Month', 'Relay AI Skill', 'Relay Business Event Rule',
                            'Relay Canned Reply', 'Relay Conversation Assignment', 'Relay Settings', 'Relay WhatsApp Template'):
                self.assertFalse(self.can(role, doctype, 'r'), (role, doctype))
            self.assertFalse(self.can(role, 'Relay Team', 'w'))

    def test_manager_runs_campaigns_events_templates_skills_billing_and_teams(self):
        for doctype in ('Relay Campaign', 'Relay Business Event Rule', 'Relay WhatsApp Template', 'Relay AI Skill',
                        'Relay Team', 'Relay Conversation Assignment', 'Relay Canned Reply'):
            self.assertTrue(self.can(MANAGER, doctype, 'rwc'), doctype)
        self.assertTrue(self.can(MANAGER, 'Relay WhatsApp Billing Month', 'r'))
        for doctype in ('Relay Settings', 'Relay AI Provider', 'Relay Channel', 'Relay Email Rule'):
            self.assertFalse(self.can(MANAGER, doctype, 'w'), doctype)

    def test_system_manager_reads_every_doctype_and_configures_settings(self):
        for doctype, rows in PERMS.items():
            self.assertIn('r', rows.get('System Manager', ''), doctype)
        self.assertTrue(self.can('System Manager', 'Relay Settings', 'rw'))

    def test_machine_records_are_system_manager_only(self):
        for doctype in ('Relay Automation Run', 'Relay Business Event Delivery', 'Relay Internal Comment', 'Relay Case',
                        'Relay Conversation Summary', 'Relay Message Translation', 'Relay Flow Run', 'Relay Call',
                        'Relay Memory'):
            self.assertEqual(set(PERMS[doctype]), {'System Manager'}, doctype)

    def test_hub_service_only_creates_hub_events(self):
        self.assertEqual([doctype for doctype, rows in PERMS.items() if HUB_SERVICE in rows], ['Relay Hub Event'])
        self.assertTrue(self.can(HUB_SERVICE, 'Relay Hub Event', 'c'))

    def test_no_relay_record_names_the_whatsapp_core_roles(self):
        for path in Path('relay_core/relay_core').glob('**/*.json'):
            text = path.read_text()
            for role in ('"WhatsApp User"', '"WhatsApp Manager"', '"WhatsApp Multi-Channel User"'):
                self.assertNotIn(role, text, path)

    def test_no_internal_record_hooks_remain(self):
        from relay_core import hooks
        self.assertNotIn('relay_core.permissions.internal_record_permission', hooks.has_permission.values())


class AccessTests(unittest.TestCase):
    def test_require_access_checks_the_named_doctype(self):
        from relay_core import permissions
        cases = {USER: (True, False, False, False), TEAM_USER: (True, False, False, False),
                 MANAGER: (True, True, False, True), 'System Manager': (True, True, True, True),
                 'Employee': (False, False, False, False)}
        for role, expected in cases.items():
            with patch.dict(sys.modules, frappe=fake_frappe([role])):
                for allowed, args, kwargs in zip(expected, ((), (), (), ('Relay Campaign', 'write')),
                                                 ({}, {'manage': True}, {'configure': True}, {})):
                    if allowed:
                        permissions.require_access(*args, **kwargs)
                    else:
                        with self.assertRaises(PermissionError, msg=(role, args, kwargs)):
                            permissions.require_access(*args, **kwargs)

    def test_hub_service_may_only_post_hub_events(self):
        from relay_core import permissions
        with patch.dict(sys.modules, frappe=fake_frappe([HUB_SERVICE])):
            permissions.require_access('Relay Hub Event', 'create')
            with self.assertRaises(PermissionError):
                permissions.require_access()

    def test_app_tile_needs_a_relay_role(self):
        from relay_core import permissions
        for role in (USER, TEAM_USER, MANAGER, 'System Manager'):
            with patch.dict(sys.modules, frappe=fake_frappe([role])):
                self.assertTrue(permissions.has_app_permission())
        for roles in (['Employee'], [HUB_SERVICE]):
            with patch.dict(sys.modules, frappe=fake_frappe(roles)):
                self.assertFalse(permissions.has_app_permission())

    def test_capability_helpers_follow_docperm(self):
        from relay_core import permissions
        for role, manage, configure, all_teams in ((USER, False, False, False), (TEAM_USER, False, False, True),
                                                  (MANAGER, True, False, True), ('System Manager', True, True, True)):
            with patch.dict(sys.modules, frappe=fake_frappe([role])):
                self.assertEqual((permissions.can_manage(), permissions.can_configure(), permissions.sees_all_teams()),
                                 (manage, configure, all_teams), role)

    def test_install_roles_creates_only_the_relay_roles(self):
        from relay_core import permissions
        created = []
        fake = types.SimpleNamespace(db=types.SimpleNamespace(exists=lambda doctype, name: name == MANAGER),
                                     get_doc=lambda values: types.SimpleNamespace(insert=lambda: created.append(values)))
        with patch.dict(sys.modules, frappe=fake):
            permissions.install_roles()
        self.assertEqual([(row['role_name'], row['desk_access']) for row in created],
                         [(USER, 1), (TEAM_USER, 1), (HUB_SERVICE, 0)])


class RoleMigrationTests(unittest.TestCase):
    def test_patch_gives_relay_roles_to_whatsapp_role_holders(self):
        import importlib
        holders = {'WhatsApp User': ['a@example.com', 'b@example.com'], 'WhatsApp Manager': ['m@example.com'],
                   'WhatsApp Multi-Channel User': ['v@example.com'], USER: ['b@example.com']}
        inserted, cleared = [], []
        fake = types.SimpleNamespace(
            get_all=lambda doctype, filters, pluck: holders.get(filters['role'], []),
            get_doc=lambda values: types.SimpleNamespace(db_insert=lambda: inserted.append((values['parent'], values['role']))),
            clear_cache=lambda user: cleared.append(user), db=types.SimpleNamespace(exists=lambda *args: True))
        with patch.dict(sys.modules, frappe=fake):
            sys.modules.pop('relay_core.patches.v1_0.use_four_relay_roles', None)
            importlib.import_module('relay_core.patches.v1_0.use_four_relay_roles').execute()
        self.assertEqual(inserted, [('a@example.com', USER), ('m@example.com', MANAGER), ('v@example.com', TEAM_USER)])
        self.assertEqual(cleared, ['a@example.com', 'm@example.com', 'v@example.com'])
        self.assertIn('relay_core.patches.v1_0.use_four_relay_roles', Path('relay_core/patches.txt').read_text().split())

    def test_patch_drops_the_team_access_doctype(self):
        import importlib
        deleted = []
        fake = types.SimpleNamespace(delete_doc=lambda *args, **kwargs: deleted.append((args, kwargs)))
        with patch.dict(sys.modules, frappe=fake):
            sys.modules.pop('relay_core.patches.v1_0.remove_team_access', None)
            importlib.import_module('relay_core.patches.v1_0.remove_team_access').execute()
        self.assertEqual(deleted, [(('DocType', 'Relay Team Access'), {'ignore_missing': True, 'force': True})])
        self.assertIn('relay_core.patches.v1_0.remove_team_access', Path('relay_core/patches.txt').read_text().split())
        self.assertFalse(Path('relay_core/relay_core/doctype/relay_team_access').exists())


class MetadataTests(unittest.TestCase):
    def test_doctype_metadata_uses_series_and_protects_configuration(self):
        import json
        from pathlib import Path
        field_names = {
            'Relay Automation Policy':'channel', 'Relay Email Rule':'channel',
            'Relay Email Preference':'user', 'Relay Contact Type':'business_doctype',
            'Relay Business Group Claim':'claim_key', 'Relay Pending Receipt':'record_key',
            'Relay WhatsApp Template':'record_key', 'Relay Campaign':'title', 'Relay Document Action':'title',
            'Relay WhatsApp Billing Month':'record_key',
            'Relay Ticket Status':'label', 'Relay Ticket Category':'label', 'Relay Ticket Type':'label',
        }
        for path in Path('relay_core/relay_core/doctype').glob('*/*.json'):
            doc=json.loads(path.read_text())
            self.assertTrue(doc['name'].startswith('Relay '))
            if doc['name']=='Relay Delivery Receipt':
                self.assertEqual(doc['autoname'],'field:receipt_key')
                self.assertEqual([row['role'] for row in doc['permissions']], ['System Manager'])
                key=next(field for field in doc['fields'] if field['fieldname']=='receipt_key')
                self.assertTrue(key['unique'] and key['read_only'] and key['reqd'])
            elif doc['name']=='Relay Business Event Delivery':
                self.assertEqual(doc['autoname'],'format:RELAY-BED-{event_key}')
            elif doc['name'] in field_names:
                field = field_names[doc['name']]
                self.assertEqual(doc['autoname'], 'field:' + field)
                self.assertTrue(next(row for row in doc['fields'] if row['fieldname'] == field)['reqd'])
            elif doc['name'] in {'Relay Channel', 'Relay AI Skill', 'Relay AI Event', 'Relay Business Event Rule', 'Relay Canned Reply', 'Relay Team', 'Relay Case Type', 'Relay Learned Procedure'}:
                self.assertEqual(doc['autoname'], 'format:{title}-{###}')
                self.assertEqual(doc['title_field'], 'title')
                self.assertTrue(doc.get('modified'))
            elif doc['name']=='Relay Ticket':
                self.assertEqual(doc['autoname'],'TKT-.#####')
            elif not doc.get('issingle'):
                self.assertTrue(doc['autoname'].endswith('.##########'))
            if doc['name'] in ('Relay Channel', 'Relay Settings'):
                for permission in doc['permissions']:
                    if permission['role']!='System Manager':
                        self.assertFalse(permission.get('write'))
                        self.assertFalse(permission.get('create'))




class CompanylessSiteTests(unittest.TestCase):
    """A site without ERPNext has no Company DocType; its records keep an empty company."""

    def frappe_without_company(self):
        def has_permission(doctype, *args, **kwargs):
            raise AssertionError('Company must not be looked up on a site without it')
        fake = types.SimpleNamespace(session=types.SimpleNamespace(user='agent@example.com'), has_permission=has_permission,
                                     db=types.SimpleNamespace(exists=lambda doctype, name: False))
        return patch.dict(sys.modules, {'frappe': fake})

    def test_empty_company_is_allowed_and_a_named_company_is_not(self):
        from relay_core.permissions import company_allowed
        with self.frappe_without_company():
            self.assertTrue(company_allowed(None))
            self.assertTrue(company_allowed(''))
            self.assertFalse(company_allowed('Other Company'))

    def test_company_condition_keeps_only_records_without_company(self):
        from relay_core.permissions import company_condition
        with self.frappe_without_company():
            self.assertEqual(company_condition('Relay Ticket'), "COALESCE(`tabRelay Ticket`.company,'')=''")
