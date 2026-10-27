import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import Mock, patch

import frappe
from relay_core import legacy, legacy_bundle, legacy_database, legacy_undo


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
        self.counts, self.failures, self.phones, self.links, self.bindings = Counter(), [], {}, {}, {}
        self.committed_counts, self.unresolved, self.pending_unresolved, self.copied = Counter(), [], [], set()


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
            self.assertEqual(legacy_database.contacts_by_phone(), {'919000000001': ['Shop', 'Old']})
        with patch.object(legacy_database.frappe.db, 'sql', return_value=[oldest, customer, contact('Chat', '2026-03-01', relay='RELAY-CON-1')]):
            self.assertEqual(legacy_database.contacts_by_phone(), {'919000000001': ['Chat', 'Shop', 'Old']})
        with patch.object(legacy_database.frappe.db, 'sql', return_value=[contact('New', '2026-02-01'), oldest]):
            self.assertEqual(legacy_database.contacts_by_phone(), {'919000000001': ['Old', 'New']})

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


class Identity(Case):
    def test_shared_phone_prefers_the_contact_of_the_bound_customer(self):
        importer = Importer()
        importer.phones = {'919000000001': ['Chat', 'Shop', 'Old']}
        importer.links = {'Shop': {'Other Customer'}, 'Old': {'Bound Customer'}}
        self.assertEqual(importer.phone_contact('919000000001', {'Bound Customer'}), 'Old')
        self.assertEqual(importer.phone_contact('919000000001', set()), 'Chat')
        self.assertIsNone(importer.phone_contact('919000000009', set()))

    def test_missing_customer_link_is_added_and_recorded_for_undo(self):
        importer = Importer()
        importer.links = {'Old': {'Have'}}
        frappe.db.sql.return_value = [[2]]
        created = {}
        with patch.object(legacy_database, 'direct_document', return_value=frappe._dict(name='LINK-1')) as document, \
             patch.object(frappe, 'generate_hash', return_value='hash'):
            importer.link_customers('Old', {'Have', 'Bound'}, created)
        values = document.call_args.args[1]
        self.assertEqual((values['parent'], values['link_doctype'], values['link_name'], values['idx']), ('Old', 'Customer', 'Bound', 2))
        self.assertEqual((created, importer.links['Old'], importer.counts['customer_links_added']), ({'links': ['LINK-1']}, {'Have', 'Bound'}, 1))

    def test_bound_customers_come_from_verified_bindings_and_must_exist(self):
        importer = Importer()
        importer.bindings = None
        importer.source.sql.return_value = [frappe._dict(identity='i1', attributes=json.dumps({'erpnext_customer': 'Shop'})),
                                            frappe._dict(identity='i1', attributes=json.dumps({'erpnext_customer': 'Gone'})),
                                            frappe._dict(identity='i1', attributes=json.dumps({'erpnext_customer': ''}))]
        with patch.object(frappe, 'get_all', return_value=['Shop']):
            self.assertEqual(importer.bound_customers(conversation()), {'Shop'})
        self.assertEqual(importer.pending_unresolved, [{'conversation': 'c1', 'reason': 'Bound Customer not on this site', 'customer': 'Gone'}])

    def test_ambiguous_phone_without_binding_is_reported(self):
        importer = Importer()
        importer.phones = {'919000000001': ['A', 'B'], '919000000002': ['C']}
        importer.check_identity(conversation(), '919000000001', True, {'Shop'})
        importer.check_identity(conversation(name='c2'), '919000000002', True, set())
        importer.check_identity(conversation(name='c3'), '919000000001', True, set())
        self.assertEqual((importer.counts['customer_bound_conversations'], importer.counts['ambiguous_resolved_by_binding'],
                          importer.counts['identity_unresolved']), (1, 1, 1))
        self.assertEqual(importer.pending_unresolved[0]['conversation'], 'c3')
        self.assertEqual(importer.pending_unresolved[0]['candidates'], ['A', 'B'])

    def test_rerun_adds_new_undo_entries_to_the_marker(self):
        self.assertEqual(legacy_database.merge_created({'endpoint': 'E1', 'links': ['L1']}, {'endpoint': 'E2', 'links': ['L1', 'L2']}),
                         {'endpoint': 'E1', 'links': ['L1', 'L2']})


