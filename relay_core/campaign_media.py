"""Private template header files, matched before a sheet row can become Pending."""
import mimetypes
import os
from collections import defaultdict

from frappe.exceptions import DoesNotExistError, PermissionError, ValidationError

from relay_core.bulk_sheet import sheet_phone
from relay_core.channels import channel
from relay_core.template_media import HEADER_KINDS, MAX_BYTES, plain_filename

MAX_FILES = 100000


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


def resolve(attachment, media_type, numbers, region):
    """Number -> (file reference, problem), using the sheet's region and mobile rules."""
    files = []
    for item in attachment['files']:
        try:
            checked_file(item, media_type)
            problem = None
        except (ValueError, OSError) as exc:
            problem = str(exc)
        except (DoesNotExistError, PermissionError, ValidationError):
            problem = 'Header attachment unavailable'
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
