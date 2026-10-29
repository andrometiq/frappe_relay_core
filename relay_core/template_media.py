"""Header media of a WhatsApp template send: an uploaded file's Hub media id, or a public HTTPS link."""
import base64
import binascii
import ipaddress
import mimetypes
import re
from urllib.parse import urlsplit

import frappe
from relay_core.business_access import document_name

from relay_core.bulk_sheet import media_url
from relay_core.channels import channel as channel_definition

MAX_BYTES = 4 * 1024 * 1024
HEADER_KINDS = {'image': 'photo', 'video': 'video', 'document': 'document'}  # Meta header type -> channel media kind.
PRIVATE_SUFFIXES = ('.localhost', '.local', '.internal', '.intranet', '.lan', '.home.arpa')


def public_link(value):
    """The link when it is HTTPS on a public host. Meta fetches it, so internal names and addresses are refused."""
    try:
        media_url(value if isinstance(value, str) else '')
    except ValueError:
        frappe.throw('Media needs an HTTPS link without credentials')
    host = urlsplit(value).hostname.rstrip('.').lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    last = host.rsplit('.', 1)[-1]
    if address and not address.is_global or not address and (
            '.' not in host or host.endswith(PRIVATE_SUFFIXES) or last.isdigit() or last.startswith('0x')):
        frappe.throw('Media link must point to a public host')
    return value


def plain_filename(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 120 or any(ord(c) < 32 for c in value)
            or any(c in value for c in '/\\"')):
        frappe.throw('Use a plain file name of at most 120 characters')
    return value


def check_header(components):
    """Each header image, video or document holds one uploaded media id or one public HTTPS link; frappe.throw refuses others."""
    for component in components:
        if not isinstance(component, dict) or str(component.get('type')).lower() != 'header':
            continue
        for parameter in component.get('parameters') or []:
            kind = parameter.get('type') if isinstance(parameter, dict) else None
            if kind not in HEADER_KINDS:
                continue
            media = parameter.get(kind)
            if not isinstance(media, dict) or set(media) - {'id', 'link', 'filename'} or len({'id', 'link'} & set(media)) != 1:
                frappe.throw('Give the header file as one upload or one link')
            if 'id' in media and not re.fullmatch(r'[0-9]{1,100}', str(media['id'])):
                frappe.throw('Upload the header file again')
            if 'link' in media:
                public_link(media['link'])
            if 'filename' in media:
                if kind != 'document':
                    frappe.throw('Only a document header has a file name')
                plain_filename(media['filename'])


@frappe.whitelist(methods=['POST'])
def upload(channel, media_type, filename, content_base64):
    """Hub media id of a header file, uploaded through the WhatsApp number that sends the template."""
    document_name(channel)
    from relay_core.document_sends import upload as hub_upload
    from relay_core.hub import HubError
    from relay_core.hub_channels import is_current
    from relay_core.permissions import require_access
    from relay_core.settings import value as connection_value
    from relay_core.whatsapp import failure_message
    require_access()
    if media_type not in HEADER_KINDS:
        frappe.throw('Choose an image, video or document header')
    sender = frappe.get_doc('Relay Channel', channel)
    sender.check_permission('read')
    if sender.channel != 'WhatsApp' or not is_current(sender, connection_value('relay_hub_account')):
        frappe.throw('The channel is unavailable', frappe.PermissionError)
    plain_filename(filename)
    mime_type = mimetypes.guess_type(filename)[0]
    if mime_type not in channel_definition('WhatsApp').features['media'][HEADER_KINDS[media_type]]:
        frappe.throw(f'This file type is not accepted for this {media_type} header')
    if not isinstance(content_base64, str) or len(content_base64) > ((MAX_BYTES + 2) // 3) * 4:
        frappe.throw('The file must be at most 4 MiB')
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error):
        frappe.throw('Invalid file data')
    if not 1 <= len(raw) <= MAX_BYTES:
        frappe.throw('The file must hold 1 byte to 4 MiB')
    try:
        media_id = hub_upload(sender, filename, raw, media_type, mime_type)
    except (HubError, ValueError) as error:
        frappe.throw(failure_message(error))
    return {'id': media_id, 'filename': filename, 'size': len(raw)}
