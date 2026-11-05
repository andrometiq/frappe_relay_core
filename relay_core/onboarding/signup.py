"""WhatsApp signup sessions: the Hub owns each session; Core keeps a Relay WhatsApp Signup copy of it."""
import json
import re
from urllib.parse import urlsplit

import frappe
from relay_core.hub import HubError, safe_text
from relay_core.onboarding.messages import TEXT, OnboardingError, text
from relay_core.permissions import MANAGER
from relay_core.settings import value as connection_value
from relay_core import locks

DOCTYPE = 'Relay WhatsApp Signup'
SESSION = re.compile(r'sus_[a-f0-9]{32}')
FLOWS = ('new', 'coexistence', 'migrate')
STATUS = {'created': 'Started', 'waiting_for_meta': 'Waiting for Meta', 'working': 'Setting up',
          'completed': 'Completed', 'cancelled': 'Cancelled', 'failed': 'Failed', 'expired': 'Expired',
          'superseded': 'Superseded'}
STEPS = ('exchange', 'verify', 'channel', 'subscribe', 'register', 'sync_contacts', 'sync_history')
STEP_STATES = ('pending', 'running', 'done', 'failed', 'skipped')
SYNC = {'pending': 'Pending', 'requested': 'Requested', 'importing': 'Importing', 'done': 'Done',
        'declined': 'Declined', 'failed': 'Failed'}
PHONE = ('id', 'display_phone_number', 'verified_name', 'name_status', 'messaging_limit', 'quality_rating',
         'platform_type')


def hub():
    if not (connection_value('relay_hub_url') and connection_value('relay_hub_token')):
        raise OnboardingError('hub_not_connected')
    from relay_core.whatsapp import client
    return client()


def call(tool, arguments):
    """One signup tool; a rejected call becomes an OnboardingError with the Hub's code."""
    try:
        return hub().call_tool(tool, arguments)
    except HubError as error:
        found = re.search(r'\bcode ([a-z][a-z_]{1,60})\b', error.detail or '')
        code = found.group(1) if found else 'hub_unavailable'
        raise OnboardingError('session_not_found' if code == 'not_found' else code) from None


def session_id(value):
    if not isinstance(value, str) or not SESSION.fullmatch(value):
        frappe.throw('Invalid signup session')
    return value


def hub_origin():
    """Where the Hub serves its signup window: the enrolled origin, else the MCP URL without /mcp."""
    enrolled = frappe.db.get_single_value('Relay Settings', 'hub_origin')
    return enrolled or (connection_value('relay_hub_url') or '').rsplit('/mcp', 1)[0]


def checked_launch(url, session):
    """The Hub's window address for this session, never another site's page."""
    origin = hub_origin().rstrip('/')
    parsed = urlsplit(url) if isinstance(url, str) else None
    expected = urlsplit(origin + '/onboard/whatsapp/' + session)
    if not origin or not parsed or (parsed.scheme, parsed.netloc, parsed.path) != (
            expected.scheme, expected.netloc, expected.path) or parsed.query or parsed.username:
        raise OnboardingError('launch_url_invalid')
    return url


def start(flow, draft):
    from relay_core.onboarding.details import prefill
    if flow not in FLOWS:
        frappe.throw('Choose the type of number')
    result = call('whatsapp.signup.start', {'flow': flow, 'prefill': prefill(draft), 'actor': frappe.session.user})
    session = result.get('session') if isinstance(result, dict) else None
    if not isinstance(session, dict):
        raise OnboardingError('hub_response_invalid')
    launch = checked_launch(result.get('launch_url'), session_id(session.get('session_id')))
    return {'session': store(session, actor=frappe.session.user), 'launch_url': launch}


def status(name, refresh=False):
    arguments = {'session_id': session_id(name), **({'refresh': True} if refresh else {})}
    return store(call('whatsapp.signup.get', arguments))


def resume(name):
    return store(call('whatsapp.signup.resume', {'session_id': session_id(name)}))


