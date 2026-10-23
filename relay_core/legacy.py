"""Idempotent history projection. Direct database writes deliberately bypass send hooks."""
import hashlib
import json

import frappe
from relay_core.permissions import require_access
from relay_core.message_updates import provider_key
from relay_core.message_types import normalize
from relay_core.automation.provenance import conversation_key
from relay_core import legacy_bundle as bundles

SOURCE = 'WhatsApp Core Message'
MEDIA = {'image', 'video', 'audio', 'document', 'sticker'}


def object_value(value):
    if isinstance(value, str):
        try: value = json.loads(value)
        except (ValueError, TypeError): return {}
    return value if isinstance(value, dict) else {}


def source_key(site, name):
    return hashlib.sha256(('frappe_whatsapp_core:' + site + ':' + name).encode()).hexdigest()


def same_origin(message, site, name):
    original = object_value(message.get('legacy_data'))
    row = original.get('row', original)
    return bool(message.get('legacy_source') and original.get('source_site') == site and row.get('name') == name)


def status(row):
    value = {'Received': 'Delivered', 'Queued': 'Pending', 'Deleted': 'Delivered'}.get(row.delivery_status, row.delivery_status)
    return value if value in ('Pending', 'Sent', 'Delivered', 'Read', 'Failed') else None


def converted(row):
    original=object_value(row.content);kind=str(row.message_type or 'text').lower()
    payload=original.get('payload') or original.get(kind) or {}
    notes=[]
    try:
        data=normalize(kind,payload,provider='WhatsApp',body=row.body or '')
    except (ValueError,TypeError,KeyError):
        data={'kind':'text','text':row.body or '['+kind+' message]'}
        notes.append('Original '+kind+' structure retained for review')
    if kind == 'template':
        snapshot=object_value(original.get('template_snapshot'))
        parts=[snapshot.get(key) for key in ('header','body','footer')]
        buttons=snapshot.get('buttons')
        if isinstance(buttons,list):
            parts += [button.get('text') for button in buttons[:10] if isinstance(button,dict)]
        rendered='\n\n'.join(part for part in parts if isinstance(part,str) and part.strip())
        data={'kind':'text','text':rendered or row.body or '[Template message]'}
        if not rendered:notes.append('Template snapshot unavailable; original parameters retained for review')
        header=str(snapshot.get('header_type') or '').lower()
        if header in ('image','video','document') and snapshot.get('header_media'):
            data={'kind':header,'caption':data['text'],'media':{}}
    elif kind == 'interactive':
        interactive=object_value(payload)
        selected=object_value(interactive.get('button_reply') or interactive.get('list_reply'))
        permission=object_value(interactive.get('call_permission_reply'))
        flow=object_value(interactive.get('nfm_reply'))
        label=selected.get('title') or selected.get('id') or flow.get('body')
        if permission:label='Call permission: '+str(permission.get('response') or 'Response received')
        if label or row.body:data={'kind':'text','text':str(label or row.body)}
    if kind == 'reaction':
        reaction = object_value(original.get('reaction') or payload)
        if isinstance(reaction.get('reaction'), dict): reaction = reaction['reaction']
        actor = (original.get('from') or original.get('from_user_id')) if row.direction == 'Inbound' else row.owner
        data = {'kind': 'reaction', 'reaction': reaction, 'reaction_actor': actor}
    if kind == 'template':
        data['template'] = original
    if data['kind']=='unsupported':notes.append('Original '+kind+' structure retained for review')
    if row.delivery_status=='Deleted':data={'kind':'text','text':'[Deleted message]'}
    quote=object_value(original.get('context')).get('id') or object_value(original.get('context')).get('message_id') or original.get('context_message_id')
    if not quote and isinstance(payload,dict):quote=payload.get('context_message_id') or object_value(payload.get('context')).get('id')
    file_url=payload.get('local_file_url') if isinstance(payload,dict) else None
    if kind=='template':file_url=object_value(original.get('template_snapshot')).get('header_media')
    return data,str(quote) if quote else None,file_url,notes


def mapping(name):
    require_access(configure=True)
    job = frappe.get_doc('Relay Legacy Import', name); job.check_permission('write')
    channel = frappe.get_doc('Relay Channel', job.channel); channel.check_permission('read')
    if channel.channel != 'WhatsApp': frappe.throw('A WhatsApp Relay channel is required')
    if job.source_bundle:
        bundle = bundles.load(job.source_bundle)
        if job.bundle_sha256 and job.bundle_sha256 != bundle['sha256']:
            frappe.throw('The source bundle changed after import started')
        manifest = bundle['manifest']; job.flags.legacy_bundle = bundle
    else:
        manifest = bundles.describe(job.source_conversation)
    if manifest['source_conversation'] != job.source_conversation:
        frappe.throw('Bundle conversation does not match this mapping')
    if job.source_site and job.source_site != manifest['source_site']:
        frappe.throw('Source site does not match this mapping')
    endpoint = manifest['endpoint']
    if not endpoint or len(endpoint) > 200: frappe.throw('Invalid source endpoint')
    job.flags.manifest = manifest
    return job, manifest, endpoint


