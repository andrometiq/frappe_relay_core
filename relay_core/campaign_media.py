"""Private template header files, matched before a sheet row can become Pending."""
import json
import mimetypes
import os
import stat
import zipfile
from collections import defaultdict

import frappe
from frappe.exceptions import DoesNotExistError, PermissionError, ValidationError

from relay_core.bulk_sheet import sheet_phone
from relay_core.channels import channel
from relay_core.file_limits import get_media_max_bytes, size_error
from relay_core.template_media import HEADER_KINDS, plain_filename

MAX_FILES = 100000
ZIP_MAX_BYTES = 200 * 1024 * 1024
ZIP_MAX_FILES = 10000
SHEETS = ('.xlsx', '.csv', '.tsv')


def zip_contents(path):
    """Bounded, flat archive contents. Never extract archive paths to the filesystem."""
    try:
        if os.path.getsize(path) > ZIP_MAX_BYTES:
            raise ValueError('ZIP must be at most 200 MiB, including expanded files')
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > ZIP_MAX_FILES:
                raise ValueError('ZIP must contain at most 10000 entries')
            if sum(item.file_size for item in entries) > ZIP_MAX_BYTES:
                raise ValueError('ZIP must be at most 200 MiB, including expanded files')
            kept, names = [], set()
            allowed = {mime for kind in HEADER_KINDS.values()
                       for mime in channel('WhatsApp').features['media'][kind]}
            for item in entries:
                parts = item.filename.replace('\\', '/').split('/')
                if (item.filename.startswith(('/', '\\')) or '..' in parts or
                        any(':' in part or '\x00' in part for part in parts) or
                        stat.S_ISLNK(item.external_attr >> 16)):
                    raise ValueError('ZIP contains an unsafe path or symbolic link')
                if item.is_dir() or any(part.startswith('.') or part == '__MACOSX' for part in parts):
                    continue
                name = parts[-1]
                if not name or len(name) > 120 or any(ord(c) < 32 or c == '"' for c in name):
                    raise ValueError('ZIP file names must be plain names of at most 120 characters')
                if name.casefold() in names:
                    raise ValueError('ZIP contains duplicate file names after folders are flattened')
                names.add(name.casefold())
                if not name.lower().endswith(SHEETS) and mimetypes.guess_type(name)[0] not in allowed:
                    raise ValueError('ZIP may contain only a sheet and WhatsApp image, video or document files')
                if item.flag_bits & 1:
                    raise ValueError('Password-protected ZIP files are not supported')
                kept.append((item, name))
            sheets = [name for _, name in kept if name.lower().endswith(SHEETS)]
            if len(sheets) != 1:
                raise ValueError('ZIP must contain exactly one .xlsx, .csv or .tsv sheet')
            result = []
            for item, name in kept:
                with archive.open(item) as handle:
                    raw = handle.read(min(item.file_size, ZIP_MAX_BYTES) + 1)
                if len(raw) != item.file_size:
                    raise ValueError('ZIP contents do not match their declared size')
                result.append((name, raw))
            return sheets[0], result
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise ValueError('This ZIP could not be read. Create a new ZIP and try again.') from exc


def unpack(path, campaign, media_type):
    """(sheet file URL, dynamic header attachment or None) of a campaign ZIP. A header file that is too
    large or unreadable is not stored; it is kept as rejected, so only its row fails validation."""
    from frappe.utils.file_manager import save_file
    from pypdf.errors import PyPdfError
    sheet_name, contents = zip_contents(path)
    limit = get_media_max_bytes('WhatsApp', HEADER_KINDS[media_type]) if media_type else 0
    sheet_url, files, rejected = None, [], []
    for filename, raw in contents:
        if filename == sheet_name:
            sheet_url = save_file(filename, raw, 'Relay Campaign', campaign, is_private=1).file_url
            continue
        if not media_type:
            continue
        if error := size_error(len(raw), limit, 'Header attachment'):
            rejected.append({'filename': filename, 'reason': error})
            continue
        try:
            saved = save_file(filename, raw, 'Relay Campaign', campaign, is_private=1)
        except (PyPdfError, ValidationError):  # Frappe parses every PDF; a damaged or unsafe one is refused.
            rejected.append({'filename': filename, 'reason': f'Wrong file content for {media_type} header'})
            continue
        files.append({'file_url': saved.file_url, 'filename': filename})
    attachment = {'mode': 'dynamic', 'files': files, **({'rejected': rejected} if rejected else {})}
    return sheet_url, attachment if files or rejected else None


def check_attachment(value, fields):
    if value is None:
        return None  # Existing API callers may still map HTTPS header URLs.
    if (not isinstance(value, dict) or not {'mode', 'files'} <= set(value) <= {'mode', 'files', 'rejected'}
            or value.get('mode') not in ('static', 'dynamic')
            or not any(field['key'] == 'header_media' for field in fields)):
        raise ValueError('Choose a header attachment mode')
    files, rejected = value['files'], check_rejected(value)
    if (not isinstance(files, list) or len(files) > MAX_FILES or not files and not rejected
            or value['mode'] == 'static' and len(files) != 1):
        raise ValueError('Choose one static file or multiple contact files')
    for item in files:
        if (not isinstance(item, dict) or set(item) != {'file_url', 'filename'}
                or not isinstance(item['file_url'], str) or not item['file_url'].startswith('/private/files/')
                or len(item['file_url']) > 2048):
            raise ValueError('Header attachments must be private uploaded files')
        plain_filename(item['filename'])
        if item['filename'].lower().endswith('.zip'):
            raise ValueError('ZIP archives are not supported. Select the individual files.')
    return value


