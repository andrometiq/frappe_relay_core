"""Ticket settings: status to state mapping, manager-only writes, in-use protection and the patch. No site data is touched."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class Doc(types.SimpleNamespace):
    def get(self, key):
        return getattr(self, key, None)

    def get_doc_before_save(self):
        return self.before


def load(name, path, frappe):
    spec = importlib.util.spec_from_file_location(name, Path(path))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'frappe': frappe}):
        spec.loader.exec_module(module)
    return module


class TicketSettingsTests(unittest.TestCase):
    def setUp(self):
        def throw(message, exception=ValueError):
            raise exception(message)
        self.statuses = {'Open': ('Open', 1), 'Started': ('In progress', 1), 'Done': ('Resolved', 1), 'Old': ('Closed', 0), 'Closed': ('Closed', 1)}
        self.options = {'Relay Ticket Category': {'Support': 1, 'Hidden': 0}, 'Relay Ticket Type': {'General': 1}}

        def get_value(doctype, name, field):
            if doctype == 'Relay Ticket Status':
                row = self.statuses.get(name)
                return None if not row else (row[0] if field == 'state' else row[1])
            return self.options[doctype].get(name)
        self.f = types.SimpleNamespace(throw=throw, PermissionError=PermissionError, whitelist=lambda **kw: lambda fn: fn,
            db=types.SimpleNamespace(get_value=Mock(side_effect=get_value), count=Mock(return_value=0)),
            get_all=Mock(return_value=[types.SimpleNamespace(name='Open')]), has_permission=Mock(return_value=False), get_doc=Mock())
        self.module = load('tested_ticket_settings', 'relay_core/ticket_settings.py', self.f)

    def ticket(self, **values):
        return Doc(**{'status': 'Open', 'category': 'Support', 'ticket_type': None, 'ticket_status': None, 'before': None, **values})

    def test_seeding_fills_only_empty_lists(self):
        self.f.db.count = Mock(side_effect=lambda doctype: 0 if doctype == 'Relay Ticket Type' else 3)
        self.module.seed_defaults()
        inserted = [call.args[0] for call in self.f.get_doc.call_args_list]
        self.assertEqual([row['doctype'] for row in inserted], ['Relay Ticket Type'])

    def test_picked_status_sets_the_state(self):
        doc = self.ticket(ticket_status='Started')
        self.module.apply(doc)
        self.assertEqual(doc.status, 'In progress')

    def test_plain_state_change_uses_the_default_status_of_that_state(self):
        before = self.ticket(status='Open', ticket_status='Open')
        doc = self.ticket(status='Closed', ticket_status='Open', before=before)
        self.f.get_all.return_value = [types.SimpleNamespace(name='Closed')]
        self.module.apply(doc)
        self.assertEqual((doc.status, doc.ticket_status), ('Closed', 'Closed'))
        self.assertEqual(self.f.get_all.call_args.kwargs['filters'], {'state': 'Closed', 'enabled': 1})

    def test_a_status_that_still_matches_the_state_is_kept(self):
        before = self.ticket(status='In progress', ticket_status='Started')
        doc = self.ticket(status='In progress', ticket_status='Started', before=before)
        self.module.apply(doc)
        self.assertEqual(doc.ticket_status, 'Started')
        self.f.get_all.assert_not_called()

    def test_unknown_or_disabled_values_are_rejected(self):
        for values in ({'ticket_status': 'Nope'}, {'ticket_status': 'Old'}, {'category': 'Hidden'}, {'category': 'Nope'}, {'ticket_type': 'Nope'}, {'status': 'anything'}):
            with self.subTest(values), self.assertRaises(ValueError):
                self.module.apply(self.ticket(**values))

    def test_a_disabled_category_stays_valid_on_a_ticket_that_already_has_it(self):
        before = self.ticket(category='Hidden')
        self.module.apply(self.ticket(category='Hidden', before=before, ticket_status='Open'))

    def test_writes_are_for_managers_only(self):
        for call in (lambda: self.module.save('status', 'Waiting', state='Open'), lambda: self.module.reorder('category', ['Support'])):
            with self.assertRaises(PermissionError):
                call()
        with self.assertRaises(ValueError):
            self.module.save('bogus', 'x')
        self.f.get_doc.assert_not_called()
        self.f.has_permission.assert_any_call('Relay Ticket Status', 'write')

    def test_a_value_in_use_cannot_be_deleted(self):
        self.f.db.exists = Mock(return_value=True)
        with self.assertRaises(ValueError):
            self.module.block_used_setting(types.SimpleNamespace(doctype='Relay Ticket Category', name='Support'))
        self.f.db.exists.assert_called_with('Relay Ticket', {'category': 'Support'})
        self.f.db.exists.return_value = False
        self.module.block_used_setting(types.SimpleNamespace(doctype='Relay Ticket Status', name='Open'))

    def test_the_last_enabled_status_of_a_state_cannot_be_turned_off(self):
        self.f.db.count = Mock(return_value=0)
        before = types.SimpleNamespace(enabled=1, state='Closed')
        doc = Doc(doctype='Relay Ticket Status', name='Closed', enabled=0, state='Closed', before=before)
        with self.assertRaises(ValueError):
            self.module.validate_setting(doc)
        self.f.db.count.assert_called_with('Relay Ticket Status', {'enabled': 1, 'name': ['!=', 'Closed'], 'state': 'Closed'})
        self.f.db.count.return_value = 1
        self.module.validate_setting(doc)

    def test_the_state_of_a_status_that_tickets_use_cannot_change(self):
        self.f.db.count = Mock(return_value=3)
        before = types.SimpleNamespace(enabled=1, state='Open')
        doc = Doc(doctype='Relay Ticket Status', name='Waiting', enabled=1, state='Resolved', before=before)
        with self.assertRaisesRegex(ValueError, '3 tickets use this status. Create a new status instead.'):
            self.module.validate_setting(doc)
        self.f.db.count.assert_called_with('Relay Ticket', {'ticket_status': 'Waiting'})
        self.f.db.count.side_effect = lambda doctype, filters: 0 if doctype == 'Relay Ticket' else 1
        self.module.validate_setting(doc)

    def test_every_default_status_maps_to_one_distinct_state(self):
        self.assertEqual([row[1] for row in self.module.DEFAULT_STATUSES], list(self.module.STATES))


class ConfigurePatchTests(unittest.TestCase):
    def test_patch_creates_what_is_missing_and_fills_empty_statuses_twice_safely(self):
        created, updates = [], []
        existing = {'Relay Ticket Category': {'Query'}, 'Relay Ticket Status': set()}

        def insert_doc(values):
            created.append((values['doctype'], values['label']))
            existing.setdefault(values['doctype'], set()).add(values['label'])
            return types.SimpleNamespace(insert=Mock())
        frappe = types.SimpleNamespace(
            whitelist=lambda **kw: lambda fn: fn,
            db=types.SimpleNamespace(table_exists=Mock(return_value=True), exists=lambda doctype, name: name in existing.get(doctype, set()),
                                     count=lambda doctype: len(existing.get(doctype, ())),
                                     sql=lambda query, values: updates.append(values)),
            get_all=Mock(side_effect=lambda doctype, **kw: ['Query', 'Legacy'] if doctype == 'Relay Ticket' else [types.SimpleNamespace(name='Open')]),
            get_doc=insert_doc)
        settings = load('tested_settings_for_patch', 'relay_core/ticket_settings.py', frappe)
        package = types.ModuleType('relay_core')
        package.ticket_settings = settings
        with patch.dict(sys.modules, {'frappe': frappe, 'relay_core': package}):
            spec = importlib.util.spec_from_file_location('tested_patch', Path('relay_core/patches/v1_0/configure_ticket_settings.py'))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.execute()
            first = list(created)
            module.execute()
        self.assertIn(('Relay Ticket Category', 'Legacy'), first)
        self.assertNotIn(('Relay Ticket Category', 'Query'), first)
        self.assertEqual({label for doctype, label in first if doctype == 'Relay Ticket Status'}, {'Open', 'In progress', 'Resolved', 'Closed'})
        self.assertEqual(created, first)
        self.assertEqual(len(updates), 8)