def source_rows(job):
    after = (str(job.last_creation), job.last_source) if job.last_source and job.last_creation else None
    bundle = job.flags.get('legacy_bundle')
    if bundle:
        return [r for r in bundle['rows'] if not after or bundles.order_key(r) > after][:51]
    upper = (str(job.upper_creation), job.upper_source) if job.upper_source else None
    return bundles.rows(job.source_conversation, after, upper, job.delta_since, job.watermark, limit=51)


def save_job(job):
    previous = getattr(frappe.flags, 'relay_legacy_import_write', False)
    frappe.flags.relay_legacy_import_write = True
    try: job.save()
    finally: frappe.flags.relay_legacy_import_write = previous


def projection(row, job, manifest):
    if row.direction not in ('Inbound', 'Outbound') or not status(row):
        raise ValueError('Unknown direction or delivery status')
    rendered = frappe._dict(row.copy())
    rendered.content = manifest.get('rendered_content', {}).get(row.name, row.content)
    data, quote, url, warnings = converted(rendered)
    if data['kind'] == 'reaction':
        data['reaction_timestamp'] = reaction_timestamp(row.provider_timestamp or row.creation,
            manifest.get('metadata', {}).get('timezone'))
    context = {'provider': 'WhatsApp', 'message_id': row.provider_message_id,
               'identifier_type': manifest['identifier_type'], 'historical': True}
    if manifest['identifier_type'] == 'Group': context['group_id'] = manifest['endpoint']
    if quote: context['reply_to_message_id'] = quote
    key = source_key(manifest['source_site'], row.name)
    values = dict(relay_contact=job.relay_contact, channel=job.channel,
        direction='Incoming' if row.direction == 'Inbound' else 'Outgoing', status=status(row),
        content=data.get('text') or data.get('caption') or row.body or '', message_type=data['kind'],
        provider_id=row.provider_message_id, sender_endpoint=manifest['endpoint'],
        provider_context=bundles.canonical(context),
        provider_message_key=provider_key(job.channel, manifest['endpoint'], row.provider_message_id) if row.provider_message_id else None,
        conversation_key=conversation_key(job.channel, manifest['endpoint'], context),
        sent_at=row.provider_timestamp or row.creation, source_key=key, legacy_source=row.name,
        legacy_author=row.owner, legacy_checksum=bundles.checksum(row),
        legacy_data=bundles.canonical({'source_site': manifest['source_site'], 'row': row}),
        legacy_triage=0 if job.business_doctype and job.business_name else 1,
        business_doctype=job.business_doctype or None, business_name=job.business_name or None)
    return values, data, warnings


def reaction_timestamp(value, timezone_name=None):
    from zoneinfo import ZoneInfo
    stamp = frappe.utils.get_datetime(value)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ZoneInfo(timezone_name or frappe.utils.get_system_timezone()))
    return int(stamp.timestamp())


def media_for(row, job, message, data):
    from relay_core.legacy_media import attach, source_file, copy_stream, TargetDatabaseError
    import tempfile
    bundle = job.flags.get('legacy_bundle'); results = []
    entries = bundle['files'].get(row.name, []) if bundle else bundles.related('File',
        {'attached_to_doctype': SOURCE, 'attached_to_name': row.name})
    for entry in entries:
        if bundle and entry.get('availability') != 'available':
            results.append(entry); continue
        try:
            if bundle:
                with bundles.open_attachment(bundle, entry) as stream:
                    results.append(attach(stream, entry, message))
            else:
                file = frappe.get_doc('File', entry.name)
                with source_file(file) as source, tempfile.TemporaryFile() as temporary:
                    digest, size = copy_stream(source, temporary); temporary.seek(0)
                    results.append(attach(temporary, {'sha256': digest, 'size': size, 'filename': file.file_name}, message))
        except TargetDatabaseError:
            raise
        except Exception as exc:
            results.append({'availability': 'copy_failed', 'source_file': entry.get('source_file') or entry.get('name'),
                            'reason': type(exc).__name__})
    if not results and (row.message_type in MEDIA or data.get('media') is not None):
        results.append({'availability': 'unavailable', 'reason': 'No archived source File'})
    if results:
        data['legacy_attachments'] = results
        available = [item for item in results if item['availability'] == 'available']
        if available:
            data.update(attachment=available[0]['attachment'], attachment_source=message)
            if data['kind'] in ('text', 'unsupported'):
                data.update(kind='document', caption=data.get('text') or row.body or '')
    return results


