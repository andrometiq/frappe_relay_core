"""Security re-review: execution identity, scalar selectors, cached titles and ownership."""
import json
import importlib
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe import _dict
from frappe.model.document import Document
from frappe.model.meta import Meta
from frappe.model.db_query import DatabaseQuery
from relay_core import business_access as access, cases, contacts
from test_ai_skills import Doc, module
from test_contact_primary import fake_frappe


class EventExecutionUserTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_frappe()
        self.validate_rule = Mock()
        controller = module('relay_core/relay_core/doctype/relay_business_event_rule/relay_business_event_rule.py',
            self.fake, {'frappe.model.document': SimpleNamespace(Document=Doc),
                        'relay_core.business_events': SimpleNamespace(validate_rule=self.validate_rule, clear_rule_cache=Mock())})
        self.rule_class = controller.RelayBusinessEventRule

    def test_relay_manager_cannot_create_or_edit_another_users_rule_even_disabled(self):
        self.fake.get_roles.return_value = ['Relay Communication Manager']
        for enabled in (0, 1):
            for previous in (None, 'reader', 'privileged@example.invalid'):
                rule = self.rule_class(run_as_user='privileged@example.invalid', enabled=enabled,
                    get_doc_before_save=lambda: Doc(run_as_user=previous) if previous else None)
                with self.subTest(enabled=enabled, previous=previous), self.assertRaises(PermissionError):
                    rule.validate()
        self.validate_rule.assert_not_called()

    def test_own_rules_and_system_manager_delegation_still_validate(self):
        for roles, execution_user in [(['Relay Communication Manager'], 'reader'),
                                      (['System Manager'], 'privileged@example.invalid')]:
            self.fake.get_roles.return_value = roles
            for enabled in (0, 1):
                rule = self.rule_class(run_as_user=execution_user, enabled=enabled)
                rule.validate()
                self.validate_rule.assert_called_with(rule)


class ScalarSelectorTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_frappe()
        self.fake.has_permission.return_value = True
        self.enterContext(patch.object(access, 'frappe', self.fake))
        self.enterContext(patch.object(cases, 'frappe', self.fake))
        self.enterContext(patch.object(cases, 'require_access'))
        self.enterContext(patch.object(cases, 'readable_contact'))
        self.enterContext(patch('relay_core.features.is_enabled', return_value=True))
        self.enterContext(patch('relay_core.permissions.readable_contact'))
        self.enterContext(patch.object(access, 'allowed_types', return_value={'Customer'}))
        self.enterContext(patch.object(access, 'candidates', return_value=[('Customer', 'C1'), ('Supplier', 'S1')]))
        self.docs = {
            'LOCAL-CUSTOMER-CASE': Doc(name='LOCAL-CUSTOMER-CASE', business_doctype='Customer', business_name='C1',
                relay_contact='R1', title='Local order for 84750', field_values='{"amount":84750}', definition='{}'),
            'LOCAL-SUPPLIER-CASE': Doc(name='LOCAL-SUPPLIER-CASE', business_doctype='Supplier', business_name='S1',
                relay_contact='R1', title='Secret supplier order', field_values='{}', definition='{}'),
        }
        self.fake.get_doc.side_effect = lambda dt, name: self.docs[name]

    def test_filters_and_malformed_names_never_reach_any_case_loader(self):
        endpoints = [lambda name: cases.read(name), lambda name: cases.move(name, 'Open', {}, 'v1'),
                     lambda name: cases.assign(name, 'reader', 'v1'), lambda name: cases.agents(name),
                     lambda name: cases.create_manual(name, 'R1', 'Local case', {}, 'request-1')]
        for bad in ({'business_doctype': 'Supplier', 'title': ['like', 'Secret%']}, {}, [], ['like', '%'],
                    None, True, 84750, '', '   ', 'x' * 141, 'CASE\n1', 'CASE\x7f1'):
            for endpoint in endpoints:
                with self.subTest(selector=bad, endpoint=endpoint), self.assertRaises(ValueError):
                    endpoint(bad)
        self.fake.get_doc.assert_not_called()

    def test_scalar_names_still_enforce_business_access_and_return_allowed_case(self):
        with self.assertRaises(PermissionError):
            cases.read('LOCAL-SUPPLIER-CASE')
        result = cases.read('LOCAL-CUSTOMER-CASE')
        self.assertEqual(result['title'], 'Local order for 84750')
        self.assertEqual(result['field_values'], {'amount': 84750})
        for name in ('Legacy name with spaces', 'नाम', 'x' * 140):
            self.assertEqual(access.document_name(name), name)

    def test_other_request_loaders_reject_filters_and_accept_scalar_names(self):
        class Loaded(Exception):
            pass

        endpoints = [
            ('reports', 'from_run', 'Relay Automation Run'),
            ('enrollment', 'revoke', 'Relay Contact Endpoint'),
            ('message_reads', 'coverage', 'Relay Message'),
            ('collaboration', 'mark_notification', 'Relay Notification'),
            ('messaging', 'reconcile', 'Relay Message Action'),
            ('messaging', 'retry', 'Relay Message Action'),
            ('messaging', 'dismiss', 'Relay Message Action'),
            ('call_records', 'recordings', 'Relay Call'),
            ('prepared_reports', 'status', 'Prepared Report'),
            ('business_events', 'template_preview', 'Relay WhatsApp Template'),
            ('summaries', 'read', 'Relay Conversation Summary'),
            ('teams', 'read', 'Relay Team'),
            ('automation.service', 'enqueue', 'Relay Message'),
            ('automation.channel', 'read', 'Relay Channel'),
        ]
        for path, method, doctype in endpoints:
            target = importlib.import_module('relay_core.' + path)
            with self.subTest(endpoint=path + '.' + method), patch.object(target, 'frappe', self.fake), \
                    patch('relay_core.permissions.require_access'), patch.object(target, 'require_access', create=True):
                self.fake.get_doc.reset_mock()
                for bad in ({'title': ['like', 'Secret%']}, {}, ['like', '%'], 'x' * 141):
                    with self.assertRaises(ValueError):
                        getattr(target, method)(bad)
                self.fake.get_doc.assert_not_called()
                self.fake.get_doc.side_effect = Loaded
                with self.assertRaises(Loaded):
                    getattr(target, method)('LOCAL-RECORD')
                self.fake.get_doc.assert_called_once_with(doctype, 'LOCAL-RECORD')

    def test_optional_editor_names_reject_empty_filter_objects_without_creating_documents(self):
        endpoints = [('business_events', 'save'), ('ai.configuration', 'save'),
                     ('automation.settings', 'save_policy'), ('flows.service', 'save'),
                     ('flows.service', 'validate_draft')]
        for path, method in endpoints:
            target = importlib.import_module('relay_core.' + path)
            with self.subTest(endpoint=path + '.' + method), patch.object(target, 'frappe', self.fake):
                for name in ({}, {'enabled': 1}, [], False):
                    with self.assertRaises(ValueError):
                        getattr(target, method)({}, name=name)
        self.fake.get_doc.assert_not_called()
        self.fake.new_doc.assert_not_called()


