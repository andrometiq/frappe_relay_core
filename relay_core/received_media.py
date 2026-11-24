"""Received WhatsApp media keeps a private File on its Relay Message, because Meta drops it after
attachments.WHATSAPP_MEDIA_DAYS. attachments.read and messaging.sticker serve that File first."""
import json
import mimetypes
import re

import frappe
from frappe.utils import add_to_date, cint, now_datetime
from relay_core import file_limits, locks
from relay_core.attachments import MediaExpired, MediaRetry, is_media_expired, save_attachment, whatsapp_attachment, whatsapp_media
from relay_core.automation.service import KEPT_COPY_KEYS
from relay_core.hub import HubError
from relay_core.messaging import object_value, sticker_bytes, STICKER_TYPES

KINDS = ('image', 'video', 'audio', 'document', 'sticker')
TIMEOUT = 300
# A failed or lost job is retried by recover() for this long; backfill() covers the rest.
RECOVER_DAYS = 1
BATCH = 500
# Why the media can never be kept, such as its size; recover() does not download it again.
SKIPPED = 'media_store_skipped'


def is_storable(doc) -> bool:
    """Whether doc is live received WhatsApp media that has no kept copy yet."""
    if doc.direction != 'Incoming' or doc.get('legacy_source') or doc.message_type not in KINDS:
        return False
    data = object_value(doc.message_data or {})
    media = data.get('media') or {}
    size = media.get('file_size') or 0
    return (not data.get('attachment') and not data.get(SKIPPED) and bool(media.get('id'))
            and size <= file_limits.get_max_bytes())


def on_message(doc, method=None):
    """Queue the copy right after projection commits: Meta keeps the media for only a few days."""
    if object_value(doc.provider_context or {}).get('provider') == 'WhatsApp' and is_storable(doc):
        name = doc.name
        frappe.db.after_commit.add(lambda: enqueue(name))  # No Redis call inside the projection transaction.


def enqueue(message):
    frappe.enqueue('relay_core.received_media.store', message=message, queue='long', timeout=TIMEOUT,
                   job_id='relay-media-store:' + message, deduplicate=True)


def store(message, try_expired=False):
    """Download the media once and keep it on the message, and return the outcome: stored, expired, failed or
    skipped. Safe to repeat: a kept copy is never replaced. try_expired asks the Hub even after Meta's window."""
    with locks.lock('relay-media-store:' + message, timeout=TIMEOUT, blocking_timeout=60):
        frappe.db.commit()  # A waiter must not keep the snapshot from before the lock.
        source = frappe.get_doc('Relay Message', message)
        if not is_storable(source):
            return 'skipped'
        if is_media_expired(source) and not try_expired:
            return 'expired'
        try:
            filename, raw = download(source, frappe.get_doc('Relay Channel', source.channel))
            if error := file_limits.size_error(len(raw), file_limits.get_max_bytes(), 'The media'):
                raise ValueError(error)
        except (HubError, ValueError, frappe.ValidationError) as error:
            frappe.logger('relay_core').warning(f'Received media {message} was not kept: {str(error)[:300]}')
            # Only a busy or failed Hub is worth another try; recover() retries it while Meta keeps the media.
            if isinstance(error, (HubError, MediaRetry)):
                return 'failed'
            skip(message, str(error)[:140])
            frappe.db.commit()
            return 'expired' if isinstance(error, MediaExpired) else 'failed'
        file = keep(source, filename, raw)
        frappe.db.commit()
        return 'stored' if file else 'skipped'


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
    data = get_locked_data(source.name)
    if data.get('attachment'):
        return None
    file = save_attachment(filename, raw, source.name)
    set_data(source.name, dict(data, attachment=file.name, attachment_source=source.name))
    return file


def skip(message, reason):
    """Record why the media cannot be kept, unless a copy was kept meanwhile."""
    data = get_locked_data(message)
    if not data.get('attachment'):
        set_data(message, dict(data, **{SKIPPED: reason}))


def get_locked_data(message):
    frappe.db.get_value('Relay Message', message, 'name', for_update=True)
    return object_value(frappe.db.get_value('Relay Message', message, 'message_data') or {})


def set_data(message, data):
    frappe.db.set_value('Relay Message', message, 'message_data', json.dumps(data, ensure_ascii=False), update_modified=False)


def with_kept_copy(previous, edited):
    """Edited message_data that keeps the kept copy, or the skip reason, of the same media."""
    previous = object_value(previous or {})
    media_id = (previous.get('media') or {}).get('id')
    if not media_id or media_id != (edited.get('media') or {}).get('id'):
        return edited
    return dict(edited, **{key: previous[key] for key in KEPT_COPY_KEYS if key in previous})


def get_missing(days, limit=BATCH, include_expired=False):
    """Live received WhatsApp media of the last `days` days that Relay has not copied, oldest first: at most
    `limit` names (None for all), and only media Meta still keeps unless include_expired. Kept and skipped
    media are left out in SQL, so each run moves on."""
    channels = frappe.get_all('Relay Channel', filters={'channel': 'WhatsApp'}, pluck='name')
    if not channels:
        return []
    filters = [['direction', '=', 'Incoming'], ['channel', 'in', channels], ['message_type', 'in', KINDS],
               ['legacy_source', 'is', 'not set'], ['creation', '>=', add_to_date(now_datetime(), days=-cint(days))],
               ['message_data', 'not like', '%"attachment"%'], ['message_data', 'not like', f'%"{SKIPPED}"%']]
    names, start = [], 0
    while limit is None or len(names) < limit:
        rows = frappe.get_all('Relay Message', filters=filters, order_by='creation asc, name asc',
            fields=['name', 'direction', 'message_type', 'message_data', 'legacy_source', 'sent_at', 'creation'],
            limit_start=start, limit_page_length=BATCH)
        names += [row.name for row in rows if is_storable(row) and (include_expired or not is_media_expired(row))]
        if len(rows) < BATCH:
            break
        start += BATCH
    return names[:limit]


def recover():
    """Queue again, at most BATCH per run, copies of the last RECOVER_DAYS days whose job was lost or failed."""
    names = get_missing(RECOVER_DAYS)
    for name in names:
        enqueue(name)
    frappe.logger('relay_core').info(f'Received media copies queued again: {len(names)}')


def backfill(days=7, dry_run=0):
    """Copy now, one message at a time, received WhatsApp media of the last `days` days that has no kept copy.
    Media past Meta's window is still tried once. Safe to repeat; each message commits on its own.

    bench --site <site> execute relay_core.received_media.backfill --kwargs "{'days': 7, 'dry_run': 1}"
    """
    names = get_missing(days, limit=None, include_expired=True)
    if cint(dry_run):
        return {'candidates': len(names)}
    counts = dict.fromkeys(('stored', 'expired', 'failed', 'skipped'), 0)
    log = frappe.logger('relay_core')
    for name in names:
        try:
            outcome = store(name, try_expired=True)
        except Exception:
            frappe.db.rollback()
            log.exception(f'Received media backfill {name} failed')
            outcome = 'failed'
        counts[outcome] += 1
        log.info(f'Received media backfill {name}: {outcome}')
    log.info(f'Received media backfill of {cint(days)} days: {counts}')
    return counts
