"""Sheet contact enrollment and private template header resolution and retries."""
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import frappe
from frappe import _dict
from relay_core import bulk_campaigns as bulk, bulk_sheet, campaign_media, contact_lifecycle
from site_file_limit import use_relay_file_limit

NUMBER = '919876543210'
FIELDS = bulk_sheet.template_fields({'components': [{'type': 'HEADER', 'format': 'IMAGE'}]})


def attachment(mode='static', *names):
    return {'mode': mode, 'files': [{'file_url': '/private/files/' + name, 'filename': name} for name in names]}


def setUpModule():
    use_relay_file_limit()


class SheetContactTests(unittest.TestCase):
    def setUp(self):
        self.fake = SimpleNamespace(db=Mock(get_value=Mock(return_value=None)), cache=SimpleNamespace(lock=MagicMock()))
        self.enterContext(patch.object(bulk, 'frappe', self.fake))
        self.sibling = self.enterContext(patch.object(contact_lifecycle, 'sibling_contact', return_value=None))
        self.create = self.enterContext(patch.object(contact_lifecycle, 'whatsapp_contact', return_value='RELAY-C1'))

    def test_length_possible_but_invalid_number_is_not_enrolled(self):
        for number in ('9199999787611', '911234567890', '914423456789'):
            self.assertEqual(bulk.sheet_contact('WA', number), ('invalid', 'Invalid phone number'))
        self.create.assert_not_called()
        self.fake.cache.lock.assert_not_called()

    def test_new_number_uses_shared_helper_and_commits_before_unlock(self):
        events = []
        lock = self.fake.cache.lock.return_value
        lock.__enter__.side_effect = lambda: events.append('lock')
        lock.__exit__.side_effect = lambda *args: events.append('unlock')
        self.fake.db.commit.side_effect = lambda: events.append('commit')
        self.create.side_effect = lambda *args, **kwargs: events.append('create') or 'RELAY-C1'
        self.assertEqual(bulk.sheet_contact('WA', NUMBER), ('created', None))
        self.create.assert_called_once_with('WA', NUMBER, locked=True)
        self.assertEqual(events, ['lock', 'commit', 'create', 'commit', 'unlock'])
        self.fake.db.get_value.assert_called_once_with('Relay Contact Endpoint',
            {'endpoint_key': contact_lifecycle.endpoint_key('WA', NUMBER)}, ['relay_contact', 'verified'], as_dict=True, for_update=True)

    def test_existing_number_and_opt_out_are_never_rewritten(self):
        self.fake.db.get_value.return_value = _dict(relay_contact='RELAY-C1', verified=1, marketing_opt_out=1)
        self.assertEqual(bulk.sheet_contact('WA', NUMBER), ('existing', None))
        self.create.assert_not_called()
        self.fake.db.set_value.assert_not_called()

    def test_revoked_binding_stays_revoked(self):
        self.fake.db.get_value.return_value = _dict(relay_contact='RELAY-C1', verified=0)
        self.assertEqual(bulk.sheet_contact('WA', NUMBER), ('existing', 'Endpoint verification revoked'))
        self.create.assert_not_called()

    def test_sibling_contact_gets_endpoint_without_another_person(self):
        self.sibling.return_value = 'RELAY-C1'
        self.assertEqual(bulk.sheet_contact('WA', NUMBER), ('created', None))
        self.create.assert_not_called()

    def test_ambiguous_binding_blocks_the_row(self):
        self.create.return_value = None
        self.assertEqual(bulk.sheet_contact('WA', NUMBER), ('existing', 'Contact binding needs review'))

    def test_failed_enrollment_rolls_back(self):
        self.create.side_effect = RuntimeError('failed')
        with self.assertRaisesRegex(RuntimeError, 'failed'):
            bulk.sheet_contact('WA', NUMBER)
        self.fake.db.rollback.assert_called_once()

    def test_concurrent_imports_share_one_creation_path(self):
        lock, existing = threading.Lock(), []
        self.fake.cache.lock.side_effect = lambda *args, **kwargs: lock
        self.fake.db.get_value.side_effect = lambda *args, **kwargs: existing[0] if existing else None
        def create(*args, **kwargs):
            existing.append(_dict(relay_contact='RELAY-C1', verified=1))
            return 'RELAY-C1'
        self.create.side_effect = create
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: bulk.sheet_contact('WA', NUMBER), range(20)))
        self.assertEqual(results.count(('created', None)), 1)
        self.assertEqual(results.count(('existing', None)), 19)
        self.create.assert_called_once()

    def test_invalid_and_duplicate_rows_are_counted_without_duplicate_creation(self):
        doc = _dict(name='Sheet', source_file='/private/files/people.csv', channel='WA', country='IN',
                    arguments=json.dumps({'fields': []}), column_map=json.dumps({'phone': 'First', 'fields': {}, 'fixed': {}}))
        rows = [(2, {'First': NUMBER}), (3, {'First': '+91 98765 43210'}), (4, {'First': 'bad'})]
        with patch.object(bulk, 'insert_chunk') as insert:
            bulk.add_rows(doc, rows, set())
        values = insert.call_args.args[1]
        self.assertEqual([row[2]['contact_status'] for row in values], ['created', 'existing', 'invalid'])
        self.assertEqual([row[3] for row in values], [None, 'Duplicate row', 'Invalid phone number'])
        self.create.assert_called_once()

    def test_same_number_with_different_values_is_not_a_duplicate(self):
        doc = _dict(name='Sheet', source_file='/private/files/people.csv', channel='WA', country='IN',
                    arguments=json.dumps({'fields': [{'key': 'name', 'label': 'Name'}]}),
                    column_map=json.dumps({'phone': 'First', 'fields': {'name': 'Name'}, 'fixed': {}}))
        rows = [(2, {'First': NUMBER, 'Name': 'Asha'}), (3, {'First': NUMBER, 'Name': 'Ravi'}),
                (4, {'First': NUMBER, 'Name': 'Asha'})]
        with patch.object(bulk, 'insert_chunk') as insert:
            bulk.add_rows(doc, rows, set())
        self.assertEqual([row[3] for row in insert.call_args.args[1]], [None, None, 'Duplicate row'])

    def test_first_column_overrides_phone_name_guess_for_sheets_only(self):
        self.assertEqual(bulk_sheet.suggest(['Recipients', 'Phone'], [], first_phone=True)['phone'], 'Recipients')
        self.assertEqual(bulk_sheet.suggest(['Recipients', 'Phone'], [])['phone'], 'Phone')

    def test_held_rows_use_excel_normalisation_and_mobile_validation(self):
        doc = _dict(name='Sheet', country='IN', column_map=json.dumps({'phone': 'Mobile'}))
        rows = list(enumerate({'Mobile': value} for value in
                             ('919876543210.0', '9.19876543210E+11', '9199999787611', '914423456789')))
        self.fake.get_all = Mock(return_value=[_dict(destination=NUMBER, arguments=json.dumps({'values': {'name': 'Asha'}}))])
        self.assertEqual(bulk.held_rows(doc, rows), {bulk.row_key(NUMBER, {'values': {'name': 'Asha'}})})
        self.assertEqual(self.fake.get_all.call_args.kwargs['filters']['destination'], ['in', [NUMBER]])


class HeaderResolutionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.files = {}
        self.enterContext(patch.object(bulk, 'uploaded_file', side_effect=lambda url: self.files[url]))
        self.enterContext(patch('relay_core.template_media.frappe.throw', side_effect=ValueError))

    def file(self, name, raw=b'\x89PNG\r\n\x1a\n', private=1):
        path = self.root / name
        path.write_bytes(raw)
        file = _dict(file_name=name, file_url='/private/files/' + name, is_private=private, get_full_path=lambda: str(path))
        self.files[file.file_url] = file
        return file

    def test_static_file_is_used_for_every_number(self):
        self.file('offer.png')
        result = campaign_media.resolve(attachment('static', 'offer.png'), 'image', {NUMBER, '919876543211'}, 'IN')
        self.assertEqual(list(result.values()), [(attachment('static', 'offer.png')['files'][0], None)] * 2)

    def test_dynamic_full_and_national_number_matches(self):
        for name in (NUMBER + '.png', '9876543210.jpg', '98765 43210.jpg', '+91 98765-43210.png',
                     '09876543210.jpg', '(+91) 98765 43210.png', '91-9876543210.png',
                     '919876543210.0.png', '9.19876543210E+11.png'):
            self.file(name, b'\xff\xd8\xff' if name.endswith('.jpg') else b'\x89PNG\r\n\x1a\n')
            result = campaign_media.resolve(attachment('dynamic', name), 'image', {NUMBER}, 'IN')
            self.assertEqual(result[NUMBER], (attachment('dynamic', name)['files'][0], None))

    def test_missing_and_duplicate_matches_are_blocked(self):
        self.file(NUMBER + '.png')
        self.file('9876543210.jpg', b'\xff\xd8\xff')
        result = campaign_media.resolve(attachment('dynamic', NUMBER + '.png', '9876543210.jpg'), 'image', {NUMBER, '919876543211'}, 'IN')
        self.assertEqual(result[NUMBER][1], 'Duplicate header attachments')
        self.assertEqual(result['919876543211'][1], 'Missing header attachment')

    def test_sheet_and_json_rows_share_normalisation_with_header_files(self):
        name = '98765 43210.jpg'
        self.file(name, b'\xff\xd8\xff')
        mapping = {'phone': 'Mobile', 'fields': {}, 'fixed': {}, 'header_attachment': attachment('dynamic', name)}
        rows = list(enumerate(({'Mobile': value} for value in
                              ('919876543210.0', '9.19876543210E+11', '9199999787611', '914423456789')), 2))
        for source in (None, '/private/files/local-only-phones.csv'):
            doc = _dict(name='Sheet', source_file=source, channel='WA', country='IN',
                        arguments=json.dumps({'fields': FIELDS}), column_map=json.dumps(mapping))
            with self.subTest(source=source), patch.object(bulk, 'insert_chunk') as insert, \
                    patch.object(bulk, 'recipient_rows', return_value=iter(rows)), \
                    patch.object(bulk, 'sheet_contact', return_value=('created', None)) as enroll:
                bulk.add_rows(doc, iter(rows), set())
            found = insert.call_args.args[1]
            self.assertEqual([row[3] for row in found],
                             [None, 'Duplicate row', 'Invalid phone number', 'Invalid phone number'])
            self.assertEqual([row[1] for row in found[:2]], [NUMBER, NUMBER])
            self.assertEqual(found[0][2]['values']['header_media'], mapping['header_attachment']['files'][0])
            self.assertEqual(enroll.call_count, 1 if source else 0)

    def test_invalid_stems_are_ignored(self):
        for stem in ('9199999787611', '1234567890', '914423456789', 'offer', '9.198765432101E+10'):
            with self.subTest(stem=stem):
                name = stem + '.png'
                self.file(name)
                result = campaign_media.resolve(attachment('dynamic', name), 'image', {NUMBER}, 'IN')
                self.assertEqual(result[NUMBER], (None, 'Missing header attachment'))

    def test_national_names_use_the_campaign_region(self):
        self.file('07911 123456.png')
        value = attachment('dynamic', '07911 123456.png')
        number = '447911123456'
        self.assertIsNone(campaign_media.resolve(value, 'image', {number}, 'GB')[number][1])
        self.assertEqual(campaign_media.resolve(value, 'image', {number}, 'IN')[number][1], 'Missing header attachment')

    def test_wrong_type_and_empty_or_large_files_are_blocked(self):
        for name, raw, reason in [(NUMBER + '.pdf', b'%PDF-1.4', 'Wrong file type'),
                                  (NUMBER + '.png', b'', 'Header attachment is empty'),
                                  (NUMBER + '.png', b'\x89PNG\r\n\x1a\n' + b'x' * 9, 'Header attachment must be at most 16 bytes')]:
            self.file(name, raw)
            with patch('relay_core.file_limits.get_max_bytes', return_value=16):
                result = campaign_media.resolve(attachment('dynamic', name), 'image', {NUMBER}, 'IN')
            self.assertIn(reason, result[NUMBER][1])

    def test_header_file_at_the_limit_is_used(self):
        name = NUMBER + '.png'
        self.file(name, b'\x89PNG\r\n\x1a\n' + b'x' * 8)
        with patch('relay_core.file_limits.get_max_bytes', return_value=16):
            self.assertIsNone(campaign_media.resolve(attachment('dynamic', name), 'image', {NUMBER}, 'IN')[NUMBER][1])

    def test_video_and_document_use_registry_types(self):
        for kind, suffix in [('video', 'mp4'), ('document', 'pdf')]:
            name = NUMBER + '.' + suffix
            self.file(name, b'\x00\x00\x00\x18ftypmp42' if kind == 'video' else b'%PDF-1.4')
            self.assertIsNone(campaign_media.resolve(attachment('dynamic', name), kind, {NUMBER}, 'IN')[NUMBER][1])

    def test_renamed_file_content_is_rejected_before_send(self):
        self.file(NUMBER + '.png', b'%PDF-1.4')
        result = campaign_media.resolve(attachment('dynamic', NUMBER + '.png'), 'image', {NUMBER}, 'IN')
        self.assertEqual(result[NUMBER][1], 'Wrong file content for image header')

    def test_public_file_and_disguised_extension_are_rejected(self):
        self.file('offer.png', private=0)
        with self.assertRaisesRegex(ValueError, 'private'):
            campaign_media.checked_file(attachment('static', 'offer.png')['files'][0], 'image')
        self.files['/private/files/offer.png'].is_private = 1
        with self.assertRaisesRegex(ValueError, 'Wrong file type'):
            campaign_media.checked_file({'file_url': '/private/files/offer.png', 'filename': 'offer.pdf'}, 'image')

    def test_permission_denial_blocks_matching_rows(self):
        with patch.object(bulk, 'uploaded_file', side_effect=frappe.PermissionError):
            result = campaign_media.resolve(attachment('dynamic', NUMBER + '.png'), 'image', {NUMBER}, 'IN')
        self.assertEqual(result[NUMBER][1], 'Header attachment unavailable')

    def test_large_dynamic_preview_checks_each_file_only_once(self):
        numbers = {'919876' + str(n).zfill(6) for n in range(5000)}
        value = attachment('dynamic', *(number + '.png' for number in numbers))
        with patch.object(campaign_media, 'checked_file', return_value=(None, 'image/png')) as checked:
            result = campaign_media.resolve(value, 'image', numbers, 'IN')
        self.assertEqual(checked.call_count, 5000)
        self.assertEqual(len(result), 5000)
        self.assertTrue(all(problem is None for _, problem in result.values()))

    def test_mapping_rejects_zip_traversal_and_multiple_static_sources(self):
        for value in [attachment('dynamic', 'contacts.zip'), attachment('dynamic', '../escape.zip'),
                      attachment('dynamic', '..\\escape.png'), attachment('static', 'a.png', 'b.png')]:
            with self.assertRaises(ValueError):
                campaign_media.check_attachment(value, FIELDS)
        with self.assertRaises(ValueError):
            bulk_sheet.check_mapping({'phone': 'Mobile', 'fields': {}, 'fixed': {'header_media': 'https://example.com/a.jpg'},
                'header_attachment': attachment('static', 'a.png')}, ['Mobile'], FIELDS)

    def test_local_file_values_and_legacy_api_urls_build_the_right_components(self):
        mapping = bulk_sheet.check_mapping({'phone': 'Mobile', 'header_attachment': attachment('static', 'a.png')}, ['Mobile'], FIELDS)
        _, values, problem = bulk_sheet.prepare_row({'Mobile': NUMBER}, mapping, FIELDS, 'IN', attachment('static', 'a.png')['files'][0])
        self.assertIsNone(problem)
        self.assertEqual(bulk_sheet.build_components(FIELDS, values['values'], {'id': '555'})[0]['parameters'][0]['image'], {'id': '555'})
        legacy = bulk_sheet.check_mapping({'phone': 'Mobile', 'fixed': {'header_media': 'https://example.com/a.jpg'}}, ['Mobile'], FIELDS)
        _, values, problem = bulk_sheet.prepare_row({'Mobile': NUMBER}, legacy, FIELDS, 'IN')
        self.assertIsNone(problem)
        self.assertEqual(bulk_sheet.build_components(FIELDS, values['values'])[0]['parameters'][0]['image'], {'link': 'https://example.com/a.jpg'})


class HeaderSendTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = self.root / 'offer.png'; path.write_bytes(b'\x89PNG\r\n\x1a\n')
        self.file = _dict(file_name='offer.png', get_full_path=lambda: str(path))
        self.now = frappe.utils.get_datetime('2026-10-29 12:00:00')
        self.doc = _dict(name='Sheet', channel='WA', template_name='offer', language='en', arguments=json.dumps({'fields': FIELDS}),
            column_map=json.dumps({'header_attachment': attachment('static', 'offer.png')}))
        self.fake = SimpleNamespace(db=Mock(), utils=SimpleNamespace(now_datetime=lambda: self.now,
            get_datetime=frappe.utils.get_datetime, add_to_date=frappe.utils.add_to_date))
        self.enterContext(patch.object(bulk, 'frappe', self.fake))
        self.enterContext(patch.object(campaign_media, 'checked_file', return_value=(self.file, 'image/png')))
        self.enterContext(patch.object(bulk.whatsapp, 'prepare', side_effect=lambda operation, args: {'operation': operation, **args}))
        self.enterContext(patch.object(bulk, 'hub_arguments', side_effect=lambda channel, args: args))
        self.hub = Mock(execute=Mock(return_value={'id': '555'}))

    def rows(self, count=2):
        return [_dict(name='R' + str(n), destination=NUMBER, arguments=json.dumps({'values': {'header_media': attachment('static', 'offer.png')['files'][0]}})) for n in range(count)]

    def test_static_provider_upload_once_and_all_rows_send_id(self):
        rows = bulk.prepare_messages(self.hub, self.doc, {'fields': FIELDS}, self.rows())
        self.hub.execute.assert_called_once()
        self.assertEqual([row.message['components'][0]['parameters'][0]['image'] for row in rows], [{'id': '555'}] * 2)
        bulk.prepare_messages(self.hub, self.doc, {'fields': FIELDS}, self.rows())
        self.hub.execute.assert_called_once()

    def test_dynamic_upload_is_persisted_and_reused_after_retry(self):
        self.doc.column_map = json.dumps({'header_attachment': attachment('dynamic', 'offer.png')})
        rows = self.rows(1)
        bulk.prepare_messages(self.hub, self.doc, {'fields': FIELDS}, rows)
        self.assertEqual(json.loads(rows[0].arguments)['header_upload']['id'], '555')
        self.fake.db.commit.assert_called_once()
        bulk.prepare_messages(self.hub, self.doc, {'fields': FIELDS}, rows)
        self.hub.execute.assert_called_once()
        self.now = frappe.utils.add_to_date(self.now, days=30)
        bulk.prepare_messages(self.hub, self.doc, {'fields': FIELDS}, rows)
        self.assertEqual(self.hub.execute.call_count, 2)

    def test_expired_send_slice_defers_media_without_uploading(self):
        with patch.object(bulk.time, 'monotonic', return_value=20):
            self.assertEqual(bulk.prepare_messages(self.hub, self.doc, {'fields': FIELDS}, self.rows(), deadline=10), [])
        self.hub.execute.assert_not_called()

    def test_missing_file_is_never_sent(self):
        rows = self.rows(1); rows[0].arguments = json.dumps({'values': {}})
        self.assertEqual(bulk.prepare_messages(self.hub, self.doc, {'fields': FIELDS}, rows), [])
        self.hub.execute.assert_not_called()
        self.assertEqual(self.fake.db.set_value.call_args.args[2]['status'], 'Skipped')

    def test_deduplicated_file_urls_keep_each_rows_document_name(self):
        first = {'file_url': '/private/files/shared.pdf', 'filename': NUMBER + '.pdf'}
        second = {**first, 'filename': '919876543211.pdf'}
        fields = bulk_sheet.template_fields({'components': [{'type': 'HEADER', 'format': 'DOCUMENT'}]})
        self.doc.arguments = json.dumps({'fields': fields})
        self.doc.column_map = json.dumps({'header_attachment': {'mode': 'dynamic', 'files': [first, second]}})
        rows = [_dict(name='R' + str(i), destination=NUMBER, arguments=json.dumps({'values': {'header_media': item}}))
                for i, item in enumerate([first, second])]
        result = bulk.prepare_messages(self.hub, self.doc, {'fields': fields}, rows)
        self.assertEqual([row.message['components'][0]['parameters'][0]['document']['filename'] for row in result],
                         [first['filename'], second['filename']])

    def test_provider_failure_never_produces_a_message(self):
        self.hub.execute.side_effect = bulk.whatsapp.HubError('unavailable')
        rows = self.rows(1)
        with self.assertRaises(bulk.whatsapp.HubError):
            bulk.prepare_messages(self.hub, self.doc, {'fields': FIELDS}, rows)
        self.assertIsNone(rows[0].message)

    def test_test_mode_blocks_header_upload_before_network(self):
        from relay_core import test_mode
        from relay_core.hub import HubClient
        hub = HubClient('https://hub.example/mcp', 'x' * 64)
        def throw(message, exception):
            raise exception(message)
        with patch.object(test_mode, 'is_enabled', return_value=True), patch.object(frappe, 'throw', throw), \
                patch.object(hub.opener, 'open') as opened:
            with self.assertRaises(test_mode.TestModeBlocked):
                bulk.upload_media_file(hub, 'WA', self.file, 'image/png', 'image')
        opened.assert_not_called()

    def test_invalid_provider_id_is_rejected(self):
        self.hub.execute.return_value = {'id': 'not-an-id'}
        with self.assertRaises(bulk.whatsapp.HubError):
            bulk.prepare_messages(self.hub, self.doc, {'fields': FIELDS}, self.rows(1))
