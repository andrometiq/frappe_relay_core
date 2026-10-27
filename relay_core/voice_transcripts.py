"""Received voice notes keep their transcript on the Relay Message."""
import json
import frappe
from relay_core import ai_features
from relay_core.automation.providers import ProviderError
from relay_core.automation.queue import after_message_commit
from relay_core.automation.service import message_hash

AUDIO_KINDS = ('audio', 'voice')
MAX_ATTEMPTS = 3


def configured_provider():
    """The site's speech-to-text provider, or None when it cannot transcribe."""
    name = frappe.db.get_single_value('Relay Settings', 'transcription_provider')
    if not name:
        return None
    provider = frappe.get_doc('Relay AI Provider', name)
    return provider if provider.enabled and provider.provider == 'OpenAI' else None


def lock(source):
    # Shared with reply inference and translation so one audio file is sent once.
    return frappe.cache.lock('relay-voice-' + message_hash(source), timeout=120, blocking_timeout=90)


def stored(source):
    row = frappe.db.get_value('Relay Message', source.name, ['transcript', 'transcript_details'], as_dict=True) or {}
    if not row.get('transcript'):
        return None, None
    details = row.transcript_details
    return row.transcript, json.loads(details) if isinstance(details, str) else details or {}


def create(source, provider, reserve=None):
    """Caller holds lock(source). Never call with a database row lock held."""
    from relay_core.attachments import read
    from relay_core.automation.multimodal import transcribe
    digest = message_hash(source)
    response = read(source.name)
    if reserve:
        reserve()
    text = transcribe(provider.model, provider.get_password('api_key'), response.get_data(), response.mimetype)
    details = {'provider': provider.provider, 'model': provider.model,
               'created_at': str(frappe.utils.now_datetime()), 'source_hash': digest}
    frappe.db.get_value('Relay Message', source.name, 'name', for_update=True)
    # An edit or revoke during the call must not receive the old audio's text.
    if message_hash(frappe.get_doc('Relay Message', source.name)) == digest:
        save(source, 'Completed', transcript=text, details=details)
    return text, details


def save(source, status, transcript='', details=None):
    frappe.db.set_value('Relay Message', source.name, {'transcript': transcript, 'transcript_status': status,
        'transcript_details': json.dumps(details or {}, ensure_ascii=False)}, update_modified=False)
    from relay_core.realtime import changed
    changed(source)


@after_message_commit
def on_message(doc, method=None):
    if doc.direction != 'Incoming' or doc.get('legacy_source') or doc.message_type not in AUDIO_KINDS or not ai_features.is_enabled():
        return
    if frappe.db.get_value('Relay Message', doc.name, 'transcript_status'):
        return
    if not configured_provider():
        save(doc, 'Unavailable', details={'reason': 'No voice transcription provider is configured'})
        return
    save(doc, 'Pending')
    frappe.enqueue('relay_core.voice_transcripts.process', message=doc.name, queue='long', timeout=300,
                   job_id='relay-voice-transcript:' + doc.name, deduplicate=True, enqueue_after_commit=True)


@ai_features.when_enabled
def process(message):
    actor = frappe.session.user
    frappe.set_user('Administrator')
    try:
        source = frappe.get_doc('Relay Message', message)
        if source.transcript_status != 'Pending':
            return
        provider = configured_provider()
        if not provider:
            save(source, 'Unavailable', details={'reason': 'No voice transcription provider is configured'})
            return
        details = json.loads(source.transcript_details or '{}')
        attempts = int(details.get('attempts', 0)) + 1
        if attempts > MAX_ATTEMPTS:
            save(source, 'Failed', details={'reason': 'Transcription attempt limit reached', 'attempts': attempts - 1})
            return
        # Count the attempt first: a crash or Hub outage is retried by recover().
        save(source, 'Pending', details={'attempts': attempts}); frappe.db.commit()
        try:
            with lock(source):
                frappe.db.commit()  # A waiter must not keep the snapshot from before the lock.
                if not stored(source)[0]:
                    create(source, provider)
        except (ValueError, ProviderError, frappe.ValidationError) as error:
            frappe.db.rollback()
            save(source, 'Failed', details={'reason': str(error)[:300] or 'Transcription could not be completed', 'attempts': attempts})
        frappe.db.commit()
    finally:
        frappe.set_user(actor)


def recover():
    """Retry transcripts whose job was lost or hit a Hub outage."""
    stale = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-10)
    for name in frappe.get_all('Relay Message', filters={'transcript_status': 'Pending', 'modified': ['<', stale]},
                               pluck='name', order_by='modified asc', limit_page_length=20):
        frappe.enqueue('relay_core.voice_transcripts.process', message=name, queue='long', timeout=300,
                       job_id='relay-voice-transcript:' + name, deduplicate=True)
