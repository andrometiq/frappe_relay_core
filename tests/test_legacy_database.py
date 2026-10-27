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

    def __init__(self, dry_run=False, files_dir=None, database='sales_source'):
        self.site_label, self.batch, self.dry_run = 'sales.example', 100, dry_run
        self.source = Mock(database=database, sql=Mock(return_value=[]))
        self.files_dir = Path(files_dir) if files_dir else None
        self.counts, self.failures, self.phones = Counter(), [], {}
        self.committed_counts, self.phone_changes, self.copied = Counter(), [], set()


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

    def test_shared_phone_prefers_relay_then_customer_contact_then_oldest(self):
        def contact(name, creation, relay=None, customer=0):
            return frappe._dict(name=name, creation=creation, phone='+91 90000 00001', mobile_no=None, contact_phone=None,
                                relay=relay, customer=customer)
        oldest, customer = contact('Old', '2026-01-01'), contact('Shop', '2026-02-01', customer=1)
        with patch.object(legacy_database.frappe.db, 'sql', return_value=[oldest, customer]):
            self.assertEqual(legacy_database.contacts_by_phone(), {'919000000001': 'Shop'})
        with patch.object(legacy_database.frappe.db, 'sql', return_value=[oldest, customer, contact('Chat', '2026-03-01', relay='RELAY-CON-1')]):
            self.assertEqual(legacy_database.contacts_by_phone(), {'919000000001': 'Chat'})
        with patch.object(legacy_database.frappe.db, 'sql', return_value=[contact('New', '2026-02-01'), oldest]):
            self.assertEqual(legacy_database.contacts_by_phone(), {'919000000001': 'Old'})

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
        values = Importer(dry_run=True).message(failed, job, manifest, [])
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

    def run_rows(self, rows, existing, live=(), files=()):
        importer = Importer()
        importer.source.sql.return_value = list(files)
        inserted = []
        with patch.object(legacy_database.frappe, 'get_all', side_effect=[existing, list(live)]), \
             patch.object(legacy_database, 'sequential_name', side_effect=lambda kind: 'RELAY-MSG-' + str(len(inserted))), \
             patch.object(legacy_database.legacy, 'insert_rows', side_effect=lambda doctype, records: inserted.extend(records)), \
             patch.object(importer, 'source_file', return_value=Path('/x/a.jpg')), \
             patch.object(importer, 'copy', return_value={'attachment': 'FILE-1', 'availability': 'available'}) as copy, \
             patch.object(legacy_database.frappe.db, 'set_value') as set_value:
            importer.import_rows(rows, self.job, self.manifest)
        return importer, inserted, set_value, copy

    def imported(self, source, **values):
        data = dict(name='RELAY-MSG-9', source_key=legacy.source_key('sales.example', source.name), relay_contact='RELAY-CON-1',
                    channel='RELAY-CH-1', legacy_checksum=legacy_bundle.checksum(source), message_data='{}',
                    legacy_data=json.dumps({'row': {'modified': str(source.modified)}}))
        return frappe._dict(data, **values)

    def test_rerun_skips_imported_and_inserts_only_new(self):
        old, new = row('m1'), row('m2')
        importer, inserted, set_value, _ = self.run_rows([old, new], [self.imported(old)])
        self.assertEqual([record['legacy_source'] for record in inserted], ['m2'])
        self.assertEqual((importer.counts['skipped'], importer.counts['created']), (1, 1))
        set_value.assert_not_called()

    def test_changed_source_row_refreshes_status_and_content(self):
        before = row('m1', direction='Outbound', delivery_status='Delivered')
        after = row('m1', direction='Outbound', delivery_status='Read', body='Edited', modified='2026-09-02 10:00:00')
        importer, inserted, set_value, _ = self.run_rows([after], [self.imported(before)])
        self.assertEqual(inserted, [])
        self.assertEqual(importer.counts['updated'], 1)
        self.assertEqual((set_value.call_args.args[2]['status'], set_value.call_args.args[2]['content']), ('Read', 'Edited'))
        self.assertEqual(set(set_value.call_args.args[2]), set(legacy_database.REFRESHED))

    def test_older_source_row_never_replaces_newer_history(self):
        newer = row('m1', delivery_status='Read', modified='2026-09-03 10:00:00')
        importer, _, set_value, _ = self.run_rows([row('m1')], [self.imported(newer)])
        set_value.assert_not_called()
        self.assertEqual(importer.counts['stale_skipped'], 1)

    def test_imported_message_of_another_conversation_is_a_failure(self):
        old = row('m1', modified='2026-09-02 10:00:00')
        importer, _, set_value, _ = self.run_rows([old], [self.imported(row('m1'), relay_contact='RELAY-CON-2')])
        set_value.assert_not_called()
        self.assertIn('belongs to another conversation', importer.failures[0]['error'])

    def test_rerun_repairs_missing_media(self):
        image = row('m1', message_type='image')
        file = frappe._dict(attached_to_name='m1', file_url='/private/files/a.jpg')
        importer, _, set_value, copy = self.run_rows([image], [self.imported(image)], files=[file])
        copy.assert_called_once()
        self.assertEqual(json.loads(set_value.call_args.args[2]['message_data'])['attachment'], 'FILE-1')
        self.assertEqual(importer.counts['updated'], 1)

    def test_live_copy_is_dropped_before_its_files_are_copied(self):
        image = row('m1', message_type='image')
        file = frappe._dict(attached_to_name='m1', file_url='/private/files/a.jpg')
        live = [legacy_database.provider_key('RELAY-CH-1', '919000000001', 'wamid.m1')]
        importer, inserted, _, copy = self.run_rows([image], [], live=live, files=[file])
        copy.assert_not_called()
        self.assertEqual((inserted, importer.failures[0]['error']), ([], 'Provider message already in Relay (live copy kept)'))


