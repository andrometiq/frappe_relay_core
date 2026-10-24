"""Target-only cutover acceptance: real DB, private media and normal read APIs.

No source writes, source schemas, migrations or external effects. Records are
clearly labelled local-only and retained for review (no destructive cleanup).
"""
import hashlib
import io
import json
import os
from pathlib import Path
import time
from unittest.mock import patch
import zipfile

import frappe
from relay_core import legacy, legacy_bundle as bundles, attachments, api
from relay_core.legacy_metadata import direct_document, prepare_import


def main():
    import sys
    from integration_ai_permissions_site import confine_writes
    sys.addaudithook(confine_writes)
    os.environ['FRAPPE_STREAM_LOGGING']='1'
    os.chdir('/home/sakthi/development/pilot/benches/version_16/sites')
    frappe.init(site='yrp.site'); frappe.connect(); frappe.set_user('Administrator'); frappe.flags.mute_emails = True
    storage=Path(__file__).resolve().parents[1]/'.runtime/backend-legacy-files'
    (storage/'private/files').mkdir(parents=True,exist_ok=True)
    site_path=frappe.get_site_path
    def local_files(*parts):
        if parts and parts[0]=='private':return str(storage.joinpath(*parts))
        return site_path(*parts)
    files_patch=patch.object(frappe,'get_site_path',side_effect=local_files);files_patch.start()
    from frappe.core.doctype.file.file import File
    full_path=File.get_full_path
    def local_full_path(doc):
        if str(doc.file_url).startswith(('/private/files/local-only-', '/private/files/relay-archive-')):
            return str(storage/str(doc.file_url).lstrip('/'))
        return full_path(doc)
    file_patch=patch.object(File,'get_full_path',local_full_path);file_patch.start()
    run = str(time.time_ns()); site = 'local-only-relay-cutover-' + run
    customer = 'Local-only Relay migration ' + run
    direct_document('Customer', dict(customer_name=customer, customer_type='Company'), customer)
    from relay_core.permissions import sequential_name
    channel = direct_document('Relay Channel', dict(channel='WhatsApp', account=site, enabled=0), sequential_name('channel')).name
    metadata = {'timezone':'UTC', 'identity': {'name': 'original-person', 'identifier_type': 'Phone'},
        'channel': {'phone_number_id': 'local-only-number-' + run},
        'conversation': {'name': 'conversation', 'status': 'Resolved', 'assigned_user': 'old-staff'},
        'staff_reads': [{'name': 'read', 'user': 'old-staff', 'message': 'zzz', 'read_at': '2020-01-02 12:00:00'}],
        'conversation_reads': [{'name': 'cursor', 'user': 'old-staff', 'last_read_message': 'zzz', 'last_opened_at': '2020-01-03 12:00:00'}],
        'notes': [{'name': 'note', 'user': 'old-staff', 'content': 'Local-only note with meaningful evidence', 'message_references': '["zzz"]', 'status': 'Resolved'}],
        'topics': [{'name': 'topic', 'title': 'Local-only topic', 'summary': 'Shipment reference 123', 'status': 'Resolved'}],
        'topic_messages': [{'name': 'topic-link', 'topic': 'topic', 'message': 'zzz'}]}
    base = dict(format='relay-legacy-history', version=2, source_site=site, source_conversation='conversation',
        source_channel='old-channel', endpoint='local-only-' + run, identifier_type='Phone', metadata=metadata,
        metadata_sha256=bundles.checksum(metadata), warnings=[], watermark='2020-02-01 00:00:00')
    raw = bytes(range(256)) * 24576  # 6 MiB, includes non-text bytes.
    digest = hashlib.sha256(raw).hexdigest()
    source = [frappe._dict(name='zzz', creation='2020-01-01 00:00:00', modified='2020-01-01 00:00:00',
        owner='old-staff', channel='old-channel', conversation='conversation', body='Local-only invoice 123: amount 456.78',
        message_type='document', content='{}', direction='Outbound', delivery_status='Queued', provider_message_id='local-only-provider-' + run)]
    for i in range(51):
        source.append(frappe._dict(dict(source[0], name='row-' + str(i).zfill(3), creation='2020-01-02 00:00:00',
            message_type='text', body='Local-only history ' + str(i), provider_message_id='local-only-' + run + '-' + str(i))))
    media = {'zzz': [{'path': 'files/' + digest, 'filename': 'local-only-six-mib.bin',
        'availability': 'available', 'size': len(raw), 'sha256': digest}]}

    def bundle(rows, *, files=None, since=None, mapped=True, metadata_override=None, watermark=None):
        manifest = dict(base, watermark=watermark or base['watermark'], count=len(rows), attachments=files or {}, since=since,
            messages_sha256=hashlib.sha256(bundles.canonical(rows).encode()).hexdigest())
        if metadata_override is not None:
            manifest.update(metadata=metadata_override, metadata_sha256=bundles.checksum(metadata_override))
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as archive:
            archive.writestr('manifest.json', bundles.canonical(manifest)); archive.writestr('messages.json', bundles.canonical(rows))
            if files: archive.writestr('files/' + digest, raw)
        content = out.getvalue(); name = 'local-only-cutover-' + hashlib.sha256(content).hexdigest() + '.zip'
        path = Path(frappe.get_site_path('private', 'files', name)); path.write_bytes(content); path.chmod(0o600)
        file = direct_document('File', dict(file_name=name, file_url='/private/files/' + name, is_private=1, file_size=len(content)))
        return prepare_import(manifest, channel, source_bundle=file.name,
            business=('Customer', customer) if mapped else None, user_map={'old-staff': 'Administrator'})

    def finish(job):
        frappe.db.commit()
        while True:
            for attempt in range(3):
                try:
                    result = legacy.run_batch(job.name)
                    break
                except frappe.QueryDeadlockError:
                    frappe.db.rollback()
                    if attempt == 2: raise
            if result['status'] == 'Completed': return result

    try:
        with patch.object(frappe, 'publish_realtime'), patch.object(frappe, 'enqueue', side_effect=AssertionError('History enqueued work')), \
             patch.object(frappe, 'sendmail', side_effect=AssertionError('History sent email')), \
             patch('relay_core.whatsapp.client', side_effect=AssertionError('History called provider')):
            first = bundle(source, files=media); result = finish(first)
            assert result['imported'] == 52 and result['mismatches'] == 0, result
            target = frappe.db.get_value('Relay Message', {'source_key': legacy.source_key(site, 'zzz')}, 'name')
            doc = frappe.get_doc('Relay Message', target)
            assert doc.status == 'Pending' and doc.owner == 'Administrator' and doc.legacy_author == 'old-staff'
            assert attachments.read(target).get_data() == raw
            assert frappe.db.count('Relay Message Read', {'message': target}) == 1
            assert frappe.db.count('Relay Internal Comment', {'relay_contact': first.relay_contact}) == 1
            assert frappe.db.count('Relay Conversation Topic', {'relay_contact': first.relay_contact}) == 1
            assert frappe.db.get_value('Relay Contact Endpoint', {'channel': channel}, 'verified') == 0
            from relay_core import collaboration, topics
            notes = collaboration.comments(first.relay_contact)['items']
            assert frappe.db.get_value('Relay Internal Comment',notes[0]['name'],'business_name')==customer
            assert len(notes) == 1 and notes[0]['name'].startswith('RELAY-NOTE-')
            assert len(topics.directory(first.relay_contact)['items']) == 1
            history = api.messages(first.relay_contact, channel=channel)
            assert history['items'], history
            # Simulate the authoritative import baseline before business fields existed.
            report=json.loads(frappe.db.get_value('Relay Legacy Import',first.name,'reconcile_report'))
            upgraded=[]
            for baseline in report['collaboration_projections'].values():
                fields=baseline['fields']
                if 'business_name' not in fields:continue
                dt='Relay Internal Comment' if 'body' in fields else 'Relay Conversation Topic'
                upgraded.append((dt,baseline['name']))
                fields.pop('business_name');fields.pop('business_doctype')
                frappe.db.set_value(dt,baseline['name'],{'business_doctype':None,'business_name':None})
            frappe.db.set_value('Relay Legacy Import',first.name,'reconcile_report',json.dumps(report));frappe.db.commit()
            again = finish(bundle(source, files=media)); assert again['imported'] == 0 and again['skipped'] == 52, again
            assert len(upgraded)==2
            for dt,name in upgraded:assert frappe.db.get_value(dt,name,'business_name')==customer
            sent = frappe._dict(dict(source[0], delivery_status='Sent', provider_message_id='local-only-sent-' + run))
            sent_result = finish(bundle([sent], files=media,watermark='2020-02-02 00:00:00'))
            assert sent_result['updated'] == 1 and sent.modified == source[0].modified
            doc.reload(); assert doc.status == 'Sent' and doc.provider_id == sent.provider_message_id
            old_snapshot=finish(bundle([source[0]],files=media))
            assert old_snapshot['mismatches']==1 and old_snapshot['updated']==0
            doc.reload();assert doc.status=='Sent' and doc.provider_id==sent.provider_message_id
            assert doc.sent_at==legacy.source_datetime(source[0].creation,'UTC')
            cached = frappe._dict(dict(sent, content=bundles.canonical({'document': {'local_file_url': '/private/files/cache.bin'},
                '_media_cache': {'status': 'stored', 'file': 'local-only-cache'}})))
            cache_result = finish(bundle([cached], files=media,watermark='2020-02-03 00:00:00'))
            assert cache_result['updated'] == 1 and cached.modified == source[0].modified
            doc.reload(); assert json.loads(doc.legacy_data)['row']['content'] == cached.content
            assert attachments.read(target).get_data() == raw
            changed = frappe._dict(dict(source[0], modified='2020-02-02 00:00:00', delivery_status='Read', body='Updated amount 999.50'))
            new = frappe._dict(dict(source[1], name='aaa', creation='2020-02-02 00:00:00', modified='2020-02-02 00:00:00', provider_message_id='local-only-new-' + run))
            delta = finish(bundle([changed, new], files=media, since=base['watermark']))
            assert delta['updated'] == 1 and delta['imported'] == 1, delta
            doc.reload(); assert doc.status == 'Read' and doc.content == changed.body
            assert attachments.read(target).get_data() == raw
            stale = finish(bundle([source[0]], files=media)); assert stale['mismatches'] == 1 and stale['updated'] == 0, stale
            doc.reload(); assert doc.status == 'Read'
            broken = frappe._dict(dict(new, name='bad-direction', direction='Unknown', provider_message_id='bad-' + run))
            good = frappe._dict(dict(new, name='good-after-error', provider_message_id='good-' + run))
            failure = finish(bundle([broken, good])); assert failure['imported'] == 1 and failure['mismatches'] == 1, failure
            assert not frappe.db.exists('Relay Message Action', {'target_channel': channel})
            assert not frappe.db.exists('Relay Automation Run', {'message': target})
            from relay_core import messaging
            try: messaging.readable_source(target)
            except frappe.PermissionError: pass
            else: raise AssertionError('Historical Pending source was sendable')

            from relay_core import inbox, teams, message_updates
            from relay_core.permissions import sequential_name
            live = direct_document('Relay Message', dict(relay_contact=first.relay_contact, channel=channel,
                direction='Incoming', status='Delivered', content='Local-only live follow-up: amount 1200',
                business_doctype='Customer', business_name=customer, message_type='text'), sequential_name('message'))
            note = notes[0]['name']
            topic = topics.directory(first.relay_contact)['items'][0]
            collaboration.edit(note, body='Local-only staff correction')
            teams.assign(first.relay_contact)
            inbox.update(first.relay_contact, last_read=live.name)
            last_seen = inbox.read(first.relay_contact)['last_seen']
            topics.save(first.relay_contact, dict(title='Local-only live topic title', summary=topic['summary'],
                status=topic['status'], category='', messages=topic['messages'], modified=str(topic['modified'])), name=topic['name'])
            updated_metadata = json.loads(json.dumps(metadata))
            updated_metadata['notes'][0]['status'] = 'Open'
            updated_metadata['topics'][0]['summary'] = 'Updated source summary'
            for _ in range(2):
                replay_job = bundle([changed, new], files=media, metadata_override=updated_metadata)
                edited_replay = finish(replay_job)
                assert edited_replay['imported'] == 0
                assert frappe.db.get_value('Relay Internal Comment', note, 'body') == 'Local-only staff correction'
                assert frappe.db.get_value('Relay Internal Comment', note, 'task_status') == 'Open'
                assert not frappe.db.get_value('Relay Conversation Assignment', {'relay_contact': first.relay_contact}, 'assigned_to')
                assert inbox.read(first.relay_contact)['last_read'] == live.name
                assert inbox.read(first.relay_contact)['last_seen'] == last_seen
                assert frappe.db.get_value('Relay Conversation Topic', topic['name'], 'title') == 'Local-only live topic title'
                assert frappe.db.get_value('Relay Conversation Topic', topic['name'], 'summary') == 'Updated source summary'
                report = json.loads(frappe.db.get_value('Relay Legacy Import', replay_job.name, 'reconcile_report'))
                conflicts = [r['detail'] for r in report['mismatches'] if r['kind'] == 'collaboration_conflict']
                for dt in ('Relay Internal Comment', 'Relay Conversation Assignment', 'Relay Conversation State', 'Relay Conversation Topic'):
                    assert any(detail.startswith(dt + ':') for detail in conflicts), conflicts

            triage_metadata = dict(metadata, notes=[dict(name='restricted-note', user='old-staff', content='Restricted triage secret')],
                topics=[dict(name='restricted-topic', title='Restricted triage title')], topic_messages=[])
            triage_row = frappe._dict(dict(new, name='restricted-message', provider_message_id='restricted-' + run))
            triage_job = bundle([triage_row], mapped=False, metadata_override=triage_metadata)
            finish(triage_job)
            assert frappe.db.count('Relay Internal Comment', {'relay_contact': first.relay_contact}) == 1
            assert frappe.db.count('Relay Conversation Topic', {'relay_contact': first.relay_contact}) == 1
            assert 'Restricted triage secret' in frappe.db.get_value('Relay Legacy Import', triage_job.name, 'source_metadata')
            reader = 'local-only-relay-' + run + '@example.invalid'
            direct_document('User', dict(email=reader, first_name='Local-only migration reader', enabled=1,
                user_type='System User'), reader)
            for role in ('Relay Communication User', 'Sales User'):
                direct_document('Has Role', dict(parent=reader, parenttype='User', parentfield='roles', role=role))
            teams.assign(first.relay_contact, assigned_to=reader); frappe.db.commit()
            frappe.set_user(reader)
            assert not frappe.has_permission('Relay Legacy Import', 'read', doc=triage_job.name)
            restricted = frappe.db.get_value('Relay Message', {'source_key': legacy.source_key(site, triage_row.name)}, 'name')
            assert not frappe.has_permission('Relay Message', 'read', doc=restricted)
            assert all(item['body'] != 'Restricted triage secret' for item in collaboration.comments(first.relay_contact)['items'])
            assert all(item['title'] != 'Restricted triage title' for item in topics.directory(first.relay_contact)['items'])
            frappe.set_user('Administrator')

            reaction = frappe._dict(dict(new, name='reaction', message_type='reaction', direction='Inbound',
                provider_message_id='reaction-' + run, content=bundles.canonical({'from': base['endpoint'],
                    'reaction': {'message_id': changed.provider_message_id, 'emoji': '👍'}})))
            finish(bundle([reaction]))
            doc.reload(); assert json.loads(doc.reactions)[base['endpoint']][0]['emoji'] == '👍'
            endpoint = frappe.db.get_value('Relay Contact Endpoint', {'channel': channel}, 'name')
            frappe.db.set_value('Relay Contact Endpoint', endpoint, 'verified', 1)
            removal = {'channel': 'WhatsApp', 'entry': [{'changes': [{'value': {'messages': [{
                'type': 'reaction', 'from': base['endpoint'], 'id': 'local-only-live-removal-' + run,
                'timestamp': str(legacy.reaction_timestamp(reaction.creation,'UTC') + 1),
                'reaction': {'message_id': changed.provider_message_id, 'emoji': ''}}]}}]}]}
            assert message_updates.apply_updates(removal, channel, 'local-only-removal') == 'Projected'
            frappe.db.commit()
            finish(bundle([reaction]))
            doc.reload(); assert json.loads(doc.reactions) == {base['endpoint']: []}
            assert json.loads(doc.message_updates)['reaction:' + base['endpoint']]['event_id'] == 'local-only-live-removal-' + run
            print(json.dumps(dict(snapshot=result, replay=again, delta=delta, stale=stale, failure=failure,
                private_attachment_bytes=len(raw), channel=channel, no_resend=True,
                live_edits_preserved=True, triage_denied=True, live_reaction_removal_preserved=True), indent=2))
    finally:
        file_patch.stop();files_patch.stop();frappe.destroy()


if __name__ == '__main__': main()
