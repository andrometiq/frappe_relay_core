"""Received WhatsApp media keeps a private File on its Relay Message, because Meta drops it after
attachments.WHATSAPP_MEDIA_DAYS. attachments.read and messaging.sticker serve that File first."""
import json
import mimetypes
import re

import frappe
from frappe.utils import add_to_date, cint, now_datetime
from relay_core import file_limits, locks
from relay_core.attachments import is_media_expired, save_attachment, whatsapp_attachment, whatsapp_media
from relay_core.hub import HubError
from relay_core.messaging import object_value, sticker_bytes, STICKER_TYPES

KINDS = ('image', 'video', 'audio', 'document', 'sticker')
TIMEOUT = 300
# A failed or lost job is retried by recover() for this long; store_recent_whatsapp_media covers the rest.
RECOVER_DAYS = 1
BATCH = 500


def is_storable(doc) -> bool:
    """Whether doc is live received WhatsApp media that has no kept copy yet."""
    if doc.direction != 'Incoming' or doc.get('legacy_source') or doc.message_type not in KINDS:
        return False
    data = object_value(doc.message_data or {})
    media = data.get('media') or {}
    size = media.get('file_size') or 0
    return not data.get('attachment') and bool(media.get('id')) and size <= file_limits.get_max_bytes()


def on_message(doc, method=None):
    """Queue the copy right after projection commits: Meta keeps the media for only a few days."""
    if object_value(doc.provider_context or {}).get('provider') == 'WhatsApp' and is_storable(doc):
        name = doc.name
        frappe.db.after_commit.add(lambda: enqueue(name))  # No Redis call inside the projection transaction.


def enqueue(message):
    frappe.enqueue('relay_core.received_media.store', message=message, queue='long', timeout=TIMEOUT,
                   job_id='relay-media-store:' + message, deduplicate=True)


def store(message):
    """Download the media once and keep it on the message. Safe to repeat: a kept copy is never replaced."""
    with locks.lock('relay-media-store:' + message, timeout=TIMEOUT, blocking_timeout=60):
        frappe.db.commit()  # A waiter must not keep the snapshot from before the lock.
        source = frappe.get_doc('Relay Message', message)
        if not is_storable(source) or is_media_expired(source):
            return None
        try:
            filename, raw = download(source, frappe.get_doc('Relay Channel', source.channel))
            if error := file_limits.size_error(len(raw), file_limits.get_max_bytes(), 'The media'):
                raise ValueError(error)
        except (HubError, ValueError, frappe.ValidationError) as error:
            # recover() tries again while Meta keeps the media.
            frappe.logger('relay_core').warning(f'Received media {message} was not kept: {str(error)[:300]}')
            return None
        file = keep(source, filename, raw)
        frappe.db.commit()
        return file


def download(source, channel):
    """The file name and bytes of the message's media, downloaded through the Hub."""
    data = object_value(source.message_data or {})
    if source.message_type == 'sticker':
        raw, mime = sticker_bytes(whatsapp_media(source, channel, data['media']['id'], sticker=True))
        return 'sticker.' + STICKER_TYPES[mime], raw
    raw, mime, filename = whatsapp_attachment(source, channel, data['media'])
    return file_name(filename, mime.split(';')[0], source.message_type), raw


def file_name(filename, mime, kind):
    """A plain file name whose extension gives the media type back when it is served."""
    name = re.sub(r'[\x00-\x1f/\\"]', '_', filename or '').strip()[:100] or 'whatsapp-' + kind
    extension = mimetypes.guess_extension(mime)
    return name + extension if extension and mimetypes.guess_type(name)[0] != mime else name


def keep(source, filename, raw):
    """Attach raw to the message and record it where attachments.read looks first."""
    frappe.db.get_value('Relay Message', source.name, 'name', for_update=True)
    data = object_value(frappe.db.get_value('Relay Message', source.name, 'message_data') or {})
    if data.get('attachment'):
        return None
    file = save_attachment(filename, raw, source.name)
    data.update(attachment=file.name, attachment_source=source.name)
    frappe.db.set_value('Relay Message', source.name, 'message_data', json.dumps(data, ensure_ascii=False), update_modified=False)
    return file


def get_missing(days):
    """Live received WhatsApp media of the last `days` days that Meta still keeps and Relay has not copied."""
    channels = frappe.get_all('Relay Channel', filters={'channel': 'WhatsApp'}, pluck='name')
    if not channels:
        return []
    rows = frappe.get_all('Relay Message', filters={'direction': 'Incoming', 'channel': ['in', channels],
        'message_type': ['in', KINDS], 'legacy_source': ['is', 'not set'],
        'creation': ['>=', add_to_date(now_datetime(), days=-cint(days))]},
        fields=['name', 'direction', 'message_type', 'message_data', 'legacy_source', 'sent_at', 'creation'],
        order_by='creation asc', limit_page_length=BATCH)
    return [row.name for row in rows if is_storable(row) and not is_media_expired(row)]


def store_recent_whatsapp_media(days=7, dry_run=1):
    """Queue the copy of received WhatsApp media from the last `days` days that has none, at most BATCH per run.

    bench --site <site> execute relay_core.received_media.store_recent_whatsapp_media --kwargs "{'days': 7, 'dry_run': 0}"
    """
    names = get_missing(days)
    if not cint(dry_run):
        for name in names:
            enqueue(name)
    summary = {'count': len(names), 'names': names, 'queued': not cint(dry_run)}
    frappe.logger('relay_core').info(f'Received media without a kept copy in {cint(days)} days: {len(names)}, queued: {summary["queued"]}')
    return summary


def recover():
    """Retry copies whose job was lost or failed."""
    store_recent_whatsapp_media(days=RECOVER_DAYS, dry_run=0)