class Finish(Case):
    def test_resumed_run_records_no_earlier_values_for_what_the_interrupted_run_created(self):
        importer = Importer()
        frappe.db.get_value.return_value = json.dumps({'created': {'relay_contact': 'RELAY-CON-1', 'endpoint': 'EP-1'}})
        job = frappe._dict(channel='CH', relay_contact='RELAY-CON-1', marker='IMPORT-1')
        created = {}
        with patch.object(importer, 'project_reactions'), patch.object(importer, 'mark'), \
             patch.object(legacy_database, 'refresh_activity'), patch.object(legacy_database, 'apply_history'):
            importer.finish(conversation(), '9190', job, created)
        self.assertEqual(created, {})


class Reactions(Case):
    def test_reactions_are_projected_and_live_targets_saved_for_undo(self):
        importer = Importer()
        job = frappe._dict(channel='RELAY-CH-1', relay_contact='RELAY-CON-1')
        reactions = [frappe._dict(message_data=json.dumps({'reaction': {'message_id': 'wamid.t', 'emoji': 'x'}}), sender_endpoint='9190')]
        live = [frappe._dict(name='RELAY-MSG-LIVE', reactions='{"a": 1}', message_updates='{}')]
        def project(job, report):
            report['mismatches'].append({'source': 'RELAY-MSG-2', 'detail': 'Reaction target unavailable'})
        created = {'reactions': {'RELAY-MSG-LIVE': {'reactions': 'first', 'message_updates': None}}}
        with patch.object(frappe, 'get_all', side_effect=[reactions * 2, live]) as get_all, \
             patch.object(legacy_database, 'project_reactions', side_effect=project) as projected:
            importer.project_reactions(job, created)
        projected.assert_called_once()
        target_filter = get_all.call_args_list[1].kwargs['filters']['provider_message_key'][1]
        self.assertEqual(target_filter, [legacy_database.provider_key('RELAY-CH-1', '9190', 'wamid.t')] * 2)
        self.assertEqual(created['reactions']['RELAY-MSG-LIVE']['reactions'], 'first')
        self.assertEqual(importer.counts['reactions_projected'], 1)
        self.assertEqual(importer.failures, [{'message': 'RELAY-MSG-2', 'error': 'Reaction target unavailable'}])


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
    def setUp(self):
        super().setUp()
        self.live = []
        self.rows = {('Relay Contact Endpoint', 'EP-1'): frappe._dict(relay_contact='RELAY-CON-1', channel='CH', endpoint='9190'),
                     ('Relay Conversation Assignment', 'ASG-1'): '2026-10-01'}
        frappe.db.exists.side_effect = lambda doctype, filters=None: self.exists(doctype, filters)
        frappe.db.get_value.side_effect = lambda doctype, name, *args, **kwargs: self.rows.get((doctype, name))

    def exists(self, doctype, filters):
        if doctype == 'Relay Message' and not isinstance(filters, dict):
            return True
        if doctype == 'Relay Message':
            return any(all(filters.get(key, value) == value for key, value in message.items() if key != 'creation')
                       for message in self.live if filters.get('creation') is None or message['creation'] > filters['creation'][1])
        return doctype == 'Relay Contact'

    def revert(self, created):
        removed = Counter()
        with patch('relay_core.legacy_undo.refresh_activity') as refresh:
            legacy_undo.revert('RELAY-CON-1', created, removed)
        return removed, refresh

    def test_changes_on_a_reused_contact_are_reversed_exactly(self):
        self.rows[('Relay Contact Endpoint', 'EP-OLD')] = frappe._dict(marketing_opt_out=1, opt_out_changed_at='2026-09-01', modified='m2')
        created = {'endpoint': 'EP-1', 'links': ['LINK-1'], 'assignment': 'ASG-1',
                   'activity': {'last_message_at': None, 'last_message': None},
                   'opt_out': {'EP-OLD': {'before': {'marketing_opt_out': 0, 'opt_out_changed_at': None, 'modified': 'm1'},
                                          'after': {'marketing_opt_out': 1, 'opt_out_changed_at': '2026-09-01', 'modified': 'm2'}}},
                   'reactions': {'RELAY-MSG-LIVE': {'reactions': '{}', 'message_updates': None}}}
        removed, _ = self.revert(created)
        for call in (('Dynamic Link', 'LINK-1'), ('Relay Conversation Assignment', 'ASG-1'), ('Relay Contact Endpoint', 'EP-1')):
            frappe.db.delete.assert_any_call(*call)
        frappe.db.set_value.assert_any_call('Relay Contact Endpoint', 'EP-OLD', created['opt_out']['EP-OLD']['before'], update_modified=False)
        frappe.db.set_value.assert_any_call('Relay Message', 'RELAY-MSG-LIVE', {'reactions': '{}', 'message_updates': None}, update_modified=False)
        frappe.db.set_value.assert_any_call('Relay Contact', 'RELAY-CON-1', {'last_message_at': None, 'last_message': None}, update_modified=False)
        self.assertNotIn(('Relay Contact', 'RELAY-CON-1'), [call.args for call in frappe.db.delete.call_args_list])
        self.assertEqual(removed['opt_out_restored'], 1)

    def test_endpoint_and_assignment_that_live_messages_use_are_kept(self):
        self.live.append(frappe._dict(relay_contact='RELAY-CON-1', channel='CH', sender_endpoint='9190', creation='2026-10-02'))
        removed, refresh = self.revert({'endpoint': 'EP-1', 'assignment': 'ASG-1', 'activity': {}})
        frappe.db.delete.assert_not_called()
        refresh.assert_called_once_with('RELAY-CON-1')
        self.assertEqual(removed['endpoints_kept_with_new_messages'], 1)

    def test_assignment_older_than_the_live_messages_is_removed(self):
        self.live.append(frappe._dict(relay_contact='RELAY-CON-1', channel='CH', sender_endpoint='other', creation='2026-09-01'))
        self.revert({'assignment': 'ASG-1'})
        frappe.db.delete.assert_called_once_with('Relay Conversation Assignment', 'ASG-1')

    def test_created_conversation_is_removed_whole(self):
        frappe.db.exists.side_effect = lambda doctype, filters=None: False
        removed, _ = self.revert({'relay_contact': 'RELAY-CON-1', 'endpoint': 'EP-1', 'contact': 'Pat'})
        for call in (('Relay Contact', 'RELAY-CON-1'), ('Relay Conversation Assignment', {'relay_contact': 'RELAY-CON-1'}),
                     ('Relay Conversation State', {'relay_contact': 'RELAY-CON-1'}), ('Contact', 'Pat'),
                     ('Dynamic Link', {'parenttype': 'Contact', 'parent': 'Pat'})):
            frappe.db.delete.assert_any_call(*call)
        self.assertEqual(removed, Counter({'Relay Contact Endpoint': 1, 'Relay Contact': 1, 'Contact': 1}))

    def test_created_conversation_with_live_messages_is_kept(self):
        self.live.append(frappe._dict(relay_contact='RELAY-CON-1', channel='CH', sender_endpoint='9190', creation='2026-10-02'))
        removed, _ = self.revert({'relay_contact': 'RELAY-CON-1', 'endpoint': 'EP-1', 'contact': 'Pat'})
        frappe.db.delete.assert_not_called()
        self.assertEqual(removed['contacts_kept_with_new_messages'], 1)

    def test_step_that_hits_a_lock_timeout_is_rolled_back_and_run_again(self):
        removed = Counter(messages=5)
        def work():
            removed['messages'] += 1
            if frappe.db.rollback.call_count == 0:
                raise frappe.QueryTimeoutError('1205')
            return 'done'
        with patch.object(legacy_undo.time, 'sleep'):
            self.assertEqual(legacy_undo.transaction(work, removed), 'done')
        self.assertEqual((frappe.db.rollback.call_count, removed['messages']), (1, 6))

    def test_undo_commits_each_message_chunk_and_each_marker(self):
        frappe.db.sql_list.side_effect = [['M1', 'M2'], ['M3'], []]
        markers = [frappe._dict(name='IMPORT-2', relay_contact='C2', source_metadata='{}'),
                   frappe._dict(name='IMPORT-1', relay_contact='C1', source_metadata='{}')]
        with patch.object(frappe, 'get_all', side_effect=lambda doctype, **kwargs: markers if doctype == 'Relay Legacy Import' else []) as get_all, \
             patch.object(legacy_undo, 'revert') as revert, patch.object(legacy_undo, 'remove_unused_copies', return_value=0), \
             patch('relay_core.queue_counts.invalidate'):
            result = legacy_undo.undo('sales.example', chunk=2)
        self.assertEqual(result['messages'], 3)
        frappe.db.delete.assert_any_call('Relay Message Read', {'message': ['in', ['M1', 'M2']]})
        self.assertEqual(frappe.db.commit.call_count, 5)
        self.assertEqual([call.args[0] for call in revert.call_args_list], ['C2', 'C1'])
        self.assertEqual([call.kwargs.get('order_by') for call in get_all.call_args_list if call.args[0] == 'Relay Legacy Import'], ['name desc'])

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
    def test_rollback_forgets_counts_contact_matches_report_rows_and_copied_bytes(self):
        importer = Importer()
        importer.counts['created'] = 5
        importer.pending_unresolved = [{'conversation': 'c1'}]
        importer.commit()
        importer.counts['created'] += 3
        importer.pending_unresolved = [{'conversation': 'c2'}]
        importer.phones, importer.links = {'919000000002': ['Rolled']}, {'Rolled': {'Shop'}}
        importer.copied = {'/private/files/relay-archive-x'}
        with patch.object(legacy_database, 'remove_unused_copies') as remove:
            importer.rollback()
        frappe.db.rollback.assert_called_once()
        remove.assert_called_once_with({'/private/files/relay-archive-x'})
        self.assertEqual(importer.counts['created'], 5)
        self.assertEqual((importer.phones, importer.links), (None, None))
        self.assertEqual((importer.unresolved, importer.pending_unresolved, importer.copied), ([{'conversation': 'c1'}], [], set()))

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
             patch.object(importer, 'finish'), \
             patch('relay_core.identity.default_region', return_value='IN'):
            importer.import_conversation(conversation())
        self.assertEqual(commit.call_count, 3)
        added = [call.args[1][0] for call in frappe.db.sql.call_args_list if 'imported = imported' in call.args[0]]
        self.assertEqual(added, [2, 1])


    def test_deadlock_with_live_traffic_is_retried_from_a_clean_state(self):
        importer = Importer()
        calls = []
        def work():
            calls.append(1)
            importer.failures.append({'message': 'm1', 'error': 'listed in the failed attempt'})
            if len(calls) == 1:
                raise frappe.QueryDeadlockError('1020')
            return 'done'
        with patch.object(importer, 'rollback') as rollback, patch.object(importer, 'commit') as commit, \
             patch.object(legacy_database.time, 'sleep'):
            self.assertEqual(importer.transaction(work), 'done')
        rollback.assert_called_once()
        commit.assert_called_once()
        self.assertEqual(len(importer.failures), 1)

    def test_deadlock_that_keeps_coming_back_is_raised(self):
        importer = Importer()
        with patch.object(importer, 'rollback'), patch.object(importer, 'commit'), patch.object(legacy_database.time, 'sleep'), \
             self.assertRaises(frappe.QueryDeadlockError):
            importer.transaction(Mock(side_effect=frappe.QueryDeadlockError('1020')))


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
    def test_only_unassigned_imported_conversations_get_the_team_and_the_marker_records_it(self):
        markers = [frappe._dict(name='IMPORT-1', relay_contact='RELAY-CON-1'), frappe._dict(name='IMPORT-2', relay_contact='RELAY-CON-2'),
                   frappe._dict(name='IMPORT-3', relay_contact='RELAY-CON-1')]
        lists = {'Relay Legacy Import': markers, 'Relay Conversation Assignment': ['RELAY-CON-2']}
        inserted = []
        def get_doc(*args):
            if isinstance(args[0], dict):
                return Mock(insert=lambda: inserted.append(args[0]) or frappe._dict(name='ASG-1'))
            return Mock()
        frappe.db.get_value.return_value = json.dumps({'created': {'endpoint': 'EP-1'}})
        with patch.object(frappe, 'get_all', side_effect=lambda doctype, **kwargs: lists[doctype]), \
             patch.object(frappe, 'get_doc', side_effect=get_doc) as get, \
             patch('relay_core.queue_counts.invalidate') as invalidate:
            result = legacy_database.assign_team('sales.example', 'Sales-001')
        get.assert_any_call('Relay Team', 'Sales-001')
        self.assertEqual(result, {'assigned': 1, 'already_assigned': 1})
        self.assertEqual(inserted, [{'doctype': 'Relay Conversation Assignment', 'relay_contact': 'RELAY-CON-1', 'team': 'Sales-001'}])
        marker, field, value = frappe.db.set_value.call_args.args[1:4]
        self.assertEqual((marker, field, json.loads(value)), ('IMPORT-1', 'source_metadata', {'created': {'endpoint': 'EP-1', 'assignment': 'ASG-1'}}))
        invalidate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
