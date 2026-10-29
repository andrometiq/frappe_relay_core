"""Contact sheet planning, permissions and revalidation without a database."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from relay_core import contact_import as service


class Person(dict):
    __getattr__ = dict.get

    def check_permission(self, kind):
        if self.get('denied'):
            raise PermissionError

    def apply_fieldlevel_read_permissions(self):
        pass


class ContactImportTests(TestCase):
    def setUp(self):
        self.fake = SimpleNamespace(PermissionError=PermissionError, ValidationError=ValueError,
            DoesNotExistError=LookupError, has_permission=Mock(return_value=True),
            db=Mock(), get_all=Mock(return_value=[]), get_doc=Mock(), get_list=Mock(),
            log_error=Mock(), session=SimpleNamespace(user='staff'), get_roles=lambda: [])
        self.fake.db.exists.return_value = True
        self.people = {}
        self.fake.get_doc.side_effect = lambda dt, name: self.people[name]
        self.fake.get_all.side_effect = self.get_all
        self.fake.db.sql.side_effect = lambda *args, **kwargs: [Person(name=name, creation='2026-01-01',
            phone=person.mobile_no, mobile_no='', contact_phone='', relay=None, customer=False)
            for name, person in self.people.items()]
        self.patchers = [patch.object(service, 'frappe', self.fake),
            patch('frappe.db', self.fake.db),
            patch.object(service.contacts, 'business_links'), patch.object(service.contacts, 'can_manage_links', return_value=True),
            patch.object(service.contacts, 'display_name', side_effect=lambda value: value),
            patch.object(service.contacts, 'ensure_relay', return_value='relay'),
            patch.object(service.contacts, 'new_person', side_effect=self.create),
            patch.object(service.contacts, 'add_link', side_effect=self.link)]
        for item in self.patchers:
            item.start(); self.addCleanup(item.stop)

    def get_all(self, doctype, *, filters, fields):
        if doctype in ('Contact', 'Contact Email'):
            return [Person(name=name, parent=name, email_id=person.email_id)
                    for name, person in self.people.items() if person.email_id in filters['email_id'][1]]
        return []

    def create(self, label, mobile, email=None):
        name = 'Person ' + str(len(self.people) + 1)
        person = Person(name=name, full_name=label, mobile_no=mobile, email_id=email, links=[])
        self.people[name] = person
        return person

    def link(self, name, doctype, record):
        self.people[name].links.append(SimpleNamespace(link_doctype=doctype, link_name=record))

    def row(self, mobile='9876543210', email='', record='LOCAL-1', kind='Customer'):
        return dict(zip(service.COLUMNS, [mobile, email, 'Local import person', kind, record]))

    def test_excel_numbers_and_email_normalization(self):
        for mobile in ('9876543210', '9876543210.0', '9.19876543210E+11', '+91 98765 43210'):
            row = service.normalize_row(self.row(mobile, ' Person@Example.Invalid '), 'IN')
            self.assertEqual((row['mobile'], row['email']), ('919876543210', 'person@example.invalid'))
        for mobile in ('123', '1.5e3', '9.1234567890123456e15'):
            with self.assertRaises(ValueError): service.normalize_row(self.row(mobile), 'IN')

    def test_preview_merges_duplicates_and_plans_one_person_with_two_links(self):
        rows = [(2, self.row()), (3, self.row('9876543210.0')), (4, self.row(record='LOCAL-2'))]
        preview = service.process(rows, 'IN')
        self.assertEqual([row['status'] for row in preview['rows']], ['create', 'skip', 'link'])
        self.assertEqual(preview['counts'], dict(created=1, linked=1, skipped=1, errors=0))
        self.assertFalse(self.people)
        result = service.process(rows, 'IN', apply=True)
        self.assertEqual(result['counts'], preview['counts'])
        self.assertEqual(len(self.people), 1)
        self.assertEqual(len(next(iter(self.people.values())).links), 2)

    def test_existing_contact_gets_link_and_reimport_skips(self):
        person = self.create('Existing', '919876543210')
        rows = [(2, self.row())]
        self.assertEqual(service.process(rows, 'IN')['rows'][0]['status'], 'link')
        self.assertEqual(service.process(rows, 'IN', apply=True)['counts']['linked'], 1)
        self.assertEqual(len(self.people), 1)
        self.assertEqual(person.links[0].link_name, 'LOCAL-1')
        self.assertEqual(service.process(rows, 'IN', apply=True)['counts']['skipped'], 1)

    def test_short_national_phone_uses_import_channel_region_in_preview_and_apply(self):
        person = self.create('Local Singapore contact', '81234567')
        rows = [(2, self.row('+65 81234567')), (3, self.row('8123 4567'))]
        with patch.object(service, 'require_manager'), patch.object(service, 'source_rows', return_value=rows), \
                patch.object(service.contacts, 'whatsapp_channel'), \
                patch('relay_core.bulk_campaigns.channel_region', return_value='SG') as channel_region, \
                patch.object(service.identity, 'default_region', return_value='IN'):
            preview = service.preview('/private/files/local.csv', channel='LOCAL-SG')
            channel_region.assert_called_once_with('LOCAL-SG')
            result = service.process(rows, 'SG', apply=True)
        self.assertEqual(preview['counts'], dict(created=0, linked=1, skipped=1, errors=0))
        self.assertEqual(result['counts'], preview['counts'])
        service.contacts.new_person.assert_not_called()
        self.assertEqual(person.links[0].link_name, 'LOCAL-1')
        self.assertEqual(service.process(rows, 'SG')['counts']['skipped'], 2)
        self.assertNotIn('LIKE', self.fake.db.sql.call_args.args[0])

    def test_two_thousand_duplicate_rows_resolve_identities_once_including_misses(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                self.people.clear()
                if existing:
                    self.create('Local existing contact', '919876543210', 'local@example.invalid')
                rows = [(number, self.row(email='local@example.invalid')) for number in range(2, 2002)]
                for apply in (False, True):
                    self.fake.db.sql.reset_mock(); self.fake.get_all.reset_mock()
                    result = service.process(rows, 'IN', apply=apply)
                    self.assertEqual(result['counts'], dict(created=int(not existing), linked=int(existing), skipped=1999, errors=0))
                    self.fake.db.sql.assert_called_once()
                    self.assertEqual([call.args[0] for call in self.fake.get_all.call_args_list],
                                     ['Contact Email', 'Contact', 'Relay Contact Endpoint'])

    def test_distinct_identities_and_endpoint_owners_are_batched_and_conflicts_preserved(self):
        person = self.create('Local endpoint owner', '', '')
        def get_all(doctype, **kwargs):
            if doctype == 'Relay Contact Endpoint':
                return [Person(endpoint='+919876543210', relay_contact='LOCAL-RELAY'),
                        Person(endpoint='Local@Example.Invalid', relay_contact='LOCAL-RELAY')]
            if doctype == 'Relay Contact':
                return [Person(name='LOCAL-RELAY', contact=person.name)]
            return self.get_all(doctype, **kwargs)
        self.fake.get_all.side_effect = get_all
        rows = [(2, self.row(email='local@example.invalid')),
                (3, self.row('9123456789', 'other@example.invalid'))]
        result = service.process(rows, 'IN')
        self.assertEqual([row['status'] for row in result['rows']], ['link', 'create'])
        self.fake.db.sql.assert_called_once()
        self.assertEqual(len(self.fake.get_all.call_args_list), 4)
        self.assertEqual(self.fake.get_all.call_args_list[0].kwargs['filters']['email_id'],
                         ['in', ['local@example.invalid', 'other@example.invalid']])
        self.create('Conflicting local phone owner', '919876543210')
        self.assertIn('different contacts', service.process(rows, 'IN')['rows'][0]['reason'])

    def test_email_only_and_unlinked_contact(self):
        rows = [(2, self.row('', 'local@example.invalid', '', ''))]
        self.assertEqual(service.process(rows, 'IN', apply=True)['counts']['created'], 1)
        self.assertEqual(service.process(rows, 'IN')['counts']['skipped'], 1)

    def test_conflicting_identities_and_hidden_contact_are_friendly_errors(self):
        self.create('Mobile owner', '919876543210')
        self.create('Email owner', '', 'second@example.invalid')
        result = service.process([(2, self.row(email='second@example.invalid'))], 'IN')
        self.assertIn('different contacts', result['rows'][0]['reason'])
        self.people['Person 1']['denied'] = True
        result = service.process([(2, self.row())], 'IN', apply=True)
        self.assertEqual(result['counts']['errors'], 1)
        self.assertIn('permission', result['rows'][0]['reason'])
        self.fake.db.rollback.assert_called_with(save_point='contact_import_row')

    def test_apply_revalidates_permissions_and_record_after_preview(self):
        rows = [(2, self.row())]
        self.assertEqual(service.process(rows, 'IN')['counts']['created'], 1)
        self.fake.has_permission.return_value = False
        self.assertEqual(service.process(rows, 'IN', apply=True)['counts']['errors'], 1)
        self.fake.has_permission.return_value = True
        service.contacts.business_links.side_effect = LookupError
        self.assertIn('does not exist', service.process(rows, 'IN', apply=True)['rows'][0]['reason'])
        self.assertFalse(self.people)

    def test_invalid_type_and_record_and_good_rows_still_apply(self):
        self.fake.db.exists.side_effect = lambda dt, values: values['business_doctype'] == 'Customer'
        rows = [(2, self.row(kind='Disabled')), (3, self.row(record='')), (4, self.row())]
        result = service.process(rows, 'IN', apply=True)
        self.assertEqual(result['counts'], dict(created=1, linked=0, skipped=0, errors=2))
        self.assertIn('enabled', result['rows'][0]['reason'])
        self.assertIn('both', result['rows'][1]['reason'])

    def test_unexpected_server_errors_are_not_exposed_as_row_reasons(self):
        service.contacts.new_person.side_effect = ValueError('SQL traceback with private internal data')
        result = service.process([(2, self.row())], 'IN', apply=True)
        self.assertEqual(result['counts']['errors'], 1)
        self.assertNotIn('SQL', result['rows'][0]['reason'])
        self.assertIn('Check the contact details', result['rows'][0]['reason'])
        self.fake.db.rollback.assert_called_once_with(save_point='contact_import_row')

    def test_endpoints_reject_nonmanagers_before_reading_files_or_contacts(self):
        def denied(message, exception):
            raise exception(message)
        self.fake.throw = denied
        for endpoint, args in ((service.preview, ('file.csv',)), (service.apply, ('file.csv',)), (service.export, ())):
            with self.assertRaises(PermissionError): endpoint(*args)
        self.fake.get_doc.assert_not_called()
        self.fake.get_list.assert_not_called()

    def test_manager_roles_only(self):
        self.assertFalse(service.allowed('staff', ['Relay Communication User']))
        for role in ('System Manager', 'Relay Communication Manager'):
            self.assertTrue(service.allowed('staff', [role]))
        self.assertTrue(service.allowed('Administrator', []))

    def test_export_shape_and_unreadable_links(self):
        person = self.create('Local person', '919876543210', 'local@example.invalid')
        self.link(person.name, 'Customer', 'LOCAL-1'); self.link(person.name, 'Customer', 'HIDDEN')
        unlinked = self.create('Unlinked', '', 'unlinked@example.invalid')
        self.fake.get_list.side_effect = [[person.name, unlinked.name], []]
        with patch.object(service.contacts, 'readable', side_effect=lambda link: link.link_name != 'HIDDEN'):
            rows = list(service.export_rows())
        self.assertEqual(rows, [list(service.COLUMNS), ['919876543210', 'local@example.invalid', 'Local person', 'Customer', 'LOCAL-1'],
                                ['', 'unlinked@example.invalid', 'Unlinked', '', '']])

    def test_file_limit_headers_and_excel_numeric_cells(self):
        from openpyxl import Workbook
        with TemporaryDirectory(dir='.runtime/phase2') as directory:
            path = Path(directory) / 'contacts.xlsx'
            book = Workbook(); sheet = book.active; sheet.append(service.COLUMNS)
            sheet.append([919876543210, '', 'Local', '', '']); sheet['A2'].number_format = '0.00E+00'
            book.save(path)
            file = SimpleNamespace(file_size=path.stat().st_size, get_full_path=lambda: str(path))
            with patch('relay_core.bulk_campaigns.uploaded_file', return_value=file):
                rows = service.source_rows('/private/files/contacts.xlsx')
                self.assertEqual(service.process(rows, 'IN')['counts']['created'], 1)
                with patch.object(service, 'MAX_ROWS', 0), self.assertRaisesRegex(ValueError, '2000'):
                    service.source_rows('/private/files/contacts.xlsx')
            bad = iter([(2, {'Unexpected': 'x'})])
            with patch('relay_core.bulk_campaigns.uploaded_file', return_value=file), patch.object(service.bulk_sheet, 'read_rows', return_value=bad):
                with self.assertRaisesRegex(ValueError, 'columns'): service.source_rows('/private/files/contacts.xlsx')

    def test_parser_failures_return_friendly_preview_errors(self):
        friendly = 'The file could not be read. Save it as Excel (.xlsx) or UTF-8 CSV.'
        with TemporaryDirectory(dir='.runtime/phase2') as directory:
            for name, content in (('contacts.csv', b'Mobile,Email\n\xff,private'), ('contacts.xlsx', b'not a workbook')):
                with self.subTest(name=name):
                    path = Path(directory) / name
                    path.write_bytes(content)
                    file = SimpleNamespace(file_size=len(content), get_full_path=lambda: str(path))
                    with patch.object(service, 'require_manager'), \
                            patch('relay_core.bulk_campaigns.uploaded_file', return_value=file):
                        self.assertEqual(service.preview('/private/files/' + name), {'error': friendly})
                        self.assertEqual(service.apply('/private/files/' + name), {'error': friendly})
                        with patch.object(service.bulk_sheet, 'read_rows', side_effect=ValueError('private parser details')):
                            self.assertEqual(service.preview('/private/files/' + name), {'error': friendly})