def cancel(name):
    return store(call('whatsapp.signup.cancel', {'session_id': session_id(name)}))


def latest():
    """The newest session of this site as the page shows it, or None."""
    row = frappe.get_all(DOCTYPE, fields=['session_data', 'channel', 'hub_channel'], order_by='creation desc', limit_page_length=1)
    if not row or not row[0].session_data:
        return None
    return shown(json.loads(row[0].session_data), row[0].channel or channel_of(row[0].hub_channel))


def channel_of(hub_channel):
    """The Core Relay Channel of a Hub WhatsApp channel key, once a channel sync brought it in."""
    return frappe.db.get_value('Relay Channel', {'channel': 'WhatsApp', 'hub_channel': hub_channel}, 'name') if hub_channel else None


def steps(session):
    rows = session.get('steps') if isinstance(session.get('steps'), list) else []
    return [{'name': row['name'], 'status': row.get('status') if row.get('status') in STEP_STATES else 'pending',
             'at': row.get('at') if isinstance(row.get('at'), str) else None}
            for row in rows if isinstance(row, dict) and row.get('name') in STEPS]


def current_step(rows):
    return next((row['name'] for row in rows if row['status'] in ('running', 'failed', 'pending')), '')


def error_of(session):
    """{code, message, retryable} in Relay's words; Meta's own text only where it is the reason."""
    error = session.get('error') if isinstance(session.get('error'), dict) else None
    state = session.get('state')
    if state == 'cancelled':
        error = dict(error or {}, code='cancelled')
    elif state == 'expired' and not error:
        error = {'code': 'expired'}
    if not error:
        return None
    code = error.get('code') if isinstance(error.get('code'), str) else 'unknown'
    detail = safe_text(error.get('message'))
    message = text(code, detail=detail, step=step_label(error.get('meta_step'))) if code in TEXT else detail or text(code)
    return {'code': code, 'message': message, 'retryable': error.get('retryable') is True}


def step_label(value):
    return safe_text(value, 60).replace('_', ' ').lower() if isinstance(value, str) else ''


def phone_of(session):
    phone = session.get('phone') if isinstance(session.get('phone'), dict) else {}
    return {key: safe_text(phone.get(key), 120) for key in PHONE if phone.get(key) is not None} or None


def coexistence_of(session):
    value = session.get('coexistence') if isinstance(session.get('coexistence'), dict) else None
    if not value:
        return None
    progress = value.get('history_progress')
    return {'contacts': value.get('contacts') if value.get('contacts') in SYNC else 'pending',
            'history': value.get('history') if value.get('history') in SYNC else 'pending',
            'history_progress': progress if type(progress) is int and 0 <= progress <= 100 else 0}


def checked_session(session):
    """The Hub Session reduced to known fields; anything malformed is refused."""
    if not isinstance(session, dict) or session.get('state') not in STATUS:
        raise OnboardingError('hub_response_invalid')
    key = session.get('channel_key')
    from relay_core.channel_sync import KEY
    return {'session_id': session_id(session.get('session_id')),
            'flow': session.get('flow') if session.get('flow') in FLOWS else 'new',
            'flow_actual': session.get('flow_actual') if session.get('flow_actual') in FLOWS else None,
            'state': session['state'], 'steps': steps(session), 'error': session.get('error'),
            'channel_key': key if isinstance(key, str) and KEY.fullmatch(key) else None,
            'waba_id': digits(session.get('waba_id')), 'business_id': digits(session.get('business_id')),
            'phone': phone_of(session), 'coexistence': coexistence_of(session),
            'payment_method_ready': session.get('payment_method_ready') if type(session.get('payment_method_ready')) is bool else None,
            'expires_at': safe_text(session.get('expires_at'), 40), 'updated_at': safe_text(session.get('updated_at'), 40)}


def digits(value):
    return value if isinstance(value, str) and value.isdigit() and len(value) <= 40 else None


