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
                        'Relay Conversation Summary', 'Relay Message Translation', 'Relay Flow Run', 'Relay Call'):
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


class ConversationRowRuleTests(unittest.TestCase):
    """A User sees its own teams and assignments; Team User, Manager and System Manager see every team."""

    def scoped(self, frappe, responsible=False):
        groups = types.SimpleNamespace(responsible=lambda contact, user: responsible,
                                       responsibility_condition=lambda user, contact: 'GROUP')
        return patch.dict(sys.modules, frappe=frappe, **{'relay_core.business_groups': groups})

    def allowed(self, roles, assignment, members=(), responsible=False):
        from relay_core import permissions
        with self.scoped(fake_frappe(roles, assignment=assignment, members=members), responsible):
            return permissions.assignment_allowed('RELAY-CON-1', 'agent@example.com')

    def test_user_sees_only_own_team_and_own_assignments(self):
        other_team = types.SimpleNamespace(team='Support-001', assigned_to='other@example.com')
        mine = {('Sales-001', 'agent@example.com')}
        self.assertFalse(self.allowed([USER], other_team, mine))
        self.assertTrue(self.allowed([USER], types.SimpleNamespace(team='Sales-001', assigned_to='other@example.com'), mine))
        self.assertTrue(self.allowed([USER], types.SimpleNamespace(team=None, assigned_to='agent@example.com')))
        self.assertTrue(self.allowed([USER], None, responsible=True))
        self.assertFalse(self.allowed([USER], None))

    def test_team_user_manager_and_system_manager_see_every_team(self):
        other_team = types.SimpleNamespace(team='Support-001', assigned_to='other@example.com')
        for role in (TEAM_USER, MANAGER, 'System Manager'):
            self.assertTrue(self.allowed([role], other_team), role)
            from relay_core import permissions
            with self.scoped(fake_frappe([role])):
                self.assertEqual(permissions.assignment_condition('agent@example.com'), '')

    def test_users_without_a_relay_role_see_nothing(self):
        team = types.SimpleNamespace(team='Sales-001', assigned_to='agent@example.com')
        for roles in (['Employee'], [HUB_SERVICE]):
            self.assertFalse(self.allowed(roles, team, {('Sales-001', 'agent@example.com')}))
            from relay_core import permissions
            with self.scoped(fake_frappe(roles)):
                self.assertEqual(permissions.assignment_condition('agent@example.com'), '1=0')

    def test_user_query_matches_team_membership_and_assignment(self):
        from relay_core import permissions
        with self.scoped(fake_frappe([USER])):
            condition = permissions.assignment_condition('agent@example.com')
            message = permissions.assignment_condition('agent@example.com', message=True)
        self.assertIn('`tabRelay Team Member`', condition)
        self.assertIn("a.assigned_to='agent@example.com'", condition)
        self.assertIn('GROUP', condition)
        self.assertIn('`tabRelay Message`.relay_contact', message)

    def test_conversation_needs_no_contact_or_business_read(self):
        from relay_core import permissions
        relay = types.SimpleNamespace(name='RELAY-CON-1', contact='person', check_permission=lambda ptype: None)
        frappe = fake_frappe([TEAM_USER], get_doc=lambda doctype, name: relay if doctype == 'Relay Contact' else doctype)
        with self.scoped(frappe):
            self.assertTrue(permissions.contact_permission(relay, 'agent@example.com'))
            self.assertEqual(permissions.contact_query('agent@example.com'), '')
            self.assertEqual(permissions.readable_contact('RELAY-CON-1'), (relay, 'Contact'))

    def test_contact_rows_follow_the_relay_role_rule(self):
        from relay_core import permissions
        for roles, expected in (([USER], True), (['Employee'], False)):
            team = types.SimpleNamespace(team='Sales-001', assigned_to=None)
            with self.scoped(fake_frappe(roles, assignment=team, members={('Sales-001', 'agent@example.com')})):
                self.assertEqual(permissions.contact_permission(types.SimpleNamespace(name='RELAY-CON-1'),
                                                                'agent@example.com'), expected, roles)
        with self.scoped(fake_frappe(['Employee'])):
            self.assertEqual(permissions.contact_query('agent@example.com'), '1=0')

    def test_message_query_hides_triage_except_from_administrator(self):
        from relay_core import permissions
        with self.scoped(fake_frappe([MANAGER])):
            self.assertEqual(permissions.message_query('agent@example.com'),
                             'COALESCE(`tabRelay Message`.legacy_triage,0)=0')
            self.assertEqual(permissions.message_query('Administrator'), '')
        with self.scoped(fake_frappe([USER])):
            condition = permissions.message_query('agent@example.com')
        self.assertIn('`tabRelay Team Member`', condition)
        self.assertTrue(condition.endswith('AND COALESCE(`tabRelay Message`.legacy_triage,0)=0'))


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
