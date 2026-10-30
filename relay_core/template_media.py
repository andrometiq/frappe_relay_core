"""Header media of a WhatsApp template send: an uploaded file's Hub media id, or a public HTTPS link."""
import base64
import binascii
import mimetypes
import re

import frappe
from relay_core.business_access import document_name

from relay_core.bulk_sheet import HEADER_KINDS, public_media_url
from relay_core.channels import channel as channel_definition
from relay_core.file_limits import encoded_length, get_media_max_bytes, size_error, size_label

UPLOADS = 'relay-template-media:'  # Hub media id -> the uploader's File and the sending channel.


def public_link(value):
    """The link when it is HTTPS on a public host. Meta fetches it, so internal names and addresses are refused."""
    try:
        return public_media_url(value if isinstance(value, str) else '')
    except ValueError as exc:
        frappe.throw(str(exc))


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
    limit = get_media_max_bytes('WhatsApp', HEADER_KINDS[media_type])
    if not isinstance(content_base64, str) or len(content_base64) > encoded_length(limit):
        frappe.throw(f'The file must be at most {size_label(limit)}')
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error):
        frappe.throw('Invalid file data')
    if error := size_error(len(raw), limit):
        frappe.throw(error)
    try:
        media_id = hub_upload(sender, filename, raw, media_type, mime_type)
    except (HubError, ValueError) as error:
        frappe.throw(failure_message(error))
    from frappe.utils.file_manager import save_file
    from relay_core.bulk_campaigns import MEDIA_DAYS
    file = save_file(filename, raw, None, None, is_private=1)
    frappe.cache.set_value(UPLOADS + media_id, {'file': file.name, 'channel': sender.name}, expires_in_sec=MEDIA_DAYS * 86400)
    return {'id': media_id, 'filename': filename, 'size': len(raw)}


def keep_header(result, kind, data):
    """Move the uploaded header file of a sent template onto its Relay Message, so the chat serves it from the site."""
    from relay_core.attachments import template_media
    template = data.get('arguments') if kind == 'whatsapp' else data if kind == 'template' else None
    media = template_media({'template': template}) if isinstance(template, dict) else None
    key = UPLOADS + str(media.get('id')) if media and result.get('action') else None
    upload = frappe.cache.get_value(key) if key else None
    channel = frappe.db.get_value('Relay Message Action', result['action'], 'target_channel') if isinstance(upload, dict) else None
    if not channel or upload['channel'] != channel:
        return None
    file = frappe.get_doc('File', upload['file'])
    if not file.is_private or file.attached_to_doctype or file.owner != frappe.session.user:
        return None
    from relay_core.document_sends import keep_copy
    if message := keep_copy(result, file.file_name, file.get_content()):
        file.delete(ignore_permissions=True)
        frappe.cache.delete_value(key)
    return message