def insert_rows(doctype, records):
    """Only migration callers use this: no controller, hook, enqueue or provider path."""
    if not records: return
    fields = sorted(set().union(*(record.keys() for record in records)))
    frappe.db.bulk_insert(doctype, fields=fields, values=[[row.get(field) for field in fields] for row in records])


def import_rows(job, manifest, rows):
    from relay_core.permissions import sequential_name
    report = object_value(job.reconcile_report) or {'types': {}, 'statuses': {}, 'mismatches': [],
        'checked': 0, 'attachment_bytes': 0, 'unavailable_media': 0, 'updated': 0, 'identity_matches': 0, 'payload_matches': 0}
    inserted = []; expected = []; pending_providers = set()
    existing_fields = ['name', 'relay_contact', 'channel', 'legacy_checksum', 'legacy_data',
                       'legacy_source', 'message_data', 'business_doctype', 'business_name']
    for row in rows:
        key = source_key(manifest['source_site'], row.name)
        existing = frappe.db.get_value('Relay Message', {'source_key': key}, existing_fields, as_dict=True)
        try:
            if row.channel != manifest['source_channel']: raise ValueError('Source channel mismatch')
            values, data, warnings = projection(row, job, manifest)
            collision = frappe.db.get_value('Relay Message', {'provider_message_key': values['provider_message_key']}, 'name') if values['provider_message_key'] else None
            if not existing:
                # Upgrade earlier same-site imports only when their retained provenance
                # proves the exact site/name; provider identity alone is never enough.
                old_key = hashlib.sha256(('frappe_whatsapp_core:' + row.name).encode()).hexdigest()
                candidate = frappe.db.get_value('Relay Message', collision or {'source_key': old_key}, existing_fields, as_dict=True)
                if candidate and same_origin(candidate, manifest['source_site'], row.name): existing = candidate
            if existing and (existing.relay_contact != job.relay_contact or existing.channel != job.channel):
                raise ValueError('Identity already mapped to another conversation')
            if collision and (not existing or collision != existing.name):
                raise ValueError('Provider ID already belongs to a different source identity')
            if values['provider_message_key'] and values['provider_message_key'] in pending_providers:
                raise ValueError('Provider ID repeats within this source batch')
            if existing:
                if existing.business_name and not values['business_name']:
                    values.update(business_doctype=existing.business_doctype, business_name=existing.business_name, legacy_triage=0)
                elif existing.business_name and (existing.business_doctype, existing.business_name) != (values['business_doctype'], values['business_name']):
                    raise ValueError('Business mapping conflicts with imported history')
                prior = object_value(existing.legacy_data).get('row', {})
                if prior.get('modified') and row.get('modified') and str(prior['modified']) > str(row.modified):
                    raise ValueError('Stale source revision; newer imported history retained')
            name = existing.name if existing else sequential_name('message')
            attachments = media_for(row, job, name, data)
            if existing and not any(a['availability'] == 'available' for a in attachments):
                previous_media = object_value(existing.message_data).get('legacy_attachments', [])
                preserved = [a for a in previous_media if a.get('availability') == 'available']
                if preserved:
                    data['legacy_attachments'] = preserved + attachments
                    data.update(attachment=preserved[0]['attachment'], attachment_source=name)
            values.update(message_data=bundles.canonical(data), message_type=data['kind'])
            now = frappe.utils.now_datetime()
            if existing:
                if (existing.legacy_checksum == values['legacy_checksum'] and existing.message_data == values['message_data']
                        and existing.business_doctype == values['business_doctype'] and existing.business_name == values['business_name']):
                    job.skipped = (job.skipped or 0) + 1
                else:
                    frappe.db.set_value('Relay Message', name, values, update_modified=False)
                    report['updated'] += 1
            else:
                inserted.append(dict(values, name=name, owner=frappe.session.user, modified_by=frappe.session.user,
                    creation=now, modified=now, docstatus=0, idx=0))
                job.imported = (job.imported or 0) + 1
                if values['provider_message_key']: pending_providers.add(values['provider_message_key'])
            expected.append((row, name, values))
            report['types'][row.message_type] = report['types'].get(row.message_type, 0) + 1
            report['statuses'][values['status']] = report['statuses'].get(values['status'], 0) + 1
            report['attachment_bytes'] += sum(a.get('size', 0) for a in attachments if a['availability'] == 'available')
            report['unavailable_media'] += sum(a['availability'] != 'available' for a in attachments)
            for warning in warnings: report['mismatches'].append({'source': row.name, 'kind': 'content_review', 'detail': warning})
            for item in attachments:
                if item['availability'] != 'available': report['mismatches'].append({'source': row.name, 'kind': 'media', 'detail': item.get('reason', 'Source unavailable')})
        except ValueError as exc:
            report['mismatches'].append({'source': row.name, 'kind': 'mapping', 'detail': str(exc),
                                         'original': dict(row), 'sha256': bundles.checksum(row)})
        job.last_creation, job.last_source = bundles.order_key(row)
        report['checked'] += 1
    insert_rows('Relay Message', inserted)
    for row, name, values in expected:
        actual = frappe.db.get_value('Relay Message', name, ['source_key', 'legacy_checksum', 'legacy_data', 'message_data', 'status'], as_dict=True)
        identity_ok = actual.source_key == source_key(manifest['source_site'], row.name)
        payload_ok = actual.legacy_checksum == bundles.checksum(row) == bundles.checksum(object_value(actual.legacy_data).get('row'))
        report['identity_matches'] += int(identity_ok); report['payload_matches'] += int(payload_ok)
        if not identity_ok or not payload_ok or actual.status != values['status'] or object_value(actual.message_data) != object_value(values['message_data']):
            report['mismatches'].append({'source': row.name, 'kind': 'reconciliation', 'detail': 'Identity, original payload, projection or status differs'})
    if manifest.get('version') == 1:
        issue = {'source': manifest['source_conversation'], 'kind': 'source_format',
                 'detail': 'Version 1 bundles omit original fields and related history; re-export version 2 before cutover'}
        if issue not in report['mismatches']: report['mismatches'].append(issue)
    job.reconcile_report = bundles.canonical(report)
    return report


