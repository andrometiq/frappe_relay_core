"""Cutover regressions: frozen exports and collaboration replay ownership."""
from copy import deepcopy
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import frappe
from relay_core import legacy, legacy_bundle as bundles, legacy_metadata as metadata


class ReplayTests(unittest.TestCase):
    def test_frozen_export_includes_sends_and_media_without_modified_changes(self):
        row = frappe._dict(name='old', creation='2020-01-01', modified='2020-01-01',
            delivery_status='Queued', provider_message_id='provisional', content='{}', channel='channel', conversation='conversation')
        manifest = dict(format='relay-legacy-history', version=2, metadata={}, attachments={}, warnings=[],
            source_site='old', source_conversation='conversation', source_channel='channel', endpoint='123', identifier_type='Phone')
        files = []
        queries = []

        def sql(query, values, **kwargs):
            queries.append(query)
            if 'modified >=' in query: return []
            return [row.copy()]

        fake = SimpleNamespace(db=SimpleNamespace(sql=sql), get_installed_apps=lambda: [], _dict=frappe._dict,
            get_doc=lambda *args: files[0])
        with tempfile.TemporaryDirectory() as directory, patch.object(bundles, 'frappe', fake), \
             patch.object(bundles, 'describe', side_effect=lambda _: deepcopy(manifest)), \
             patch.object(bundles, 'require_access'), patch.object(bundles, 'related', side_effect=lambda *args: files), \
             patch.object(bundles, 'source_file', side_effect=lambda _: io.BytesIO(b'cached media')):
            def export(name, **options):
                path = Path(directory) / name
                bundles.export_conversation('conversation', path, upper=('2020-01-01', 'old'),
                    watermark='2020-02-01', **options)
                return bundles.decode(path)
            snapshot = export('snapshot.zip')
            # Legacy outbound._mark_sent uses SQL without updating modified.
            row.update(delivery_status='Sent', provider_message_id='final-provider')
            # Legacy message_media caches content with update_modified=False.
            row.content = bundles.canonical({'document': {'local_file_url': '/private/files/cache.bin'},
                '_media_cache': {'status': 'stored', 'file': 'cached'}})
            files.append(frappe._dict(name='cached', file_name='cache.bin'))
            self.assertEqual(export('delta.zip', since='2020-01-02')['rows'], [])
            frozen = export('frozen.zip', since='2020-01-02', frozen=True)
            self.assertEqual(snapshot['rows'][0].modified, frozen['rows'][0].modified)
            self.assertEqual(frozen['rows'][0].delivery_status, 'Sent')
            self.assertEqual(frozen['rows'][0].provider_message_id, 'final-provider')
            self.assertEqual(json.loads(frozen['rows'][0].content)['_media_cache']['status'], 'stored')
            self.assertEqual(frozen['files']['old'][0]['size'], len(b'cached media'))
            self.assertNotIn('modified', queries[-1])
            self.assertIsNone(frozen['manifest']['since'])
            self.assertTrue(frozen['manifest']['frozen'])

    def test_triage_does_not_project_any_collaboration(self):
        job = frappe._dict(relay_contact='contact', channel='channel')
        manifest = dict(source_site='site', source_conversation='conversation', metadata={
            'notes': [{'name': 'secret', 'content': 'Restricted triage note'}],
            'topics': [{'name': 'secret-topic', 'title': 'Restricted triage topic'}]})
        with patch.object(metadata, 'previous_projections', return_value={}), \
             patch.object(metadata, 'direct_document', side_effect=AssertionError('Leaked collaboration')), \
             patch.object(metadata.frappe, 'db', SimpleNamespace(
                 set_value=Mock(side_effect=AssertionError('Updated triage collaboration')))):
            report = {'mismatches': []}
            metadata.import_metadata(job, manifest, report)
        self.assertEqual(report['related_counts']['notes'], 1)
        self.assertIn('Restricted triage', report['business_mapping'])
        self.assertEqual(manifest['metadata']['notes'][0]['content'], 'Restricted triage note')

    def test_field_merge_preserves_live_edits_and_reports_conflicts(self):
        for doctype, field in [('Relay Conversation Assignment', 'assigned_to'),
                               ('Relay Conversation State', 'last_read'),
                               ('Relay Internal Comment', 'body'),
                               ('Relay Conversation Topic', 'title')]:
            with self.subTest(doctype=doctype):
                baseline = {field: 'imported', 'untouched': 'original'}
                current = dict(baseline, **{field: 'live edit'})
                desired = {field: 'new source', 'untouched': 'updated source'}
                updates, conflicts = metadata.merge_projection(doctype, current, baseline, desired)
                self.assertEqual(updates, {'untouched': 'updated source'})
                self.assertEqual(conflicts, [field])
                current.update(updates); baseline.update(updates)
                self.assertEqual(metadata.merge_projection(doctype, current, baseline, desired)[1], [field])

    def test_read_cursors_never_retreat_even_without_live_edits(self):
        baseline = dict(last_read='RELAY-MSG-0000000020', last_seen=datetime(2026, 1, 2), exact_reads=1)
        values = dict(last_read='RELAY-MSG-0000000001', last_seen='2026-01-01 00:00:00', exact_reads=1)
        updates, conflicts = metadata.merge_projection('Relay Conversation State', baseline, baseline, values)
        self.assertEqual(updates, {'exact_reads': 1})
        self.assertEqual(conflicts, ['last_read', 'last_seen'])

    def test_untracked_existing_state_is_not_adopted(self):
        updates, conflicts = metadata.merge_projection('Relay Internal Comment', {'body': 'live'}, {}, {'body': 'source'})
        self.assertEqual(updates, {})
        self.assertEqual(conflicts, ['body'])

    def test_reaction_replay_preserves_live_removal_and_canonical_actor(self):
        target = frappe._dict(name='target', reactions='{}', message_updates='{}')
        row = frappe._dict(name='reaction', sender_endpoint='123', direction='Incoming', sent_at='2020-01-01',
            message_data=bundles.canonical({'reaction': {'message_id': 'provider', 'emoji': '👍'},
                'reaction_actor': '123', 'reaction_timestamp': 100}))
        db = Mock()
        db.get_value.return_value = target
        db.set_value.side_effect = lambda dt, name, values, **kw: target.update(values)
        fake = SimpleNamespace(db=db, get_all=lambda *args, **kwargs: [row])
        with patch.object(metadata, 'frappe', fake):
            metadata.project_reactions(frappe._dict(relay_contact='contact', channel='channel'), {'mismatches': []})
            self.assertEqual(json.loads(target.reactions), {'123': [{'type': 'emoji', 'emoji': '👍'}]})
            original_data = row.message_data
            row.name = 'reaction-later'
            row.message_data = bundles.canonical({'reaction': {'message_id': 'provider', 'emoji': ''},
                'reaction_actor': '123', 'reaction_timestamp': 100})
            metadata.project_reactions(frappe._dict(relay_contact='contact', channel='channel'), {'mismatches': []})
            self.assertEqual(json.loads(target.reactions), {'123': []})
            row.name = 'reaction'; row.message_data = original_data
            target.reactions = bundles.canonical({'123': [], 'Incoming:123': [{'type': 'emoji', 'emoji': '👍'}]})
            target.message_updates = bundles.canonical({'reaction:123': {'timestamp': 101, 'event_id': 'live-removal'}})
            metadata.project_reactions(frappe._dict(relay_contact='contact', channel='channel'), {'mismatches': []})
            self.assertEqual(json.loads(target.reactions), {'123': []})
            self.assertEqual(json.loads(target.message_updates)['reaction:123']['event_id'], 'live-removal')
            row.message_data = row.message_data.replace('100', '101')
            metadata.project_reactions(frappe._dict(relay_contact='contact', channel='channel'), {'mismatches': []})
            self.assertEqual(json.loads(target.reactions), {'123': []})

    def test_reaction_source_timezone_is_preserved(self):
        self.assertEqual(legacy.reaction_timestamp('2020-01-01 05:30:00', 'Asia/Kolkata'),
                         legacy.reaction_timestamp('2020-01-01 00:00:00', 'UTC'))


if __name__ == '__main__': unittest.main()
