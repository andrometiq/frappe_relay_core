import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import Mock, patch

import frappe
from relay_core import legacy, legacy_bundle, legacy_database


def conversation(**values):
    return frappe._dict(dict(name='c1', channel='old', normalized_value='919000000001', identifier_type='Phone',
                             display_value='Pat', identity='i1', phone_alias=None), **values)


def row(name='m1', **values):
    return frappe._dict(dict(name=name, creation='2026-09-01 10:00:00', modified='2026-09-01 10:00:00', channel='old',
        conversation='c1', message_type='text', content='{}', body='Hello', direction='Inbound', delivery_status='Received',
        owner='old@example.invalid', provider_message_id='wamid.' + name, provider_timestamp='2026-09-01 10:00:00', failure=None), **values)


class Importer(legacy_database.Importer):
    """The importer without a database: no channel lookup, no contact lookup."""

    def __init__(self, dry_run=False, files_dir=None):
        self.site_label, self.batch, self.dry_run = 'sales.example', 100, dry_run
        self.files_dir = Path(files_dir) if files_dir else None
        self.counts, self.failures, self.phones = Counter(), [], {}


class Case(unittest.TestCase):
    """No site: fixed time zone, a mock database and a session user."""

    def setUp(self):
        self.enterContext(patch.object(legacy.frappe.utils, 'get_system_timezone', return_value='Asia/Kolkata'))
        self.enterContext(patch('frappe.utils.data.get_system_timezone', return_value='Asia/Kolkata'))
        frappe.local.session = frappe._dict(user='importer')
        frappe.local.db = Mock()
        self.addCleanup(lambda: (delattr(frappe.local, 'session'), delattr(frappe.local, 'db')))


class Mapping(Case):
    def setUp(self):
        super().setUp()
        self.enterContext(patch('relay_core.identity.default_region', return_value='IN'))

    def test_phone_identity_uses_e164_digits(self):
        self.assertEqual(legacy_database.legacy_endpoint(conversation(normalized_value='+91 90000 00001')), ('919000000001', True))

    def test_business_scoped_id_uses_its_phone_alias(self):
        value = conversation(normalized_value='IN.1109766564966551', identifier_type='BSUID', phone_alias='919598306735')
        self.assertEqual(legacy_database.legacy_endpoint(value), ('919598306735', True))

    def test_business_scoped_id_without_phone_stays_opaque(self):
        value = conversation(normalized_value='IN.1109766564966551', identifier_type='BSUID')
        self.assertEqual(legacy_database.legacy_endpoint(value), ('IN.1109766564966551', False))

    def test_channel_matches_by_number_only_when_unique(self):
        source = frappe._dict(phone_number_id='979157361944731', display_name='421 224 2924')
        channels = [frappe._dict(name='A', hub_channel='979157361944731', address=None), frappe._dict(name='B', hub_channel='x', address='+91 99999')]
        with patch.object(legacy_database.frappe, 'get_all', return_value=channels):
            self.assertEqual(legacy_database.matching_channel(source), 'A')
        with patch.object(legacy_database.frappe, 'get_all', return_value=[*channels, frappe._dict(name='C', hub_channel='979157361944731', address=None)]):
            self.assertIsNone(legacy_database.matching_channel(source))

    def test_message_keeps_time_direction_status_and_has_no_triage(self):
        job = frappe._dict(channel='RELAY-CH-1', relay_contact='RELAY-CON-1')
        manifest = {'source_site': 'sales.example', 'endpoint': '919000000001', 'identifier_type': 'Phone'}
        failed = row(direction='Outbound', delivery_status='Failed', failure=json.dumps({'message': 'Re-engagement'}))
        values = Importer(dry_run=True).message(failed, job, manifest)
        self.assertEqual((values['direction'], values['status'], values['legacy_triage']), ('Outgoing', 'Failed', 0))
        self.assertEqual(values['delivery_error'], 'Re-engagement')
        self.assertEqual(str(values['sent_at']), '2026-09-01 10:00:00')
        self.assertEqual(values['source_key'], legacy.source_key('sales.example', 'm1'))
        self.assertEqual(values['legacy_source'], 'm1')
        self.assertIsNone(values['business_name'])

    def test_unknown_status_is_listed_not_raised(self):
        importer = Importer(dry_run=True)
        job = frappe._dict(channel='RELAY-CH-1', relay_contact='RELAY-CON-1')
        with patch.object(legacy_database.frappe, 'get_all', return_value=[]):
            importer.import_rows([row(delivery_status='Bogus')], job, {'source_site': 'sales.example', 'endpoint': '1', 'identifier_type': 'Phone'})
        self.assertEqual(importer.failures[0]['message'], 'm1')
        self.assertEqual(importer.counts['created'], 0)