def shown(session, channel=None):
    """What the browser gets: the checked Session, the error in Relay's words and the Core channel."""
    return dict(session, error=error_of(session), channel=channel or None)


def store(session, actor=None):
    """Upsert the Core copy under a per-session lock; completion runs until the new channel is linked.

    The lock holder reads after a commit and commits before it lets go, so a request and the callback
    worker never write from an older snapshot (MariaDB error 1020)."""
    session = checked_session(session)
    name = session['session_id']
    with locks.lock('relay-signup:' + name, timeout=60, blocking_timeout=30):
        frappe.db.commit()
        exists = frappe.db.exists(DOCTYPE, name)
        doc = frappe.get_doc(DOCTYPE, name) if exists else frappe.get_doc(
            {'doctype': DOCTYPE, 'name': name, 'session_id': name, 'started_by': actor or frappe.session.user})
        first = doc.get('status') != 'Completed'
        doc.update(kept(doc, values(session)))
        if doc.status == 'Completed' and (first or (doc.hub_channel and not doc.get('channel'))):
            doc.update(complete(doc))
        if exists:
            doc.save(ignore_permissions=True)
        else:
            doc.insert(ignore_permissions=True)
        frappe.db.commit()
    publish(name)
    return shown(session, doc.get('channel'))


def values(session):
    error = error_of(session) or {}
    coexistence = session['coexistence'] or {}
    phone = session['phone'] or {}
    return {'flow': session['flow'], 'flow_actual': session['flow_actual'] or '', 'status': STATUS[session['state']],
            'step': current_step(session['steps']), 'error_code': error.get('code', ''),
            'error_message': error.get('message', ''), 'retryable': int(bool(error.get('retryable'))),
            'hub_channel': session['channel_key'] or '', 'phone_number': phone.get('display_phone_number', ''),
            'waba_id': session['waba_id'] or '', 'payment_method_ready': int(bool(session['payment_method_ready'])),
            'contacts_status': SYNC.get(coexistence.get('contacts'), ''),
            'history_status': SYNC.get(coexistence.get('history'), ''),
            'history_progress': coexistence.get('history_progress') or 0,
            'session_data': json.dumps(session, sort_keys=True)}


def kept(doc, changes):
    """Core imports the copied chats itself, so a finished copy or a higher progress never goes back."""
    for field in ('contacts_status', 'history_status'):
        if doc.get(field) in ('Done', 'Declined'):
            changes.pop(field)
    changes['history_progress'] = max(changes['history_progress'], doc.get('history_progress') or 0)
    return changes


def complete(doc):
    """Bring the new channel in, queue its templates and make the admin a Relay Communication Manager.

    A failed channel read leaves `channel` empty, and the next store of the session runs this again."""
    from relay_core.channel_sync import sync
    sync()
    channel = channel_of(doc.hub_channel)
    frappe.enqueue('relay_core.whatsapp_templates.sync', queue='short', job_id='relay-onboarding-templates',
                   deduplicate=True, enqueue_after_commit=True, notify=True)
    grant_manager(doc.started_by)
    return {'channel': channel, 'completed_at': doc.get('completed_at') or frappe.utils.now_datetime()}


def grant_manager(user):
    if not user or user in ('Administrator', 'Guest') or not frappe.db.exists('User', user):
        return
    doc = frappe.get_doc('User', user)
    if MANAGER not in [row.role for row in doc.roles]:
        doc.append('roles', {'role': MANAGER})
        doc.save(ignore_permissions=True)


def publish(name):
    frappe.publish_realtime('relay_changed', {'kind': 'onboarding', 'session': name},
                            room=frappe.realtime.get_doctype_room(DOCTYPE), after_commit=True)


def project_event(payload):
    """A `relay_signup` callback is a hint: read the session from the Hub and store it. False when that failed."""
    try:
        status(session_id(payload.get('session_id')))
    except (OnboardingError, frappe.ValidationError):
        return False
    return True