@frappe.whitelist(methods=['GET'])
def preview(name):
    job, manifest, endpoint = mapping(name)
    rows = source_rows(job)[:50]
    bundle = job.flags.get('legacy_bundle')
    attached = review = 0
    for row in rows:
        entries = bundle['files'].get(row.name, []) if bundle else bundles.related('File', {'attached_to_doctype': SOURCE, 'attached_to_name': row.name})
        attached += bool(any(item.get('availability', 'available') == 'available' for item in entries))
        _, _, _, warnings = converted(row)
        review += bool(warnings or not job.business_name or any(item.get('availability') == 'unavailable' for item in entries))
    return {'messages': len(rows), 'local_attachments': attached, 'review_required': review, 'status': job.status}


@frappe.whitelist(methods=['POST'])
def run_batch(name):
    require_access(configure=True)
    # Site-wide serialization prevents competing jobs from splitting one source identity.
    with frappe.cache.lock('relay-legacy-import', timeout=600):
        job, manifest, endpoint = mapping(name)
        if job.status == 'Completed':
            return {'status': job.status, 'imported': job.imported, 'skipped': job.skipped}
        if job.status == 'Draft':
            from relay_core.legacy_metadata import validate_mapping
            validate_mapping(job, manifest)
            job.source_site = manifest['source_site']; job.source_channel = manifest['source_channel']
            job.source_metadata = json.dumps(manifest.get('metadata', {}), ensure_ascii=False, indent=2, default=str)
            bundle = job.flags.get('legacy_bundle')
            if bundle:
                job.bundle_sha256 = bundle['sha256']; job.watermark = manifest.get('watermark')
                job.delta_since = manifest.get('since')
            else:
                job.watermark = str(frappe.db.sql('SELECT CURRENT_TIMESTAMP(6)')[0][0])
                newest = frappe.db.sql('SELECT creation,name FROM `tabWhatsApp Core Message` WHERE conversation=%s ORDER BY creation DESC,name DESC LIMIT 1', job.source_conversation, as_dict=True)
                if newest: job.upper_creation, job.upper_source = bundles.order_key(newest[0])
            job.status = 'Running'
        rows = source_rows(job)
        if not job.source_bundle and 'frappe_whatsapp_core' in frappe.get_installed_apps():
            from frappe_whatsapp_core.inbox import _attach_template_snapshots
            rendered = [frappe._dict(row.copy()) for row in rows]
            _attach_template_snapshots(rendered)
            manifest['rendered_content'] = {row.name: row.content for row in rendered}
        report = import_rows(job, manifest, rows[:50])
        if len(rows) <= 50:
            from relay_core.legacy_metadata import import_metadata, project_reactions
            import_metadata(job, manifest, report)
            job.source_metadata = json.dumps(manifest.get('metadata', {}), ensure_ascii=False, indent=2, default=str)
            project_reactions(job, report)
            job.status = 'Completed'
            job.reconcile_report = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        job.warnings = ('Restricted triage: business mapping is unresolved.\n' if not job.business_name else '') + '\n'.join(manifest.get('warnings', []))
        save_job(job); frappe.db.commit()
        return {'status': job.status, 'imported': job.imported, 'skipped': job.skipped, 'updated': report['updated'], 'mismatches': len(report['mismatches'])}
