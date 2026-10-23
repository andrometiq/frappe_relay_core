"""Portable history segments with streaming media and creation/name cursors."""
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import zipfile

import frappe
from relay_core.permissions import require_access
from relay_core.legacy_media import copy_stream, source_file

PAGE = 500
# JSON is bounded; attachment bytes are streamed, never subject to the viewer limit.
MAX_JSON = 64 * 1024 * 1024


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def checksum(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def order_key(row):
    return str(row.get('creation') or ''), row['name']


def rows(conversation, after=None, upper=None, since=None, until=None, limit=PAGE + 1):
    conditions = ['conversation=%(conversation)s']
    values = dict(conversation=conversation)
    for key, pair, operator in [('after', after, '>'), ('upper', upper, '<=')]:
        if pair:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2 or any(not isinstance(value, str) or not value for value in pair):
                raise ValueError('Use the creation/name cursor returned by the exporter')
            conditions.append(f'(creation, name) {operator} (%({key}_creation)s, %({key}_name)s)')
            values.update({key + '_creation': pair[0], key + '_name': pair[1]})
    if since:
        conditions.append('modified >= %(since)s'); values['since'] = since
    if until:
        conditions.append('modified <= %(until)s'); values['until'] = until
    values['limit'] = limit
    return frappe.db.sql('SELECT * FROM `tabWhatsApp Core Message` WHERE ' + ' AND '.join(conditions)
        + ' ORDER BY creation, name LIMIT %(limit)s', values, as_dict=True)


def related(doctype, filters):
    if not frappe.db.exists('DocType', doctype):
        return []
    return frappe.get_all(doctype, filters=filters, fields=['*'], limit_page_length=0)


def describe(conversation):
    old = frappe.get_doc('WhatsApp Core Conversation', conversation); old.check_permission('read')
    identity = frappe.get_doc('WhatsApp Core Identity', old.remote_identity); identity.check_permission('read')
    channel = frappe.get_doc('WhatsApp Core Channel', old.channel); channel.check_permission('read')
    metadata = {'timezone': frappe.utils.get_system_timezone(),
        'conversation': old.as_dict(), 'identity': identity.as_dict(), 'channel': channel.as_dict(),
        'identity_links': related('WhatsApp Core Identity Link', {'identity': identity.name}),
        'party_bindings': related('WhatsApp Core Party Binding', {'identity': identity.name}),
        'hub_accounts': related('WhatsApp Core Hub Account', {'channel': old.channel})}
    for key, dt in [('staff_reads', 'Message Read'), ('conversation_reads', 'Conversation Read'),
                    ('notes', 'Internal Comment'), ('topics', 'Conversation Topic')]:
        metadata[key] = related('WhatsApp Core ' + dt, {'conversation': conversation})
    metadata['topic_messages'] = related('WhatsApp Core Topic Message',
        {'topic': ['in', [row.name for row in metadata['topics']]]}) if metadata['topics'] else []
    return {'format': 'relay-legacy-history', 'version': 2, 'source_site': frappe.local.site,
        'source_conversation': conversation, 'source_channel': old.channel,
        'endpoint': identity.normalized_value, 'identifier_type': identity.identifier_type,
        'metadata': metadata, 'attachments': {}, 'warnings': []}


def export_conversation(conversation, destination, after=None, *, upper=None, since=None, watermark=None, frozen=False):
    """Read-only export. Carry next/upper/watermark through every segment of a pass.

    For a live cutover, follow a snapshot with modified >= its watermark (inclusive).
    After freezing all source writers, use frozen=True for every final segment.
    That pass ignores modified: legacy sends and media caching do not advance it.
    Caller may hold a consistent read-only DB transaction across the entire site.
    """
    require_access(configure=True)
    manifest = describe(conversation)
    watermark = watermark or str(frappe.db.sql('SELECT CURRENT_TIMESTAMP(6)')[0][0])
    if not upper:
        newest = frappe.db.sql('SELECT creation,name FROM `tabWhatsApp Core Message` WHERE conversation=%s '
            'ORDER BY creation DESC,name DESC LIMIT 1', conversation, as_dict=True)
        upper = order_key(newest[0]) if newest else None
    if frozen:
        since = None
    selected = rows(conversation, after, upper, since, None if frozen else watermark)
    more = len(selected) > PAGE; selected = selected[:PAGE]
    manifest.update(count=len(selected), next=order_key(selected[-1]) if more else None,
        upper=upper, watermark=watermark, since=since, frozen=frozen)
    raw = canonical(selected).encode()
    if len(raw) > MAX_JSON:
        raise ValueError('Message JSON segment exceeds 64 MiB')
    manifest['messages_sha256'] = hashlib.sha256(raw).hexdigest()
    # Rendering is derived evidence; never mutate the complete original row.
    if 'frappe_whatsapp_core' in frappe.get_installed_apps():
        from frappe_whatsapp_core.inbox import _attach_template_snapshots
        rendered = [frappe._dict(row.copy()) for row in selected]
        _attach_template_snapshots(rendered)
        manifest['rendered_content'] = {row.name: row.content for row, original in zip(rendered, selected)
            if row.content != original.content}
    target = Path(destination); target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as handle:
        with zipfile.ZipFile(handle, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            archive.writestr('messages.json', raw)
            for row in selected:
                files = related('File', {'attached_to_doctype': 'WhatsApp Core Message', 'attached_to_name': row.name})
                entries = manifest['attachments'][row.name] = []
                for record in files:
                    entry = {'source_file': record.name, 'filename': record.file_name, 'source': dict(record)}
                    entries.append(entry)
                    path = 'files/' + checksum([row.name, record.name])
                    try:
                        with source_file(frappe.get_doc('File', record.name)) as source, archive.open(path, 'w', force_zip64=True) as output:
                            digest, size = copy_stream(source, output)
                        entry.update(path=path, sha256=digest, size=size, availability='available')
                    except Exception as exc:
                        # Keep the exact File metadata, with a safe reason rather than credentials/URLs in errors.
                        entry.update(availability='unavailable', reason=type(exc).__name__)
                        manifest['warnings'].append(row.name + ': source file unavailable (' + type(exc).__name__ + ')')
            manifest['metadata_sha256'] = checksum(manifest['metadata'])
            archive.writestr('manifest.json', canonical(manifest))
    return {key: manifest[key] for key in ('count', 'next', 'upper', 'watermark', 'warnings')}


def decode(source):
    """Validate a path or bytes. Keep compressed attachments on disk until requested."""
    archive_source = io.BytesIO(source) if isinstance(source, bytes) else source
    try:
        with zipfile.ZipFile(archive_source) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or len({e.filename for e in entries}) != len(entries):
                raise ValueError('Duplicate or excessive archive entries')
            if any(e.filename not in ('manifest.json', 'messages.json') and not re.fullmatch(r'files/[a-f0-9]{64}', e.filename) for e in entries):
                raise ValueError('Unsafe archive path')
            for path in ('manifest.json', 'messages.json'):
                if archive.getinfo(path).file_size > MAX_JSON:
                    raise ValueError('Oversize JSON')
            manifest = json.loads(archive.read('manifest.json')); raw = archive.read('messages.json'); records = json.loads(raw)
            if manifest.get('format') != 'relay-legacy-history' or manifest.get('version') not in (1, 2):
                raise ValueError('Unknown format')
            if hashlib.sha256(raw).hexdigest() != manifest.get('messages_sha256'):
                raise ValueError('Message checksum mismatch')
            if manifest.get('version') == 2 and checksum(manifest.get('metadata')) != manifest.get('metadata_sha256'):
                raise ValueError('Metadata checksum mismatch')
            if not isinstance(records, list) or len(records) > PAGE or len(records) != manifest.get('count'):
                raise ValueError('Invalid row count')
            for key in ('source_site', 'source_conversation', 'source_channel', 'endpoint'):
                if not isinstance(manifest.get(key), str) or not 1 <= len(manifest[key]) <= 200:
                    raise ValueError('Missing source identity')
            if manifest.get('identifier_type') not in ('Phone', 'BSUID', 'Group'):
                raise ValueError('Unknown identity type')
            names = set(); files = {}
            for row in records:
                if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not 1 <= len(row['name']) <= 140 or row['name'] in names:
                    raise ValueError('Invalid/duplicate source row')
                if row.get('conversation') != manifest['source_conversation'] or row.get('channel') != manifest['source_channel']:
                    raise ValueError('Source boundary mismatch')
                names.add(row['name'])
                metas = manifest.get('attachments', {}).get(row['name'], [])
                if isinstance(metas, dict): metas = [dict(metas, availability='available')]
                files[row['name']] = metas
                for meta in metas:
                    if meta.get('availability') != 'available': continue
                    if not re.fullmatch(r'files/[a-f0-9]{64}', meta.get('path', '')) or not re.fullmatch(r'[a-f0-9]{64}', meta.get('sha256', '')):
                        raise ValueError('Invalid attachment identity')
                    if not isinstance(meta.get('filename'), str) or len(meta['filename']) > 255:
                        raise ValueError('Invalid attachment filename')
                    size = archive.getinfo(meta['path']).file_size
                    if meta.get('size', size) != size: raise ValueError('Attachment size mismatch')
                    meta['size'] = size
        # Pin the whole segment, including media. Read in bounded chunks.
        handle = io.BytesIO(source) if isinstance(source, bytes) else open(source, 'rb')
        with handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        return {'manifest': manifest, 'rows': [frappe._dict(r) for r in sorted(records, key=order_key)],
                'files': files, 'source': source, 'sha256': digest}
    except (ValueError, TypeError, KeyError, zipfile.BadZipFile, UnicodeDecodeError, RuntimeError, NotImplementedError) as exc:
        frappe.throw('Legacy bundle is malformed: ' + str(exc))


@contextmanager
def open_attachment(bundle, meta):
    source = bundle['source']
    with zipfile.ZipFile(io.BytesIO(source) if isinstance(source, bytes) else source) as archive:
        with archive.open(meta['path']) as stream:
            yield stream


def load(file_name):
    require_access(configure=True)
    file = frappe.get_doc('File', file_name); file.check_permission('read')
    if not file.is_private or not str(file.file_url).startswith('/private/files/'):
        frappe.throw('Legacy bundles must be private local files')
    return decode(file.get_full_path())


@frappe.whitelist(methods=['GET'])
def details(file):
    manifest = load(file)['manifest']
    return {key: manifest.get(key) for key in ('source_site', 'source_conversation', 'count', 'next', 'watermark')}
