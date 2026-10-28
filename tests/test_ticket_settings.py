"""Ticket settings: Open and Closed status types, manager-only writes, in-use protection and the patch. No site data is touched."""
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
        self.statuses = {'Open': 'Open', 'Started': 'Open', 'Done': 'Closed'}
        self.f = types.SimpleNamespace(throw=throw, PermissionError=PermissionError, whitelist=lambda **kw: lambda fn: fn,
            db=types.SimpleNamespace(get_value=Mock(side_effect=lambda doctype, name, field: self.statuses.get(name)),
                                     count=Mock(return_value=0), exists=Mock(return_value=False)),
            get_all=Mock(return_value=['Open']), has_permission=Mock(return_value=False), get_doc=Mock())
        self.module = load('tested_ticket_settings', 'relay_core/ticket_settings.py', self.f)

    def test_seeding_creates_only_the_missing_status_types(self):
        self.f.db.exists = Mock(side_effect=lambda doctype, filters: filters == {'state': 'Open'})
        self.module.seed_defaults()
        inserted = [call.args[0] for call in self.f.get_doc.call_args_list]
        self.assertEqual([(row['label'], row['state']) for row in inserted], [('Closed', 'Closed')])

    def test_seeding_creates_no_ticket_types(self):
        self.module.seed_defaults()
        self.assertEqual({call.args[0]['doctype'] for call in self.f.get_doc.call_args_list}, {'Relay Ticket Status'})

    def test_a_ticket_without_status_starts_in_the_first_open_status(self):
        doc = Doc(ticket_status=None)
        self.module.apply(doc)
        self.assertEqual(doc.ticket_status, 'Open')
        self.assertEqual(self.f.get_all.call_args.kwargs['filters'], {'state': 'Open'})
        doc = Doc(ticket_status='Done')
        self.module.apply(doc)
        self.assertEqual(doc.ticket_status, 'Done')

    def test_a_missing_status_type_is_reported(self):
        self.f.get_all.return_value = []
        with self.assertRaisesRegex(ValueError, 'type Closed'):
            self.module.status_of('Closed')

    def test_a_ticket_is_closed_by_the_type_of_its_status(self):
        self.assertTrue(self.module.is_closed(Doc(ticket_status='Done')))
        self.assertFalse(self.module.is_closed(Doc(ticket_status='Started')))

    def test_writes_are_for_managers_only(self):
        for call in (lambda: self.module.save('status', 'Waiting', state='Open'), lambda: self.module.reorder('type', ['General']),
                     lambda: self.module.remove('type', 'General')):
            with self.assertRaises(PermissionError):
                call()
        with self.assertRaises(ValueError):
            self.module.save('category', 'x')
        self.f.get_doc.assert_not_called()
        self.f.has_permission.assert_any_call('Relay Ticket Status', 'write')

    def test_a_value_in_use_cannot_be_deleted(self):
        self.f.db.exists = Mock(return_value=True)
        with self.assertRaises(ValueError):
            self.module.block_used_setting(types.SimpleNamespace(doctype='Relay Ticket Type', name='Billing'))
        self.f.db.exists.assert_called_with('Relay Ticket', {'ticket_type': 'Billing'})

    def test_the_last_status_of_a_type_cannot_be_deleted(self):
        status = types.SimpleNamespace(doctype='Relay Ticket Status', name='Done', state='Closed')
        with self.assertRaisesRegex(ValueError, 'type Closed'):
            self.module.block_used_setting(status)
        self.f.db.count.assert_called_with('Relay Ticket Status', {'state': 'Closed', 'name': ['!=', 'Done']})
        self.f.db.count.return_value = 1
        self.module.block_used_setting(status)

    def test_the_type_of_a_status_that_tickets_use_cannot_change(self):
        self.f.db.count = Mock(return_value=3)
        doc = Doc(doctype='Relay Ticket Status', name='Waiting', state='Closed', before=types.SimpleNamespace(state='Open'))
        with self.assertRaisesRegex(ValueError, '3 tickets use this status. Create a new status instead.'):
            self.module.validate_status(doc)
        self.f.db.count.assert_any_call('Relay Ticket', {'ticket_status': 'Waiting'})
        self.f.db.count.side_effect = lambda doctype, filters: 0 if doctype == 'Relay Ticket' else 1
        self.module.validate_status(doc)


class StatusTypePatchTests(unittest.TestCase):
    def test_patch_maps_old_states_and_fills_empty_statuses(self):
        updates = []
        frappe = types.SimpleNamespace(
            whitelist=lambda **kw: lambda fn: fn,
            db=types.SimpleNamespace(sql=lambda query, values: updates.append(values), exists=Mock(return_value=True),
                                     has_column=Mock(return_value=True)),
            get_all=Mock(side_effect=lambda doctype, filters, **kw: [filters['state']]), get_doc=Mock())
        settings = load('tested_settings_for_patch', 'relay_core/ticket_settings.py', frappe)
        package = types.ModuleType('relay_core')
        package.ticket_settings = settings
        with patch.dict(sys.modules, {'frappe': frappe, 'relay_core': package}):
            spec = importlib.util.spec_from_file_location('tested_patch', Path('relay_core/patches/v1_0/use_open_and_closed_ticket_statuses.py'))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.execute()
        self.assertEqual(updates, [('Open', 'In progress'), ('Closed', 'Resolved'),
            ('Open', 'Open'), ('Open', 'In progress'), ('Closed', 'Resolved'), ('Closed', 'Closed')])
        frappe.get_doc.assert_not_called()