class Idempotency(Case):
    def setUp(self):
        super().setUp()
        self.job = frappe._dict(channel='RELAY-CH-1', relay_contact='RELAY-CON-1')
        self.manifest = {'source_site': 'sales.example', 'endpoint': '919000000001', 'identifier_type': 'Phone'}

    def run_rows(self, rows, existing):
        importer = Importer()
        inserted = []
        with patch.object(legacy_database.frappe, 'get_all', side_effect=[existing, []]), \
             patch.object(legacy_database, 'sequential_name', side_effect=lambda kind: 'RELAY-MSG-' + str(len(inserted))), \
             patch.object(legacy_database.legacy, 'insert_rows', side_effect=lambda doctype, records: inserted.extend(records)), \
             patch.object(legacy_database.frappe.db, 'set_value') as set_value:
            importer.import_rows(rows, self.job, self.manifest)
        return importer, inserted, set_value

    def test_rerun_skips_imported_and_inserts_only_new(self):
        old, new = row('m1'), row('m2')
        existing = [frappe._dict(name='RELAY-MSG-9', source_key=legacy.source_key('sales.example', 'm1'), legacy_checksum=legacy_bundle.checksum(old))]
        importer, inserted, set_value = self.run_rows([old, new], existing)
        self.assertEqual([record['legacy_source'] for record in inserted], ['m2'])
        self.assertEqual((importer.counts['skipped'], importer.counts['created']), (1, 1))
        set_value.assert_not_called()

    def test_changed_source_row_updates_status_only(self):
        before = row('m1', direction='Outbound', delivery_status='Delivered')
        after = row('m1', direction='Outbound', delivery_status='Read', modified='2026-09-02 10:00:00')
        existing = [frappe._dict(name='RELAY-MSG-9', source_key=legacy.source_key('sales.example', 'm1'), legacy_checksum=legacy_bundle.checksum(before))]
        importer, inserted, set_value = self.run_rows([after], existing)
        self.assertEqual(inserted, [])
        self.assertEqual(importer.counts['updated'], 1)
        self.assertEqual(set_value.call_args.args[2]['status'], 'Read')


class Media(Case):
    def test_file_in_files_dir_is_copied_else_url_is_linked(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'a.jpg').write_bytes(b'image')
            importer = Importer(files_dir=directory)
            with patch.object(legacy_database, 'attach', return_value={'attachment': 'copied', 'availability': 'available'}) as attach, \
                 patch.object(legacy_database, 'link_file', return_value={'attachment': 'linked', 'availability': 'linked'}):
                self.assertEqual(importer.attachment('/private/files/a.jpg', 'RELAY-MSG-1')['attachment'], 'copied')
                self.assertEqual(importer.attachment('/private/files/b.jpg', 'RELAY-MSG-2')['attachment'], 'linked')
            self.assertEqual(attach.call_args.args[1]['size'], 5)
            self.assertEqual((importer.counts['media_copied'], importer.counts['media_linked']), (1, 1))


if __name__ == '__main__':
    unittest.main()
