"""Streaming archive media. No provider downloads, uploads, or File hooks."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import tempfile

import frappe

CHUNK = 1024 * 1024


class TargetDatabaseError(Exception):
    """Target transaction failure must never be reported as missing source media."""


def copy_stream(source, target):
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(CHUNK):
        target.write(chunk)
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


@contextmanager
def source_file(file, *, source_checked=False):
    """Only registered Files are eligible; never fetch arbitrary payload URLs.
    source_checked: the caller proved the File is kept on a message the user can read."""
    if not source_checked:
        file.check_permission('read')
    if file.get('custom_is_s3_uploaded') and file.get('custom_s3_key'):
        from frappe_s3_integration.s3_core import getS3Connection
        connection = getS3Connection()
        if connection.s3_settings.disable_s3_operations:
            raise OSError('Source S3 access is disabled')
        stream = connection.get_file_from_bucket(file.custom_s3_key, file.custom_s3_bucket_name)['Body']
    else:
        if not str(file.file_url).startswith(('/private/files/', '/files/')):
            raise OSError('External storage requires a streaming storage adapter')
        stream = open(file.get_full_path(), 'rb')
    try:
        yield stream
    finally:
        stream.close()


def attach(stream, metadata, message):
    """Stage in private storage, verify before linking, and bypass external File hooks."""
    directory = Path(frappe.get_site_path('private', 'files'))
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, prefix='.relay-import-', delete=False) as handle:
        temporary = Path(handle.name)
        try:
            digest, size = copy_stream(stream, handle)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    if digest != metadata['sha256'] or size != metadata['size']:
        temporary.unlink(missing_ok=True)
        raise ValueError('Attachment bytes/checksum mismatch')
    # Content addressed names permit crash recovery without overwriting unrelated files.
    filename = 'relay-archive-' + digest
    destination = directory / filename
    os.chmod(temporary, 0o600)
    os.replace(temporary, destination)
    key = hashlib.sha256((message + ':' + digest).encode()).hexdigest()
    name = 'relay-archive-' + key
    try:
        if not frappe.db.exists('File', name):
            frappe.get_doc(dict(doctype='File', name=name, file_name=Path(metadata['filename'].replace('\\', '/')).name,
                file_url='/private/files/' + filename, is_private=1, file_size=size,
                attached_to_doctype='Relay Message', attached_to_name=message,
                owner=frappe.session.user, creation=frappe.utils.now_datetime(), modified=frappe.utils.now_datetime(),
                modified_by=frappe.session.user)).db_insert()
    except Exception as exc:
        raise TargetDatabaseError('Could not register the imported File') from exc
    return {'attachment': name, 'attachment_source': message, 'sha256': digest, 'size': size,
            'filename': metadata['filename'], 'availability': 'available'}