class Media(Case):
    def attachments(self, files, payload_url=None, names=None):
        with tempfile.TemporaryDirectory() as directory:
            for name in names or ('a.jpg',):
                (Path(directory) / name).write_bytes(b'image')
            importer = Importer(files_dir=directory)
            content = json.dumps({'payload': {'local_file_url': payload_url}}) if payload_url else '{}'
            copied = lambda stream, metadata, message: {'attachment': 'copy-' + metadata['sha256'][:6], 'availability': 'available'}
            with patch.object(legacy_database, 'attach', side_effect=copied):
                result = importer.attachments(row(message_type='image', content=content), files, 'RELAY-MSG-1', {'kind': 'text', 'text': 'x'})
        return importer, result

    def test_every_source_file_is_copied_and_a_missing_one_is_a_failure(self):
        files = [frappe._dict(file_url='/private/files/a.jpg'), frappe._dict(file_url='/private/files/gone.jpg')]
        importer, result = self.attachments(files, payload_url='/private/files/other.jpg')
        self.assertEqual((importer.counts['media_copied'], importer.counts['media_failed']), (1, 1))
        self.assertEqual(importer.failures, [{'message': 'm1', 'error': 'Media file not found: /private/files/gone.jpg'}])
        self.assertEqual([item['availability'] for item in result['legacy_attachments']], ['available', 'missing'])
        self.assertEqual((result['attachment'], result['kind']), (result['legacy_attachments'][0]['attachment'], 'document'))

    def test_payload_url_is_used_only_without_file_rows(self):
        importer, result = self.attachments([], payload_url='/private/files/a.jpg')
        self.assertEqual(importer.counts['media_copied'], 1)
        importer, result = self.attachments([], payload_url=None)
        self.assertEqual((result, importer.counts['media_copied']), ({}, 0))

    def test_same_bytes_in_several_file_rows_give_one_attachment(self):
        files = [frappe._dict(file_url='/private/files/a.jpg'), frappe._dict(file_url='/private/files/b.jpg')]
        importer, result = self.attachments(files, names=('a.jpg', 'b.jpg'))
        self.assertEqual((importer.counts['media_copied'], len(result['legacy_attachments'])), (1, 1))

    def test_dry_run_checks_files_without_copying(self):
        importer = Importer(dry_run=True, files_dir=tempfile.gettempdir())
        with patch.object(legacy_database, 'attach') as attach:
            result = importer.attachments(row(), [frappe._dict(file_url='/private/files/relay-missing-x.jpg')], 'dry-run', {'kind': 'image'})
        attach.assert_not_called()
        self.assertEqual((importer.counts['media_failed'], result['legacy_attachments'][0]['availability']), (1, 'missing'))

    def test_same_site_import_copies_a_file_found_at_its_own_url(self):
        with tempfile.TemporaryDirectory() as site:
            (Path(site) / 'public' / 'files').mkdir(parents=True)
            (Path(site) / 'public' / 'files' / 'receipt.pdf').write_bytes(b'pdf')
            site_path = lambda *parts: str(Path(site, *parts))
            with patch.object(legacy_database.frappe, 'get_site_path', side_effect=site_path):
                self.assertEqual(Importer(database=None).source_file('/files/receipt.pdf'), Path(site, 'public', 'files', 'receipt.pdf'))
                self.assertIsNone(Importer(database=None).source_file('/files/missing.pdf'))
                self.assertIsNone(Importer().source_file('/files/receipt.pdf'))


