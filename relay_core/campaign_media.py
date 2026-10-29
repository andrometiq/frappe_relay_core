"""Private template header files, matched before a sheet row can become Pending."""
import mimetypes
import os
import stat
import zipfile
from collections import defaultdict

from frappe.exceptions import DoesNotExistError, PermissionError, ValidationError

from relay_core.bulk_sheet import sheet_phone
from relay_core.channels import channel
from relay_core.template_media import HEADER_KINDS, MAX_BYTES, plain_filename

MAX_FILES = 100000
ZIP_MAX_BYTES = 200 * 1024 * 1024
ZIP_MAX_FILES = 2000
SHEETS = ('.xlsx', '.csv', '.tsv')


def zip_contents(path):
    """Bounded, flat archive contents. Never extract archive paths to the filesystem."""
    try:
        if os.path.getsize(path) > ZIP_MAX_BYTES:
            raise ValueError('ZIP must be at most 200 MiB, including expanded files')
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > ZIP_MAX_FILES:
                raise ValueError('ZIP must contain at most 2000 entries')
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


def check_attachment(value, fields):
    if value is None:
        return None  # Existing API callers may still map HTTPS header URLs.
    if (not isinstance(value, dict) or set(value) != {'mode', 'files'}
            or value.get('mode') not in ('static', 'dynamic')
            or not any(field['key'] == 'header_media' for field in fields)):
        raise ValueError('Choose a header attachment mode')
    files = value['files']
    if (not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES
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


def checked_file(item, media_type):
    from relay_core.bulk_campaigns import uploaded_file
    file = uploaded_file(item['file_url'])  # File read permission applies to every reference.
    if not file.is_private or not str(file.file_url).startswith('/private/files/'):
        raise ValueError('Header attachments must stay private')
    mime = mimetypes.guess_type(file.file_name or '')[0]
    if (mime not in channel('WhatsApp').features['media'][HEADER_KINDS[media_type]]
            or mimetypes.guess_type(item['filename'])[0] != mime):
        raise ValueError(f'Wrong file type for {media_type} header')
    if not 1 <= os.path.getsize(file.get_full_path()) <= MAX_BYTES:
        raise ValueError('Header attachment must contain 1 byte to 4 MiB')
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
        if issues is not None:
            unused = (attachment['mode'] == 'dynamic' and
                      sheet_phone(os.path.splitext(item['filename'])[0], region) not in numbers)
            if problem or unused:
                issues.append({'filename': item['filename'], 'reason': problem or 'No matching mobile number in the sheet'})
        files.append((item, problem))
    if attachment['mode'] == 'static':
        item, problem = files[0]
        return {number: (item, problem) for number in numbers}
    matches = defaultdict(list)
    for item, problem in files:
        number = sheet_phone(os.path.splitext(item['filename'])[0], region)
        if number in numbers:
            matches[number].append((item, problem))
    return {number: (matches[number][0] if len(matches[number]) == 1 else
                     (None, 'Duplicate header attachments' if matches[number] else 'Missing header attachment'))
            for number in numbers}