class CachedChatTitleTests(unittest.TestCase):
    def test_generic_document_and_list_reads_strip_cached_title_but_keep_business_identity(self):
        """Exercise Frappe's actual field filters against the versioned DocType metadata."""
        schema = json.loads(Path('relay_core/relay_core/doctype/relay_chat/relay_chat.json').read_text())
        fields = [_dict(field, permlevel=field.get('permlevel', 0)) for field in schema['fields']]
        permissions = [_dict(row, permlevel=row.get('permlevel', 0)) for row in schema['permissions']]
        meta = SimpleNamespace(name='Relay Chat', istable=0, fields=fields, permissions=permissions,
            get_table_fields=lambda **kw: [], get_permissions=lambda *a, **kw: permissions,
            get_fieldnames_with_value=lambda **kw: fields)
        meta.get_permlevel_access = lambda **kw: Meta.get_permlevel_access(meta, **kw)
        fake = fake_frappe()
        for role in ('Relay Communication User', 'Relay Communication Team User', 'Relay Communication Manager', 'System Manager'):
            fake.get_roles.return_value = [role]
            with self.subTest(role=role), patch('frappe.model.document.frappe', fake), patch('frappe.model.meta.frappe', fake):
                doc = SimpleNamespace(meta=meta, title='Old private cached value', business_name='LOCAL-C1', mask_fields=Mock())
                doc.get_permissions = lambda: permissions
                doc.get_permlevel_access = lambda kind: Document.get_permlevel_access(doc, kind)
                Document.apply_fieldlevel_read_permissions(doc)
                self.assertFalse(hasattr(doc, 'title'))
                self.assertEqual(doc.business_name, 'LOCAL-C1')
                permitted = Meta.get_permitted_fieldnames(meta)
                for requested in (['title', 'business_name'], ['*']):
                    query = SimpleNamespace(flags=_dict(ignore_permissions=False), doctype='Relay Chat', parent_doctype=None,
                        permission_map={}, fields=requested.copy(), linked_table_aliases={})
                    query.remove_field = lambda index: query.fields.pop(index)
                    with patch('frappe.model.db_query.get_permitted_fields', return_value=permitted):
                        DatabaseQuery.apply_fieldlevel_read_permissions(query)
                    self.assertNotIn('title', query.fields)
                    self.assertIn('business_name', query.fields)


class PrimaryOwnerTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_frappe()
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE `tabRelay Message`
            (name TEXT, relay_contact TEXT, business_doctype TEXT, business_name TEXT, legacy_triage INTEGER);
            INSERT INTO `tabRelay Message` VALUES ('local-history','R1',NULL,NULL,0),
            ('local-stamped','R1','Customer','C1',0), ('local-triage','R1',NULL,NULL,1);''')
        self.relay = _dict(name='R1', primary_doctype='Supplier', primary_name='S1')
        self.relay.save = Mock()
        self.person = _dict(name='P1', check_permission=Mock(), links=[Doc(link_doctype='Supplier', link_name='S1'), Doc(link_doctype='Customer', link_name='C1')])
        self.person.save = Mock()
        self.person.set = lambda key, value: self.person.update({key: [Doc(row) for row in value]})
        self.fake.get_doc.side_effect = lambda dt, name: self.person if dt == 'Contact' else self.relay if dt == 'Relay Contact' else Doc(name=name)
        self.fake.db.get_value.side_effect = lambda dt, name, fields, **kw: (
            (self.relay.primary_doctype, self.relay.primary_name) if isinstance(fields, list) else 'R1')
        self.fake.db.sql.side_effect = lambda sql, values: self.db.execute(sql.replace('%s', '?'), values)
        self.fake.get_all.return_value = ['Customer', 'Supplier']
        self.enterContext(patch.object(access, 'frappe', self.fake))
        self.enterContext(patch.object(contacts, 'frappe', self.fake))
        self.types = self.enterContext(patch.object(access, 'allowed_types', return_value={'Customer'}))
        self.enterContext(patch.object(contacts, 'allowed_types', self.types))
        self.enterContext(patch.object(access, 'candidates', side_effect=lambda contact: [
            (row.link_doctype, row.link_name) for row in self.person.links]))
        for helper in ('require_access', 'require_person', 'readable_contact', 'summary'):
            self.enterContext(patch.object(contacts, helper))
        self.enterContext(patch.object(contacts, 'can_manage_links', return_value=False))
        self.enterContext(patch('relay_core.relay_chats.merge'))

    def history(self):
        row = self.db.execute("SELECT business_doctype, business_name FROM `tabRelay Message` WHERE name='local-history'").fetchone()
        return _dict(doctype='Relay Message', relay_contact='R1', business_doctype=row[0], business_name=row[1])

    def test_contact_writer_cannot_replace_or_clear_an_inaccessible_primary(self):
        self.assertFalse(access.message_allowed(self.history()))
        for target in [('Customer', 'C1'), (None, None)]:
            with self.subTest(target=target), self.assertRaises(PermissionError):
                contacts.set_primary('P1', *target)
        self.relay.save.assert_not_called()
        self.fake.db.sql.assert_not_called()
        self.assertEqual(access.primary('R1'), ('Supplier', 'S1'))

    def test_authorized_change_preserves_history_and_does_not_overwrite_existing_ownership(self):
        self.types.return_value = {'Customer', 'Supplier'}
        contacts.set_primary('P1', 'Customer', 'C1')
        self.relay.save.assert_called_once_with(ignore_permissions=True)
        self.assertEqual(access.primary('R1'), ('Customer', 'C1'))
        self.assertTrue(access.message_allowed(self.history()))
        self.types.return_value = {'Customer'}
        self.assertFalse(access.message_allowed(self.history()))
        self.assertEqual(self.db.execute('SELECT business_doctype, business_name FROM `tabRelay Message` ORDER BY name').fetchall(),
                         [('Supplier', 'S1'), ('Customer', 'C1'), (None, None)])
        contacts.set_primary('P1')  # Clearing an accessible current owner is allowed.
        self.assertIsNone(access.primary('R1'))

    def test_link_removal_preserves_prior_owner_before_a_new_sole_link_takes_over(self):
        self.types.return_value = {'Customer', 'Supplier'}
        contacts.set_links('P1', [{'doctype': 'Customer', 'name': 'C1'}])
        self.person.save.assert_called_once()
        self.assertEqual(access.primary('R1'), ('Customer', 'C1'))
        self.types.return_value = {'Customer'}
        self.assertFalse(access.message_allowed(self.history()))
        self.assertEqual((self.history().business_doctype, self.history().business_name), ('Supplier', 'S1'))