class Undo(Case):
    def test_removed_conversation_loses_its_team_assignment_and_inbox_state(self):
        frappe.db.exists.return_value = False
        removed = Counter()
        legacy_database.remove_created({'relay_contact': 'RELAY-CON-1', 'endpoint': 'RELAY-EP-1'}, removed)
        frappe.db.delete.assert_any_call('Relay Conversation Assignment', {'relay_contact': 'RELAY-CON-1'})
        frappe.db.delete.assert_any_call('Relay Conversation State', {'relay_contact': 'RELAY-CON-1'})
        self.assertEqual(removed, Counter({'Relay Contact Endpoint': 1, 'Relay Contact': 1}))

    def test_conversation_with_live_messages_is_kept_whole(self):
        frappe.db.exists.return_value = True
        removed = Counter()
        legacy_database.remove_created({'relay_contact': 'RELAY-CON-1', 'endpoint': 'RELAY-EP-1'}, removed)
        frappe.db.delete.assert_not_called()
        self.assertEqual(removed, Counter({'contacts_kept_with_new_messages': 1}))

    def test_copied_media_is_deleted_unless_another_file_row_uses_it(self):
        with tempfile.TemporaryDirectory() as site:
            files = Path(site, 'private', 'files')
            files.mkdir(parents=True)
            for name in ('relay-archive-a', 'relay-archive-b', 'source.jpg'):
                (files / name).write_bytes(b'x')
            urls = {'/private/files/relay-archive-a', '/private/files/relay-archive-b', '/private/files/source.jpg', None}
            with patch.object(legacy_database.frappe, 'get_site_path', side_effect=lambda *parts: str(Path(site, *parts))), \
                 patch.object(frappe, 'get_all', return_value=['/private/files/relay-archive-b']):
                self.assertEqual(legacy_database.remove_unused_copies(urls), 1)
            self.assertEqual(sorted(path.name for path in files.iterdir()), ['relay-archive-b', 'source.jpg'])


