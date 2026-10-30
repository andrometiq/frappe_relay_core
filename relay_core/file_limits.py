"""The one attachment size limit of Relay, lowered per media kind where a channel provider accepts less."""
import frappe
from frappe.utils import cint
from relay_core.channels.contract import MEGABYTE

MAX_BYTES = 10 * MEGABYTE
# Frappe limits every request body that is not upload_file to site config max_file_size, or 25 MB.
DEFAULT_REQUEST_BYTES = 25 * MEGABYTE
REQUEST_OVERHEAD_BYTES = 64 * 1024


def encoded_length(size: int) -> int:
    """Length of the base64 text of size bytes."""
    return (size + 2) // 3 * 4


def get_max_bytes() -> int:
    """Largest attachment: the site file size limit, what a base64 request body can carry, and at most 10 MB."""
    from frappe.core.api.file import get_max_file_size
    request_bytes = cint(frappe.conf.get('max_file_size')) or DEFAULT_REQUEST_BYTES
    return min(get_max_file_size(), (request_bytes - REQUEST_OVERHEAD_BYTES) * 3 // 4, MAX_BYTES)


def get_media_max_bytes(channel_name: str, kind: str) -> int:
    """Largest attachment of one media kind, such as 'photo', on a channel."""
    from relay_core.channels import channel
    provider_limit = (channel(channel_name).features['max_media_bytes'] or {}).get(kind)
    largest = get_max_bytes()
    return min(largest, provider_limit) if provider_limit else largest


def size_label(size: int) -> str:
    if size >= MEGABYTE:
        return f'{round(size / MEGABYTE, 1):g} MB'
    if size >= 1024:
        return f'{round(size / 1024):g} KB'
    return f'{size} bytes'


def size_error(size: int, limit: int, subject: str = 'The file') -> str:
    """The reason size is outside 1 byte to limit, or an empty text."""
    if size < 1:
        return f'{subject} is empty'
    if size > limit:
        return f'{subject} must be at most {size_label(limit)}'
    return ''