def check_rejected(value):
    """ZIP files that unpack() did not store, each with the reason its row fails."""
    from relay_core.bulk_campaigns import friendly_reason
    rejected = value.get('rejected', [])
    if not isinstance(rejected, list) or len(rejected) > MAX_FILES or rejected and value['mode'] != 'dynamic':
        raise ValueError('Header attachments must be private uploaded files')
    for item in rejected:
        if (not isinstance(item, dict) or set(item) != {'filename', 'reason'} or not item['reason']
                or friendly_reason(item['reason']) != item['reason']):
            raise ValueError('Header attachments must be private uploaded files')
        plain_filename(item['filename'])
    return rejected


def checked_file(item, media_type):
    from relay_core.bulk_campaigns import uploaded_file
    file = uploaded_file(item['file_url'])  # File read permission applies to every reference.
    if not file.is_private or not str(file.file_url).startswith('/private/files/'):
        raise ValueError('Header attachments must stay private')
    mime = mimetypes.guess_type(file.file_name or '')[0]
    if (mime not in channel('WhatsApp').features['media'][HEADER_KINDS[media_type]]
            or mimetypes.guess_type(item['filename'])[0] != mime):
        raise ValueError(f'Wrong file type for {media_type} header')
    limit = get_media_max_bytes('WhatsApp', HEADER_KINDS[media_type])
    if error := size_error(os.path.getsize(file.get_full_path()), limit, 'Header attachment'):
        raise ValueError(error)
    with open(file.get_full_path(), 'rb') as handle:
        prefix = handle.read(1024)
    if not matches_format(prefix, mime):
        raise ValueError(f'Wrong file content for {media_type} header')
    return file, mime


def matches_format(prefix, mime):
    """Check container signatures as well as extensions; archives are never extracted."""
    signatures = {'image/png': b'\x89PNG\r\n\x1a\n', 'image/jpeg': b'\xff\xd8\xff',
                  'application/pdf': b'%PDF-', 'application/msword': b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',
                  'application/vnd.ms-excel': b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',
                  'application/vnd.ms-powerpoint': b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'}
    if mime in signatures:
        return prefix.startswith(signatures[mime])
    if mime == 'video/mp4':
        return prefix[4:8] == b'ftyp'
    if mime.startswith('application/vnd.openxmlformats-officedocument.'):
        return prefix.startswith(b'PK\x03\x04')
    if mime == 'text/plain':
        return b'\0' not in prefix and not prefix.startswith((b'PK\x03\x04', b'MZ'))
    return False


def resolve(attachment, media_type, numbers, region, issues=None):
    """Number -> (file reference, problem), using the sheet's region and mobile rules."""
    files = []
    for item in attachment['files']:
        try:
            checked_file(item, media_type)
            problem = None
        except ValueError as exc:
            problem = str(exc)
        except (OSError, DoesNotExistError, PermissionError, ValidationError):
            problem = 'Header attachment unavailable'
        files.append((item['filename'], item, problem))
    files += [(item['filename'], None, item['reason']) for item in attachment.get('rejected', [])]
    if issues is not None:
        for filename, _, problem in files:
            unused = (attachment['mode'] == 'dynamic' and
                      sheet_phone(os.path.splitext(filename)[0], region) not in numbers)
            if problem or unused:
                issues.append({'filename': filename, 'reason': problem or 'No matching mobile number in the sheet'})
    if attachment['mode'] == 'static':
        _, item, problem = files[0]
        return {number: (item, problem) for number in numbers}
    matches = defaultdict(list)
    for filename, item, problem in files:
        number = sheet_phone(os.path.splitext(filename)[0], region)
        if number in numbers:
            matches[number].append((item, problem))
    return {number: (matches[number][0] if len(matches[number]) == 1 else
                     (None, 'Duplicate header attachments' if matches[number] else 'Missing header attachment'))
            for number in numbers}


def sent_header(source, campaign):
    """(file name, bytes) of the header file the campaign row of `source` sent, or None when the
    campaign sent no uploaded header. The caller has checked the source, so File sharing rules do
    not apply; the file must be the one the row named and one of that campaign's header files."""
    from relay_core.bulk_campaigns import RECIPIENT, header_type
    doc = frappe.db.get_value('Relay Campaign', campaign, ['channel', 'column_map', 'arguments'], as_dict=True)
    attachment = json.loads(doc.column_map or '{}').get('header_attachment') if doc else None
    row = frappe.db.get_value(RECIPIENT, {'name': source.source_key, 'campaign': campaign},
                              ['destination', 'arguments'], as_dict=True) if attachment else None
    if not row:
        return None
    item = json.loads(row.arguments or '{}').get('values', {}).get('header_media')
    files = {(entry['file_url'], entry['filename']) for entry in attachment['files']}
    if (doc.channel != source.channel or row.destination != source.sender_endpoint
            or not isinstance(item, dict) or (item.get('file_url'), item.get('filename')) not in files):
        raise PermissionError('Attachment belongs to another campaign')
    name = frappe.db.get_value('File', {'file_url': item['file_url'], 'is_private': 1}, 'name')
    if not name:
        raise DoesNotExistError('Header attachment unavailable')
    file = frappe.get_doc('File', name)
    path = file.get_full_path()
    if not os.path.isfile(path):
        raise DoesNotExistError('Header attachment unavailable')
    limit = get_media_max_bytes('WhatsApp', HEADER_KINDS[header_type(doc)])
    if error := size_error(os.path.getsize(path), limit, 'Header attachment'):
        raise ValidationError(error)
    return item['filename'], file.get_content()