class Transactions(Case):
    def test_rollback_forgets_counts_phone_matches_and_copied_bytes(self):
        importer = Importer()
        importer.counts['created'] = 5
        importer.phones = {'919000000001': 'Old'}
        importer.commit()
        importer.counts['created'] += 3
        importer.phone_changes = [('919000000001', 'Old'), ('919000000002', None)]
        importer.phones.update({'919000000001': 'Rolled', '919000000002': 'Rolled'})
        importer.copied = {'/private/files/relay-archive-x'}
        with patch.object(legacy_database, 'remove_unused_copies') as remove:
            importer.rollback()
        frappe.db.rollback.assert_called_once()
        remove.assert_called_once_with({'/private/files/relay-archive-x'})
        self.assertEqual(importer.counts['created'], 5)
        self.assertEqual(importer.phones, {'919000000001': 'Old'})
        self.assertEqual((importer.phone_changes, importer.copied), ([], set()))

    def test_failed_conversation_is_rolled_back_and_listed(self):
        importer = Importer()
        importer.source = Mock(sql=Mock(return_value=[conversation(name='c1'), conversation(name='c2')]))
        with patch.object(importer, 'import_conversation', side_effect=[None, RuntimeError('boom')]), \
             patch.object(importer, 'commit'), patch.object(importer, 'rollback') as rollback:
            result = importer.run()
        rollback.assert_called_once()
        self.assertEqual(result['failures'], [{'conversation': 'c2', 'error': 'RuntimeError: boom'}])

    def test_long_conversation_commits_once_per_batch(self):
        importer = Importer()
        pages = [[row('m1'), row('m2')], [row('m3')], []]
        def import_rows(rows, job, manifest):
            importer.counts['created'] += len(rows)
        with patch.object(importer, 'page', side_effect=pages), \
             patch.object(importer, 'channels', {'old': 'RELAY-CH-1'}, create=True), \
             patch.object(importer, 'contact_for', return_value='RELAY-CON-1'), \
             patch.object(importer, 'mark', return_value='IMPORT-1'), \
             patch.object(importer, 'import_rows', side_effect=import_rows), \
             patch.object(importer, 'commit') as commit, \
             patch.object(legacy_database, 'refresh_activity'), patch.object(legacy_database, 'apply_history'), \
             patch('relay_core.identity.default_region', return_value='IN'):
            importer.import_conversation(conversation())
        self.assertEqual(commit.call_count, 2)
        added = [call.args[1][0] for call in frappe.db.sql.call_args_list if 'imported = imported' in call.args[0]]
        self.assertEqual(added, [2, 1])


class Command(unittest.TestCase):
    def test_exit_status_is_one_when_anything_failed(self):
        from click.testing import CliRunner
        from relay_core.commands import relay_import_whatsapp_core
        frappe.local.flags = frappe._dict()
        self.addCleanup(lambda: delattr(frappe.local, 'flags'))
        for failures, code in (([], 0), ([{'message': 'm1', 'error': 'x'}], 1)):
            importer = Mock(return_value=Mock(run=Mock(return_value={'counts': {}, 'failures': failures})))
            with patch.object(frappe, 'init'), patch.object(frappe, 'connect'), patch.object(frappe, 'set_user'), \
                 patch.object(frappe, 'destroy'), patch.object(legacy_database, 'Source'), \
                 patch.object(legacy_database, 'Importer', importer), \
                 patch.object(frappe.utils, 'now_datetime', return_value=__import__('datetime').datetime(2026, 1, 1)):
                result = CliRunner().invoke(relay_import_whatsapp_core, ['--source-site-label', 'sales.example'],
                                            obj=frappe._dict(sites=['site.test']))
            self.assertEqual(result.exit_code, code, (result.output, result.exception))


class TeamAssignment(Case):
    def test_only_unassigned_imported_conversations_get_the_team(self):
        lists = {'Relay Legacy Import': ['RELAY-CON-1', 'RELAY-CON-2', 'RELAY-CON-1'],
                 'Relay Conversation Assignment': ['RELAY-CON-2']}
        inserted = []
        def get_doc(*args):
            if isinstance(args[0], dict):
                return Mock(insert=lambda: inserted.append(args[0]))
            return Mock()
        with patch.object(frappe, 'get_all', side_effect=lambda doctype, **kwargs: lists[doctype]), \
             patch.object(frappe, 'get_doc', side_effect=get_doc) as get, \
             patch('relay_core.queue_counts.invalidate') as invalidate:
            result = legacy_database.assign_team('sales.example', 'Sales-001')
        get.assert_any_call('Relay Team', 'Sales-001')
        self.assertEqual(result, {'assigned': 1, 'already_assigned': 1})
        self.assertEqual(inserted, [{'doctype': 'Relay Conversation Assignment', 'relay_contact': 'RELAY-CON-1', 'team': 'Sales-001'}])
        invalidate.assert_called_once()

if __name__ == '__main__':
    unittest.main()
