import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

import frappe
from relay_core import legacy, legacy_bundle, legacy_media, business_access


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(legacy.frappe.utils, 'get_system_timezone', return_value='UTC'))

    def row(self, **kw):
        return frappe._dict(dict(name='z9', creation='2020-01-01 10:00:00', modified='2020-01-01 10:00:00',
            channel='old-channel', conversation='old-conversation', message_type='text', content='{}', body='Hello',
            direction='Outbound', delivery_status='Queued', owner='original@example.invalid',
            provider_message_id='provider-1', message_key='old-key', idempotency_key='old-intent', relay_event='old-event', **kw))

    def test_identity_is_site_scoped_and_mode_independent(self):
        self.assertEqual(legacy.source_key('site-a', 'z9'), legacy.source_key('site-a', 'z9'))
        self.assertNotEqual(legacy.source_key('site-a', 'z9'), legacy.source_key('site-b', 'z9'))
        row = self.row(); row.custom_extra = 'Retained'
        job = frappe._dict(channel='new-channel', relay_contact='contact')
        manifest = dict(source_site='site-a', endpoint='919000000000', identifier_type='Phone')
        values, data, notes = legacy.projection(row, job, manifest)
        self.assertEqual(json.loads(values['legacy_data'])['row'], row)
        self.assertEqual(values['legacy_checksum'], legacy_bundle.checksum(row))
        self.assertEqual(values['legacy_author'], row.owner)
        self.assertEqual(values['status'], 'Pending')
        self.assertEqual(values['legacy_triage'], 1)
        self.assertIsNone(values['business_name'])
        self.assertTrue(json.loads(values['provider_context'])['historical'])

    def test_old_import_adoption_requires_exact_original_provenance(self):
        old = frappe._dict(legacy_source='z9', legacy_data=json.dumps(dict(self.row(), source_site='site')))
        self.assertTrue(legacy.same_origin(old, 'site', 'z9'))
        self.assertFalse(legacy.same_origin(old, 'another-site', 'z9'))
        self.assertFalse(legacy.same_origin(old, 'site', 'another-message'))
        self.assertFalse(legacy.same_origin(frappe._dict(provider_id='same'), 'site', 'z9'))

    def test_mapping_typed_content_quotes_deletion(self):
        cases = [('location', {'latitude': 12.3, 'longitude': 77.5}, 'location'),
                 ('contacts', [{'name': {'formatted_name': 'Pat'}, 'phones': [{'phone': '123'}]}], 'contacts'),
                 ('image', {'id': '100', 'mime_type': 'image/jpeg'}, 'image'),
                 ('reaction', {'message_id': 'quoted', 'emoji': '👍'}, 'reaction')]
        for kind, payload, expected in cases:
            row = self.row(); row.message_type = kind
            row.content = json.dumps({kind: payload, 'context': {'id': 'quoted'}})
            data, quote, _, notes = legacy.converted(row)
            self.assertEqual(data['kind'], expected); self.assertEqual(quote, 'quoted')
        row.delivery_status = 'Deleted'
        self.assertEqual(legacy.converted(row)[0]['text'], '[Deleted message]')

    def test_template_rendering_does_not_mutate_original(self):
        row = self.row(); row.message_type = 'template'
        original = dict(row)
        job = frappe._dict(channel='channel', relay_contact='contact', business_doctype='Customer', business_name='C1')
        manifest = dict(source_site='source', endpoint='123', identifier_type='BSUID', rendered_content={row.name:
            json.dumps({'template_snapshot': {'body': 'Hi Pat', 'header_type': 'image', 'header_media': '/private/files/header.png'}})})
        values, data, notes = legacy.projection(row, job, manifest)
        self.assertEqual(data['kind'], 'image'); self.assertEqual(data['caption'], 'Hi Pat')
        self.assertEqual(json.loads(values['legacy_data'])['row'], original)
        self.assertEqual(json.loads(values['provider_context'])['identifier_type'], 'BSUID')
        self.assertEqual(values['business_name'], 'C1'); self.assertEqual(values['legacy_triage'], 0)

    def test_creation_cursor_and_inclusive_modified_delta(self):
        early = dict(name='zzzz', creation='2020-01-01 10:00:00')
        late = dict(name='aaaa', creation='2020-01-02 10:00:00')
        self.assertLess(legacy_bundle.order_key(early), legacy_bundle.order_key(late))
        db = Mock(); db.sql.return_value = []
        with patch.object(legacy_bundle, 'frappe', SimpleNamespace(db=db)):
            legacy_bundle.rows('conversation', after=legacy_bundle.order_key(early), upper=legacy_bundle.order_key(late),
                since='2020-01-01', until='2020-01-03')
        query, args = db.sql.call_args.args
        self.assertIn('(creation, name) >', query); self.assertIn('modified >= %(since)s', query)
        self.assertIn('modified <= %(until)s', query)
        self.assertEqual(args['after_name'], 'zzzz'); self.assertEqual(args['upper_name'], 'aaaa')

    def test_large_attachment_stream_is_bounded_and_exact(self):
        raw = b'\x00\xffhello' * 900000
        class Bounded(io.BytesIO):
            def read(self, size=-1):
                if size < 0 or size > legacy_media.CHUNK: raise AssertionError('Unbounded read')
                return super().read(size)
        target = io.BytesIO()
        digest, size = legacy_media.copy_stream(Bounded(raw), target)
        self.assertGreater(size, 4 * 1024 * 1024)
        self.assertEqual(target.getvalue(), raw); self.assertEqual(digest, hashlib.sha256(raw).hexdigest())

    def bundle(self, filename='files/'+'a'*64, raw=b'content'):
        row = self.row(); messages = legacy_bundle.canonical([row]).encode()
        manifest = dict(format='relay-legacy-history', version=2, source_site='source', source_conversation=row.conversation,
            source_channel=row.channel, endpoint='123', identifier_type='Phone', count=1, metadata={},
            metadata_sha256=legacy_bundle.checksum({}), messages_sha256=hashlib.sha256(messages).hexdigest(),
            attachments={row.name: [dict(path=filename, filename='media.bin', availability='available',
                sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))]})
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('manifest.json', json.dumps(manifest)); archive.writestr('messages.json', messages)
            archive.writestr(filename, raw)
        return output.getvalue()

    def test_bundle_large_file_and_safe_paths(self):
        raw = b'x' * (5 * 1024 * 1024)
        bundle = legacy_bundle.decode(self.bundle(raw=raw))
        self.assertNotIn('content', bundle['files']['z9'][0])
        with legacy_bundle.open_attachment(bundle, bundle['files']['z9'][0]) as stream:
            digest, size = legacy_media.copy_stream(stream, io.BytesIO())
        self.assertEqual(size, len(raw)); self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
        with patch.object(legacy_bundle.frappe, 'throw', side_effect=ValueError), self.assertRaises(ValueError):
            legacy_bundle.decode(self.bundle(filename='../outside'))

    def test_missing_media_is_explicit(self):
        row = self.row(); row.message_type = 'image'
        job = frappe._dict(flags=frappe._dict(legacy_bundle={'files': {}}))
        data = {'kind': 'image'}
        entries = legacy.media_for(row, job, 'message', data)
        self.assertEqual(entries[0]['availability'], 'unavailable')
        self.assertEqual(data['legacy_attachments'], entries)

    def test_unresolved_business_is_never_inferred(self):
        with patch.object(business_access, 'candidates', side_effect=AssertionError('Guessed business')):
            self.assertIsNone(business_access.reference(frappe._dict(legacy_triage=1, relay_contact='contact')))

    def test_bulk_history_has_no_document_or_enqueue_path(self):
        db = Mock()
        forbidden = Mock(side_effect=AssertionError('History triggered side effects'))
        fake = SimpleNamespace(db=db, get_doc=forbidden, enqueue=forbidden)
        with patch.object(legacy, 'frappe', fake):
            legacy.insert_rows('Relay Message', [{'name': 'one', 'status': 'Pending', 'legacy_source': 'old'}])
        db.bulk_insert.assert_called_once(); forbidden.assert_not_called()

    def test_delta_updates_and_replay_skips_without_hooks(self):
        records = {}
        class Database:
            def get_value(self, doctype, filters, fields, **kw):
                found = records.get(filters) if isinstance(filters, str) else next(
                    (r for r in records.values() if all(r.get(k) == v for k, v in filters.items())), None)
                if not found: return None
                return frappe._dict({k: found.get(k) for k in fields}) if isinstance(fields, list) else found.get(fields)
            def set_value(self, doctype, name, values, **kw): records[name].update(values)
            def bulk_insert(self, doctype, fields, values):
                for row in values:
                    record = dict(zip(fields, row)); records[record['name']] = record
        fake = SimpleNamespace(db=Database(), session=SimpleNamespace(user='importer'),
            utils=SimpleNamespace(get_system_timezone=lambda:'UTC', get_datetime=__import__('datetime').datetime.fromisoformat, now_datetime=lambda: '2026-01-01 00:00:00'), _dict=frappe._dict)
        manifest = dict(watermark='2026-01-01', source_site='site', source_channel='old-channel', endpoint='123', identifier_type='Phone')
        def job(): return frappe._dict(channel='channel', relay_contact='contact', flags=frappe._dict(legacy_bundle={'files': {}}))
        row = self.row()
        with patch.object(legacy, 'frappe', fake), patch('relay_core.permissions.sequential_name', return_value='message'):
            first = job(); result = legacy.import_rows(first, manifest, [row, frappe._dict(dict(row, name='duplicate-provider'))])
            self.assertEqual(first.imported, 1); self.assertEqual(len(result['mismatches']), 1)
            again = job(); legacy.import_rows(again, manifest, [row]); self.assertEqual(again.skipped, 1)
            sent = frappe._dict(dict(row, delivery_status='Sent', provider_message_id='final-provider'))
            snapshot = dict(manifest)
            manifest['watermark'] = '2026-01-02'
            completed = legacy.import_rows(job(), manifest, [sent])
            self.assertEqual(completed['updated'], 1)
            self.assertEqual(records['message']['status'], 'Sent')
            self.assertEqual(records['message']['provider_id'], 'final-provider')
            stale_pass = legacy.import_rows(job(), snapshot, [row])
            self.assertEqual(stale_pass['mismatches'][0]['kind'], 'conflict')
            self.assertEqual(records['message']['provider_id'], 'final-provider')
            manifest['watermark'] = '2026-01-03'
            cached = frappe._dict(dict(sent, content=json.dumps({'_media_cache': {'status': 'stored', 'file': 'cached'}})))
            completed = legacy.import_rows(job(), manifest, [cached])
            self.assertEqual(completed['updated'], 1)
            self.assertEqual(json.loads(records['message']['legacy_data'])['row']['content'], cached.content)
            replay = job(); legacy.import_rows(replay, manifest, [cached]); self.assertEqual(replay.skipped, 1)
            changed = frappe._dict(dict(row, modified='2020-02-01', delivery_status='Read', body='Changed'))
            delta = legacy.import_rows(job(), manifest, [changed]); self.assertEqual(delta['updated'], 1)
            self.assertEqual(records['message']['status'], 'Read'); self.assertEqual(records['message']['content'], 'Changed')
            stale = legacy.import_rows(job(), manifest, [row]); self.assertEqual(stale['mismatches'][0]['kind'], 'mapping')
            self.assertEqual(records['message']['status'], 'Read')

    def test_attachment_checksum_failure_never_creates_file_record(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            fake = SimpleNamespace(get_site_path=lambda *args: directory, get_doc=Mock(side_effect=AssertionError('Bad media attached')))
            with patch.object(legacy_media, 'frappe', fake), self.assertRaises(ValueError):
                legacy_media.attach(io.BytesIO(b'changed'), {'sha256': '0'*64, 'size': 7, 'filename': 'file'}, 'message')
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_source_storage_adapter_streams_and_closes(self):
        import sys
        stream = io.BytesIO(b'stored media')
        connection = SimpleNamespace(s3_settings=SimpleNamespace(disable_s3_operations=False),
            get_file_from_bucket=Mock(return_value={'Body': stream}))
        adapter = SimpleNamespace(getS3Connection=lambda: connection)
        file = frappe._dict(custom_is_s3_uploaded=1, custom_s3_key='explicit-key', custom_s3_bucket_name='explicit-bucket', check_permission=Mock())
        with patch.dict(sys.modules, {'frappe_s3_integration.s3_core': adapter}):
            with legacy_media.source_file(file) as source: self.assertEqual(source.read(100), b'stored media')
        self.assertTrue(stream.closed)
        connection.get_file_from_bucket.assert_called_once_with('explicit-key', 'explicit-bucket')
        file.check_permission.assert_called_once_with('read')

    def test_archived_media_of_a_checked_source_skips_the_file_owner_rule(self):
        import sys
        connection = SimpleNamespace(s3_settings=SimpleNamespace(disable_s3_operations=False),
            get_file_from_bucket=Mock(return_value={'Body': io.BytesIO(b'archived')}))
        file = frappe._dict(custom_is_s3_uploaded=1, custom_s3_key='key', custom_s3_bucket_name='bucket',
            check_permission=Mock(side_effect=PermissionError('Only the uploader')))
        with patch.dict(sys.modules, {'frappe_s3_integration.s3_core': SimpleNamespace(getS3Connection=lambda: connection)}):
            with self.assertRaises(PermissionError), legacy_media.source_file(file): pass
            with legacy_media.source_file(file, source_checked=True) as source: self.assertEqual(source.read(100), b'archived')

    def test_target_database_failure_is_not_hidden_as_missing_media(self):
        metadata = {'availability': 'available', 'path': 'files/' + 'a'*64}
        job = frappe._dict(flags=frappe._dict(legacy_bundle={'files': {'z9': [metadata]}}))
        from contextlib import contextmanager
        @contextmanager
        def opened(*args): yield io.BytesIO(b'data')
        with patch.object(legacy_bundle, 'open_attachment', opened), \
             patch.object(legacy_media, 'attach', side_effect=legacy_media.TargetDatabaseError('Database failed')):
            with self.assertRaises(legacy_media.TargetDatabaseError):
                legacy.media_for(self.row(), job, 'message', {'kind': 'text'})

    def test_triage_is_restricted_to_administrator(self):
        doc = frappe._dict(legacy_triage=1, relay_contact='contact')
        for roles, expected in [(['System Manager'], False), (['Relay Communication Manager'], False), (['Relay Communication User'], False)]:
            fake = SimpleNamespace(get_roles=lambda user: roles)
            with patch.object(business_access, 'frappe', fake):
                self.assertEqual(business_access.allowed(doc, user='reader'), expected)
                self.assertTrue(business_access.allowed(doc, user='Administrator'))

    def test_live_hooks_skip_history(self):
        from relay_core.automation import service
        from relay_core.flows import service as flows
        from relay_core import translations, email_preferences
        row = frappe._dict(legacy_source='old', direction='Incoming', message_type='text')
        with patch.object(frappe, 'conf', {'relay_automation_enabled': 1}), patch.object(frappe, 'enqueue', side_effect=AssertionError('History enqueued')):
            service.on_message(row); flows.on_message(row); email_preferences.on_message(row)
        # Translation hook checks deployment configuration before the history flag.
        with patch.object(translations, 'frappe', SimpleNamespace(conf={'relay_automation_enabled': 1}, enqueue=Mock(side_effect=AssertionError))):
            translations.on_message(row)


if __name__ == '__main__': unittest.main()
