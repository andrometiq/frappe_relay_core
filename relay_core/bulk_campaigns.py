"""WhatsApp template, text and media campaigns from an uploaded sheet or JSON rows, pushed to Hub 50 rows at a time."""
import base64
import hashlib
import json
import mimetypes
import re
import time
import frappe
from frappe.exceptions import DoesNotExistError, PermissionError, ValidationError
from redis.exceptions import LockError
from relay_core import bulk_sheet, service_window, whatsapp
from relay_core.automation.contracts import canonical
from relay_core.automation.service import internal_save
from relay_core.hub_channels import hub_arguments
from relay_core.identity import default_region
from relay_core.permissions import require_access
from relay_core.settings import value as connection_value

RECIPIENT = 'Relay Campaign Recipient'
BATCH = 50
CHUNK = 1000
CALL_ROWS = 5000  # JSON rows per API call; more go through append_rows.
HIGH_WATER = 1000
LOW_WATER = 500
DEFAULT_RATE = 50
SLICE_SECONDS = 45
JOB_TIMEOUT = 1800  # A 100,000-row import; a send slice ends long before.
RETRY_SECONDS = 60
LOCK_WAIT = 10  # A slice notices a pause or cancel within one Hub call or one second of waiting.
WAIT = 'relay-bulk-wait:'
RETRIES = 'relay-bulk-retries:'
CANCEL_AFTER = 'relay-bulk-cancel-after:'
NOT_QUEUED = 'queued delivery could not be cancelled'  # Hub already sends it; its update has the outcome.
CANCEL_REFUSED = ('Hub refused to cancel queued messages, so they may still be sent. Issue a Hub auth key with the '
                  'deliveries:cancel scope and save it in Relay Settings; Relay retries by itself. ')
OPERATIONS = ('templates.send', 'messages.send', 'messages.media')
OUTSIDE_WINDOW = 'Outside the 24-hour reply window'
OPTED_OUT = 'Opted out'
MEDIA_DAYS = 29  # Meta keeps an uploaded media id for 30 days.
ADMISSION = {'queued': 'Queued', 'submitting': 'Queued', 'submitted': 'Queued', 'rejected': 'Failed',
             'uncertain': 'Uncertain', 'cancelled': 'Cancelled'}


def is_bulk(doc):
    if doc.operation == 'templates.send':
        return bool(doc.template_name)
    return doc.operation in OPERATIONS and bool(doc.arguments) and 'message' in json.loads(doc.arguments)


def bulk(name, statuses=None):
    require_access('Relay Campaign', 'write')
    doc = frappe.get_doc('Relay Campaign', name)
    doc.check_permission('read')
    if not is_bulk(doc):
        frappe.throw('This is not a WhatsApp bulk campaign')
    if statuses and doc.status not in statuses:
        frappe.throw(f'Campaign is {doc.status}')
    return doc


def whatsapp_channel(channel=None):
    """The given enabled WhatsApp channel, else the site's default number."""
    from relay_core.hub_channels import choose
    return choose('WhatsApp', requested=channel)


def campaign_channel(channel=None):
    """A campaign names its number once the site has more than one; the template list is that number's WABA."""
    if not channel and frappe.db.count('Relay Channel', {'channel': 'WhatsApp', 'enabled': 1,
                                                         'account': connection_value('relay_hub_account')}) > 1:
        frappe.throw('Choose the WhatsApp number this campaign sends from')
    return whatsapp_channel(channel)


def channel_region(channel):
    """Use the sending company's country, falling back to System Settings."""
    from frappe.geo.country_info import get_country_info
    company = frappe.db.get_value('Relay Channel', channel, 'company')
    country = frappe.db.get_value('Company', company, 'country') if company else None
    code = (get_country_info(country) or {}).get('code') if country else None
    return code.upper() if isinstance(code, str) and len(code) == 2 else default_region()


def approved_template(hub, name, language, channel=None):
    from relay_core.whatsapp_templates import overlay
    after = ''
    for _ in range(20):
        page = overlay(hub.execute(hub_arguments(channel, {'operation': 'templates.list', **({'after': after} if after else {})})))
        for row in page.get('data') or []:
            if row.get('name') == name and row.get('language') == language:
                if row.get('status') != 'APPROVED':
                    frappe.throw('Choose an approved template')
                return row
        paging = page.get('paging') or {}
        after = (paging.get('cursors') or {}).get('after')
        if not paging.get('has_more') or not after:
            break
    frappe.throw('Template not found for this WhatsApp account')


def template_snapshot(template):
    kept = {key: template.get(key) for key in ('name', 'language', 'category', 'parameter_format', 'components')}
    return {'template': kept, 'fields': bulk_sheet.template_fields(template)}


@frappe.whitelist(methods=['POST'])
def create(title, template_name=None, language=None, channel=None, reply_window_hours=72, message=None):
    """A Draft campaign that sends an approved template, or with message a text or media message."""
    require_access('Relay Campaign', 'write')
    title = (title or '').strip() if isinstance(title, str) else ''
    if not 3 <= len(title) <= 100 or any(c in title for c in '/\\%#?<>'):
        frappe.throw('Give the campaign a readable title of 3-100 characters')
    hours = frappe.utils.cint(reply_window_hours)
    if not 1 <= hours <= 720:
        frappe.throw('Reply window must be 1-720 hours')
    if frappe.db.exists('Relay Campaign', title):
        frappe.throw('A campaign with this title already exists')
    target = campaign_channel(channel)
    try:
        if message:
            operation, snapshot = campaign_message(frappe.parse_json(message))
            template_name = language = None
        else:
            hub, _ = whatsapp.checked_client()
            operation, snapshot = 'templates.send', template_snapshot(approved_template(hub, template_name, language, target))
    except whatsapp.HubError as exc:
        frappe.throw(whatsapp.failure_message(exc))
    except ValueError as exc:
        frappe.throw(str(exc))
    doc = frappe.get_doc(dict(doctype='Relay Campaign', title=title, channel=target, operation=operation,
        template_name=template_name, language=language, arguments=canonical(snapshot),
        status='Draft', account=connection_value('relay_hub_account'), country=channel_region(target),
        reply_window_hours=hours, request_key='bulk-' + hashlib.sha256(title.encode()).hexdigest()[:40]))
    internal_save(doc, new=True)
    return read(doc.name)


def campaign_message(message):
    """Operation and snapshot of a text or media campaign."""
    message = bulk_sheet.check_message(message)
    operation = 'messages.send' if message['kind'] == 'text' else 'messages.media'
    return operation, {'message': message, 'fields': bulk_sheet.message_fields(message)}


def fixed_file(doc):
    """(File, MIME type) that every row of a media campaign sends, or None when rows carry links."""
    mapping = json.loads(doc.column_map or '{}')
    attachment = mapping.get('header_attachment')
    if attachment:
        if attachment['mode'] != 'static':
            return None
        from relay_core.campaign_media import checked_file
        return checked_file(attachment['files'][0], header_type(doc))
    value = (mapping.get('fixed') or {}).get('media_url')
    if not bulk_sheet.is_site_file(value):
        return None
    kind = json.loads(doc.arguments)['message']['kind']
    file = uploaded_file(value)
    mime_type = mimetypes.guess_type(file.file_name or '')[0]
    if mime_type not in bulk_sheet.accepted_types(kind):
        frappe.throw(f'Upload a {kind} file in a format WhatsApp accepts')
    return file, mime_type


def media_upload(hub, doc):
    """Campaign fields of the Hub media id for the fixed file: uploaded once, and again when the id would expire."""
    found = fixed_file(doc)
    if not found:
        return {}
    now = frappe.utils.now_datetime()
    if doc.media_id and frappe.utils.get_datetime(doc.media_uploaded_at) > frappe.utils.add_to_date(now, days=-MEDIA_DAYS):
        return {}
    file, mime_type = found
    snapshot = json.loads(doc.arguments)
    kind = bulk_sheet.MESSAGE_MEDIA[snapshot['message']['kind']] if 'message' in snapshot else header_type(doc)
    media_id = upload_media_file(hub, doc.channel, file, mime_type, kind)
    return {'media_id': media_id, 'media_uploaded_at': now}


def upload_media_file(hub, channel, file, mime_type, kind, filename=None):
    from relay_core.template_media import MAX_BYTES
    with open(file.get_full_path(), 'rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    if not 1 <= len(raw) <= MAX_BYTES:
        raise ValueError('Header attachment must contain 1 byte to 4 MiB')
    payload = whatsapp.prepare('messages.media_upload', {'media_type': kind, 'mime_type': mime_type,
        'filename': filename or file.file_name, 'content_base64': base64.b64encode(raw).decode()})
    media_id = str(hub.execute(hub_arguments(channel, payload)).get('id') or '')
    if not re.fullmatch(r'[0-9]{1,100}', media_id):
        raise whatsapp.HubError('Hub returned no media id')
    return media_id


def uploaded_file(file_url):
    name = frappe.db.get_value('File', {'file_url': file_url}, 'name')
    if not name:
        frappe.throw('Uploaded file not found')
    file = frappe.get_doc('File', name)
    file.check_permission('read')
    return file


def source_path(file_url):
    if not isinstance(file_url, str) or not file_url.lower().endswith(('.xlsx', '.csv', '.tsv')):
        frappe.throw('Upload a .xlsx, .csv or .tsv file')
    return uploaded_file(file_url).get_full_path()


@frappe.whitelist(methods=['POST'])
def inspect(name, file_url):
    """Columns, a five-row sample and a suggested mapping for the uploaded sheet."""
    doc = bulk(name, ('Draft',))
    try:
        header, sample = bulk_sheet.columns(source_path(file_url))
    except ValueError as exc:
        frappe.throw(str(exc))
    if not header:
        frappe.throw('The file has no recipient rows')
    doc.source_file, doc.recipient_filters = file_url, None
    internal_save(doc)
    fields = json.loads(doc.arguments)['fields']
    return {'columns': header, 'sample': sample, 'fields': fields, 'mapping': bulk_sheet.suggest(header, fields, first_phone=True)}


@frappe.whitelist(methods=['POST'])
def import_rows(name, mapping):
    doc = bulk(name, ('Draft',))
    if not doc.source_file:
        frappe.throw('Upload the recipient file first')
    mapping = frappe.parse_json(mapping) if isinstance(mapping, str) else mapping
    try:
        header, _ = bulk_sheet.columns(source_path(doc.source_file), sample=1)
        if not header or not isinstance(mapping, dict):
            raise ValueError('Upload recipient rows and choose their mapping')
        mapping = bulk_sheet.check_mapping({**mapping, 'phone': header[0]}, header, json.loads(doc.arguments)['fields'])
    except ValueError as exc:
        frappe.throw(str(exc))
    doc.column_map, doc.recipient_filters = canonical(mapping), None
    start_import(doc)
    return read(name)


def start_import(doc):
    try:
        fixed_file(doc)
    except (ValueError, OSError) as exc:
        frappe.throw(str(exc))
    doc.status, doc.last_error = 'Importing', ''
    doc.media_id, doc.media_uploaded_at = None, None
    internal_save(doc)
    enqueue('import_job', doc.name)


def given_rows(rows, after=0):
    rows = parsed(rows)
    if not isinstance(rows, list) or not 1 <= len(rows) <= CALL_ROWS:
        frappe.throw(f'Send 1-{CALL_ROWS} rows in one call')
    try:
        return list(bulk_sheet.given_rows(rows, after))
    except ValueError as exc:
        frappe.throw(str(exc))


def parsed(value):
    """JSON text from a form post as its value; text that is not JSON stays text and fails the type check."""
    try:
        return frappe.parse_json(value) if isinstance(value, str) else value
    except ValueError:
        return value


@frappe.whitelist(methods=['POST'])
def create_with_rows(title, rows, message=None, template_name=None, language=None, mapping=None, start=0,
                     channel=None, reply_window_hours=72):
    """A campaign whose recipients are JSON objects of column -> value; start=1 starts sending at once.
    Without a mapping, columns are matched by name as for a sheet."""
    require_access('Relay Campaign', 'write')
    numbered = given_rows(rows)
    name = create(title, template_name, language, channel, reply_window_hours, message)['name']
    doc = frappe.get_doc('Relay Campaign', name)
    header = list(dict.fromkeys(column for _, row in numbered for column in row))
    fields = json.loads(doc.arguments)['fields']
    mapping = parsed(mapping)
    try:
        doc.column_map = canonical(bulk_sheet.check_mapping(mapping or bulk_sheet.suggest(header, fields), header, fields))
    except ValueError as exc:
        frappe.throw(str(exc))
    fixed_file(doc)
    internal_save(doc)
    add_rows(doc, numbered, set())
    from relay_core.bulk_updates import changed
    changed(name)
    return control(name, 'start') if frappe.utils.cint(start) else read(name)


@frappe.whitelist(methods=['POST'])
def append_rows(name, rows):
    """More JSON rows for a Draft campaign created with rows. A number the campaign already holds is a duplicate."""
    doc = bulk(name, ('Draft',))
    if doc.source_file or doc.recipient_filters or not doc.column_map:
        frappe.throw('Add rows only to a campaign created with rows')
    with frappe.cache.lock('relay-bulk-append:' + name, timeout=120):
        last, total = frappe.db.sql(f'SELECT COALESCE(MAX(sheet_row), 0), COUNT(*) FROM `tab{RECIPIENT}` WHERE campaign=%s',
                                    name)[0]
        numbered = given_rows(rows, int(last))
        if total + len(numbered) > bulk_sheet.MAX_ROWS:
            frappe.throw(f'A campaign supports at most {bulk_sheet.MAX_ROWS} rows')
        add_rows(doc, numbered, held_numbers(doc, numbered))
    from relay_core.bulk_updates import changed
    changed(name)
    return read(name)


def held_numbers(doc, rows):
    """Numbers of these rows the campaign already holds in a row that was not skipped."""
    column = json.loads(doc.column_map)['phone']
    numbers = list({bulk_sheet.sheet_phone(row.get(column), doc.country) for _, row in rows} - {None})
    if not numbers:
        return set()
    return set(frappe.get_all(RECIPIENT, filters={'campaign': doc.name, 'destination': ['in', numbers],
                                                  'status': ['!=', 'Skipped']}, pluck='destination', limit_page_length=0))


def enqueue(method, name, step=0, slot=None):
    """Short jobs at the back of the queue. A slice continues under the other of two job IDs, because its own
    ID is still running and deduplication would drop it; a manager's action uses a third."""
    frappe.enqueue(f'relay_core.bulk_campaigns.{method}', name=name, queue='long', timeout=JOB_TIMEOUT,
                   job_id=f'relay-bulk-{method}:{name}:{step % 2 if slot is None else slot}', deduplicate=True,
                   enqueue_after_commit=True, **({'step': step} if step else {}))


def import_job(name):
    doc = frappe.get_doc('Relay Campaign', name)
    if doc.status != 'Importing':
        return
    remove_unsent(name)
    try:
        add_rows(doc, recipient_rows(doc), set())
        doc.last_error = ''
    except (ValueError, OSError, ValidationError, PermissionError) as exc:
        frappe.db.rollback()
        remove_unsent(name)  # Chunks before the error were committed; none of them may start.
        doc.last_error = str(exc)[:500]
    doc.status = 'Draft'
    internal_save(doc)
    frappe.db.commit()
    from relay_core.bulk_updates import changed
    changed(name)


def recipient_rows(doc):
    if doc.recipient_filters:
        from relay_core.campaign_audience import contact_rows
        return contact_rows(doc)
    return bulk_sheet.read_rows(source_path(doc.source_file))


def add_rows(doc, rows, seen):
    """Check and insert (row number, column -> text) rows in chunks; sheet and JSON rows share this path."""
    snapshot, mapping = json.loads(doc.arguments), json.loads(doc.column_map)
    fields, message = snapshot['fields'], snapshot.get('message')
    attachment, resolved = mapping.get('header_attachment'), {}
    if attachment:
        from relay_core.campaign_media import resolve
        # Only the destination set is retained; the uploaded sheet remains streamed.
        if doc.source_file:
            numbers = {bulk_sheet.sheet_phone(row.get(mapping['phone']), doc.country) for _, row in recipient_rows(doc)}
        else:
            rows = list(rows)
            numbers = {bulk_sheet.sheet_phone(row.get(mapping['phone']), doc.country) for _, row in rows}
        resolved = resolve(attachment, header_type(doc), numbers - {None}, doc.country)
    chunk, enrolled = [], {}
    for number, row in rows:
        destination = bulk_sheet.sheet_phone(row.get(mapping['phone']), doc.country)
        header_file, media_problem = resolved.get(destination, (None, None))
        destination, values, problem = bulk_sheet.prepare_row(row, mapping, fields, doc.country, header_file)
        if destination and media_problem:
            problem = media_problem
        if doc.source_file and not doc.recipient_filters:
            values = values or {'values': {}}
            if not destination:
                values['contact_status'] = 'invalid'
            elif destination in enrolled:
                values['contact_status'] = 'existing'
                problem = problem or enrolled[destination]
            else:
                contact_status, contact_problem = sheet_contact(doc.channel, destination)
                enrolled[destination] = contact_problem
                values['contact_status'] = contact_status
                problem = problem or contact_problem
        if not problem and message:
            problem = bulk_sheet.message_problem(message, values['values'])
        if not problem and destination in seen:
            problem = 'Duplicate number'
        seen.add(destination)
        shown = destination or str(row.get(mapping['phone']) or '').strip()[:40]
        chunk.append((number, shown, values, problem))
        if len(chunk) == CHUNK:
            insert_chunk(doc, chunk)
            chunk = []
    insert_chunk(doc, chunk)


def sheet_contact(channel, number):
    """Use the existing enrollment path, holding its person lock through commit.

    The indexed lookup also preserves revoked bindings and opt-outs. A fresh transaction
    inside the lock sees another campaign's committed endpoint before creating anything.
    """
    from relay_core.contact_lifecycle import endpoint_key, sibling_contact, whatsapp_contact
    if not bulk_sheet.sheet_phone('+' + number, ''):
        return 'invalid', 'Invalid phone number'
    with frappe.cache.lock('relay-whatsapp-person:' + number, timeout=30):
        frappe.db.commit()
        existing = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': endpoint_key(channel, number)},
                                       ['relay_contact', 'verified'], as_dict=True, for_update=True)
        if existing:
            return 'existing', None if existing.verified else 'Endpoint verification revoked'
        try:
            relay = sibling_contact(channel, number) or whatsapp_contact(channel, number, locked=True)
            frappe.db.commit()  # Enrollment must be visible before the Redis lock is released.
        except Exception:
            frappe.db.rollback()
            raise
        return ('created', None) if relay else ('existing', 'Contact binding needs review')


def contact_counts(name):
    rows = frappe.db.sql(f"""SELECT JSON_UNQUOTE(JSON_EXTRACT(arguments, '$.contact_status')) AS kind,
        COUNT(*) AS count FROM `tab{RECIPIENT}` WHERE campaign=%s GROUP BY kind""", name, as_dict=True)
    return {kind: sum(row.count for row in rows if row.kind == kind) for kind in ('created', 'existing', 'invalid')}


def header_type(doc):
    return next(field['media'] for field in json.loads(doc.arguments)['fields'] if field['key'] == 'header_media')


def remove_unsent(campaign):
    for status in ('Skipped', 'Pending'):
        in_chunks(campaign, status, lambda names: frappe.db.delete(RECIPIENT, {'name': ['in', names]}))


def in_chunks(campaign, status, apply):
    """Short transactions over a large campaign; never one long lock."""
    while True:
        names = frappe.get_all(RECIPIENT, filters={'campaign': campaign, 'status': status}, pluck='name',
                               limit_page_length=CHUNK)
        if not names:
            return
        apply(tuple(names))
        frappe.db.commit()


def recipient_key(campaign, number):
    return f"bulk-{hashlib.sha256(campaign.encode()).hexdigest()[:16]}-{number}"


def endpoint_facts(channel, destinations):
    """Linked Contact per verified number and opt-out per number, in indexed queries. An opt-out
    outlives the Contact link: a number removed from its Contact keeps its Denied preference."""
    if not destinations:
        return {}, set()
    keys = {hashlib.sha256((channel + ':' + number).encode()).hexdigest(): number for number in destinations}
    endpoints = frappe.get_all('Relay Contact Endpoint', filters={'endpoint_key': ['in', list(keys)]},
                               fields=['name', 'endpoint_key', 'relay_contact', 'verified', 'marketing_opt_out'],
                               limit_page_length=0)
    verified = [e for e in endpoints if e.verified]
    people = dict(frappe.get_all('Relay Contact', filters={'name': ['in', [e.relay_contact for e in verified]]},
                                 fields=['name', 'contact'], as_list=True, limit_page_length=0)) if verified else {}
    denied = set(frappe.get_all('Relay Channel Preference', filters={'endpoint': ['in', [e.name for e in endpoints]],
                 'consent': 'Denied'}, pluck='endpoint', limit_page_length=0)) if endpoints else set()
    contacts = {keys[e.endpoint_key]: people.get(e.relay_contact) for e in verified}
    return contacts, {keys[e.endpoint_key] for e in endpoints if e.name in denied or e.marketing_opt_out}


def insert_chunk(doc, chunk):
    if not chunk:
        return
    contacts, opted_out = endpoint_facts(doc.channel, [d for _, d, _, p in chunk if d and not p])
    now, user = frappe.utils.now(), frappe.session.user
    values = []
    for number, destination, arguments, problem in chunk:
        if not problem and destination in opted_out:
            problem = OPTED_OUT
        key = recipient_key(doc.name, number)
        values.append((key, now, now, user, user, 0, doc.name, contacts.get(destination), key, key,
                       'Skipped' if problem else 'Pending', destination or '', canonical(arguments) if arguments else None,
                       number, problem or ''))
    frappe.db.bulk_insert(RECIPIENT, ('name', 'creation', 'modified', 'owner', 'modified_by', 'docstatus', 'campaign',
        'contact', 'recipient_key', 'request_key', 'status', 'destination', 'arguments', 'sheet_row', 'reason'),
        values, ignore_duplicates=True)
    frappe.db.commit()


@frappe.whitelist(methods=['GET'])
def read(name, after=None, status=None):
    doc = bulk(name)
    filters = [['campaign', '=', name]]
    if after:
        filters.append(['sheet_row', '>', frappe.utils.cint(after)])
    if status:
        if status not in ('Pending', 'Skipped', 'Queued', 'Sent', 'Delivered', 'Read', 'Failed', 'Uncertain', 'Cancelled'):
            frappe.throw('Invalid recipient status')
        filters.append(['status', '=', status])
    rows = frappe.get_all(RECIPIENT, filters=filters, fields=['sheet_row', 'destination', 'contact', 'status', 'reason',
                          'error_code', 'replied_at'], order_by='sheet_row asc', limit_page_length=51)
    issues = frappe.db.sql(f'''SELECT reason, count(*) AS count FROM `tab{RECIPIENT}` WHERE campaign=%s
        AND status IN ('Skipped','Failed') AND reason!='' GROUP BY reason ORDER BY count DESC LIMIT 10''', name, as_dict=True)
    snapshot = json.loads(doc.arguments)
    return {**{key: doc.get(key) for key in ('name', 'title', 'channel', 'status', 'operation', 'template_name', 'language',
               'source_file', 'country', 'reply_window_hours', 'scheduled_at', 'started_at', 'finished_at', 'last_error')},
            'mapping': json.loads(doc.column_map) if doc.column_map else None, 'message': snapshot.get('message'),
            'audience': json.loads(doc.recipient_filters) if doc.recipient_filters else None,
            'time_zone': frappe.utils.get_system_timezone(),
            'fields': snapshot['fields'], 'counts': counts(doc), 'issues': issues,
            'contact_counts': contact_counts(name) if doc.source_file else None,
            'recipients': rows[:50], 'next': rows[49].sheet_row if len(rows) > 50 else None}


@frappe.whitelist(methods=['GET'])
def window(name):
    """Pending numbers that can receive text or media now; the rest fail at send time without a Hub call."""
    doc = bulk(name)
    numbers = frappe.get_all(RECIPIENT, filters={'campaign': name, 'status': 'Pending'}, pluck='destination',
                             limit_page_length=0)
    reachable = sum(len(service_window.open_numbers(doc.channel, numbers[start:start + CHUNK]))
                    for start in range(0, len(numbers), CHUNK))
    return {'open': reachable, 'closed': len(numbers) - reachable}


def counts(doc):
    return {key: doc.get(key + '_count') or 0 for key in
            ('total', 'skipped', 'queued', 'sent', 'delivered', 'read', 'failed', 'replied')}


@frappe.whitelist(methods=['POST'])
def control(name, action, scheduled_at=None):
    """Start, schedule, pause, resume or cancel. A schedule runs the start checks now and starts at scheduled_at
    in the site time zone."""
    transitions = {'start': (('Draft', 'Scheduled'), 'Running'), 'schedule': (('Draft',), 'Scheduled'),
                   'unschedule': (('Scheduled',), 'Draft'), 'pause': (('Running',), 'Paused'),
                   'resume': (('Paused',), 'Running'), 'cancel': (('Draft', 'Scheduled', 'Running', 'Paused'), 'Cancelling')}
    if action not in transitions:
        frappe.throw('Invalid campaign action')
    allowed, target = transitions[action]
    require_access('Relay Campaign', 'write')
    if target == 'Scheduled':
        from relay_core.campaign_schedule import start_time
        scheduled_at = start_time(scheduled_at)
    checked = target in ('Running', 'Scheduled')
    media = check_ready(bulk(name, allowed)) if checked else {}  # Hub calls stay outside the lock.
    with frappe.cache.lock('relay-bulk-control:' + name, timeout=30):
        doc = bulk(name, allowed)
        if checked:
            doc.execution_user = frappe.session.user
            doc.update(media)
        if target == 'Running':
            doc.started_at = doc.started_at or frappe.utils.now_datetime()
            from relay_core.bulk_updates import open_reply_window
            open_reply_window(doc.reply_window_hours)
        if target in ('Scheduled', 'Draft'):
            doc.scheduled_at = scheduled_at if target == 'Scheduled' else None
        doc.status, doc.last_error = target, ''
        internal_save(doc)
    if target in ('Running', 'Cancelling'):
        frappe.cache.delete_value(WAIT + name)  # A manager's action tries Hub now, not after a backoff.
        enqueue('send_job', name, slot='control')
    return read(name)


def check_ready(doc):
    whatsapp_channel(doc.channel)
    if doc.status == 'Draft' and doc.last_error:
        frappe.throw('The last import failed. Fix the file and import the recipients again')
    if doc.status == 'Draft' and not frappe.db.exists(RECIPIENT, {'campaign': doc.name, 'status': 'Pending'}):
        frappe.throw('Import recipients with at least one valid row first')
    try:
        hub, _ = whatsapp.checked_client()
        if doc.operation == 'templates.send':
            approved_template(hub, doc.template_name, doc.language, doc.channel)
        return media_upload(hub, doc)
    except (ValueError, OSError) as exc:
        frappe.throw(str(exc))
    except whatsapp.HubError as exc:
        frappe.throw(whatsapp.failure_message(exc))


def send_job(name, step=0):
    """One slice of at most SLICE_SECONDS; it enqueues the next slice instead of running on."""
    deadline, more = time.monotonic() + SLICE_SECONDS, False
    try:
        with frappe.cache.lock('relay-bulk-send:' + name, timeout=SLICE_SECONDS + 300, blocking_timeout=LOCK_WAIT):
            doc = frappe.get_doc('Relay Campaign', name)
            if doc.status == 'Running':
                more = push(doc, deadline)
            if not more and current_status(name) == 'Cancelling':
                more = cancel_remaining(doc, deadline)
    except LockError:
        return  # Another worker owns this campaign.
    from relay_core.bulk_updates import changed
    changed(name)
    if more:
        enqueue('send_job', name, step + 1)
    frappe.db.commit()


def current_status(name):
    frappe.db.commit()  # A fresh snapshot sees a manager's pause or cancel.
    return frappe.db.get_value('Relay Campaign', name, 'status')


def wait(name, seconds):
    """Backpressure and retry: the slice, or its successor, sends again after this time."""
    frappe.cache.set_value(WAIT + name, time.time() + seconds, expires_in_sec=int(seconds) + 3600)


def is_waiting(name, deadline):
    """Sleep up to a second toward the wait time; True while that time is still ahead."""
    delay = frappe.utils.flt(frappe.cache.get_value(WAIT + name)) - time.time()
    if delay <= 0:
        return False
    time.sleep(max(0, min(delay, 1, deadline - time.monotonic())))
    return True


def retry_later(doc, message):
    """Show the Hub error and back off 5, 10, 20, 40, then 60 seconds. Self-driving: no scheduler needed."""
    attempts = frappe.utils.cint(frappe.cache.get_value(RETRIES + doc.name))
    frappe.cache.set_value(RETRIES + doc.name, attempts + 1, expires_in_sec=3600)
    wait(doc.name, min(RETRY_SECONDS, 5 * 2 ** attempts))
    doc.last_error = message[:500]
    frappe.db.set_value('Relay Campaign', doc.name, 'last_error', doc.last_error, update_modified=False)
    frappe.db.commit()


def push(doc, deadline):
    """Push Pending rows 50 at a time. True when the slice ran out of time with rows left."""
    snapshot = json.loads(doc.arguments)
    hub = whatsapp.client()
    has_attachments = bool(json.loads(doc.column_map or '{}').get('header_attachment'))
    while time.monotonic() < deadline:
        if current_status(doc.name) != 'Running':
            return False
        if is_waiting(doc.name, deadline):
            continue
        rows = frappe.db.sql(f'''SELECT name, request_key, destination, arguments FROM `tab{RECIPIENT}`
            WHERE campaign=%s AND status='Pending' ORDER BY sheet_row LIMIT {BATCH}''', doc.name, as_dict=True)
        if not rows:
            return False
        rows = without_opted_out(doc, rows)
        if rows and 'message' in snapshot:
            rows = within_window(doc, rows)
        if not rows:
            continue
        try:
            rows = prepare_messages(hub, doc, snapshot, rows, deadline=deadline)
        except whatsapp.HubError as exc:
            retry_later(doc, whatsapp.failure_message(exc))
            continue
        except (ValueError, OSError, ValidationError, PermissionError) as exc:
            doc.status, doc.last_error = 'Paused', str(exc)[:500]
            internal_save(doc)
            frappe.db.commit()
            return False
        if has_attachments:
            if current_status(doc.name) != 'Running':
                return False
            rows = without_opted_out(doc, rows)
        if not rows:
            continue
        messages = [{'key': row.request_key, 'message': row.message} for row in rows]
        # Attempted before Hub sends: a reply can arrive before this batch's admission commits.
        frappe.db.sql(f"UPDATE `tab{RECIPIENT}` SET attempted=1 WHERE name IN %s", (tuple(row.name for row in rows),))
        frappe.db.commit()
        try:
            result = hub.call_tool('whatsapp.bulk', hub_arguments(doc.channel, {'messages': messages}))
        except whatsapp.HubError as exc:
            retry_later(doc, whatsapp.failure_message(exc))  # The same keys go again; Hub returns rows it holds.
            continue
        from relay_core.bulk_timeline import record, reserve
        first = reserve(len(rows))  # Commits; the batch below locks its rows before it reads any.
        admitted = admit(rows, result.get('deliveries') or [])
        if doc.last_error:  # Hub accepted again after a retry.
            clear_error(doc)
        record(doc, snapshot, [row for row in rows if row.request_key in admitted], first)
        frappe.db.commit()
        from relay_core.bulk_updates import changed
        changed(doc.name)
        queued = frappe.utils.cint(result.get('queued'))
        if queued >= HIGH_WATER:
            rate = frappe.utils.cint(result.get('messages_per_second')) or DEFAULT_RATE
            wait(doc.name, (queued - LOW_WATER) / rate)
    return True


def prepare_messages(hub, doc, snapshot, rows, *, deadline=None):
    attachment = json.loads(doc.column_map or '{}').get('header_attachment')
    if not attachment:
        for row in rows:
            row.message = hub_message(doc, snapshot, row)
        return rows
    from relay_core.campaign_media import checked_file
    kind = header_type(doc)
    files = {(item['file_url'], item['filename']) for item in attachment['files']}
    ready = []
    for row in rows:
        if deadline is not None and time.monotonic() >= deadline:
            break
        arguments = json.loads(row.arguments)
        item = arguments['values'].get('header_media')
        try:
            if not isinstance(item, dict) or (item.get('file_url'), item.get('filename')) not in files:
                raise ValueError('Missing header attachment')
            file, mime = checked_file(item, kind)
        except (ValueError, OSError, DoesNotExistError, PermissionError, ValidationError) as exc:
            frappe.db.set_value(RECIPIENT, row.name, {'status': 'Skipped', 'reason': str(exc)[:500]})
            continue
        if attachment['mode'] == 'static':
            fresh = media_upload(hub, doc)
            if fresh:
                doc.update(fresh)
                frappe.db.set_value('Relay Campaign', doc.name, fresh, update_modified=False)
            media_id = doc.media_id
        else:
            cached = arguments.get('header_upload') or {}
            now = frappe.utils.now_datetime()
            if (cached.get('id') and cached.get('at')
                    and frappe.utils.get_datetime(cached['at']) > frappe.utils.add_to_date(now, days=-MEDIA_DAYS)):
                media_id = cached['id']
            else:
                media_id = upload_media_file(hub, doc.channel, file, mime, kind, item['filename'])
                arguments['header_upload'] = {'id': media_id, 'at': str(now)}
                row.arguments = canonical(arguments)
                frappe.db.set_value(RECIPIENT, row.name, 'arguments', row.arguments, update_modified=False)
                frappe.db.commit()  # Reuse this upload if bulk admission is retried.
        header = {'id': media_id, **({'filename': item['filename']} if kind == 'document' else {})}
        row.message = hub_message(doc, snapshot, row, header)
        ready.append(row)
    return ready


def hub_message(doc, snapshot, row, header_media=None):
    values = json.loads(row.arguments)['values']
    if 'message' in snapshot:
        return {**bulk_sheet.build_message(snapshot['message'], values, doc.media_id), 'to': row.destination}
    return {'operation': 'templates.send', 'to': row.destination, 'name': doc.template_name, 'language': doc.language,
            'components': bulk_sheet.build_components(snapshot['fields'], values, header_media)}


def without_opted_out(doc, rows):
    """A number that opted out after the import is skipped here without a Hub call."""
    _, opted_out = endpoint_facts(doc.channel, [row.destination for row in rows])
    skipped = tuple(row.name for row in rows if row.destination in opted_out)
    if skipped:
        frappe.db.sql(f'''UPDATE `tab{RECIPIENT}` SET status='Skipped', reason=%s, modified=NOW(6)
            WHERE name IN %s AND status='Pending' ''', (OPTED_OUT, skipped))
        frappe.db.commit()
        from relay_core.bulk_updates import changed
        changed(doc.name)
    return [row for row in rows if row.destination not in opted_out]


def within_window(doc, rows):
    """Meta delivers text and media only inside the reply window; other rows fail here without a Hub call."""
    reachable = service_window.open_numbers(doc.channel, [row.destination for row in rows])
    closed = tuple(row.name for row in rows if row.destination not in reachable)
    if closed:
        frappe.db.sql(f'''UPDATE `tab{RECIPIENT}` SET status='Failed', reason=%s, modified=NOW(6)
            WHERE name IN %s AND status='Pending' ''', (OUTSIDE_WINDOW, closed))
        frappe.db.commit()
        from relay_core.bulk_updates import changed
        changed(doc.name)
    return [row for row in rows if row.destination in reachable]


def clear_error(doc):
    frappe.cache.delete_value(RETRIES + doc.name)
    frappe.db.set_value('Relay Campaign', doc.name, 'last_error', '', update_modified=False)
    doc.last_error = ''


def admit(rows, deliveries):
    """Store each row's admission; returns the keys Hub holds (queued or uncertain)."""
    by_key = {row.get('key'): row for row in deliveries if isinstance(row, dict)}
    held = set()
    for row in rows:
        delivery = by_key.get(row.request_key)
        status = ADMISSION.get((delivery or {}).get('state'), 'Uncertain')
        reason = '' if delivery else 'Hub did not confirm admission; the same key is kept'
        if status == 'Failed':
            reason = str(delivery.get('error') or 'Hub refused this row')[:500]
        if status in ('Queued', 'Uncertain'):
            held.add(row.request_key)
        frappe.db.sql(f'''UPDATE `tab{RECIPIENT}` SET status=%s, delivery_id=%s, reason=%s, attempted=1,
            modified=NOW(6) WHERE name=%s AND status='Pending' ''',
            (status, str((delivery or {}).get('id') or ''), reason, row.name))
    return held


def cancel_remaining(doc, deadline):
    """Cancel every row Hub still holds, paging past rows Hub already sends. True when time ran out.
    A Hub refusal keeps the campaign Cancelling with the reason; the refused row is tried again."""
    in_chunks(doc.name, 'Pending', lambda names: frappe.db.sql(f'''UPDATE `tab{RECIPIENT}` SET status='Cancelled',
        modified=NOW(6) WHERE name IN %s AND status='Pending' ''', (names,)))
    hub = whatsapp.client()
    has_attachments = bool(json.loads(doc.column_map or '{}').get('header_attachment'))
    while time.monotonic() < deadline:
        if is_waiting(doc.name, deadline):
            continue
        after = frappe.cache.get_value(CANCEL_AFTER + doc.name) or ''
        rows = frappe.get_all(RECIPIENT, filters={'campaign': doc.name, 'status': 'Queued', 'delivery_id': ['!=', ''],
                              'name': ['>', after]}, fields=['name', 'delivery_id', 'request_key'],
                              order_by='name asc', limit_page_length=CHUNK)
        if not rows:
            finish_cancel(doc)
            return False
        for row in rows:
            if time.monotonic() >= deadline:
                return True
            if not cancel_row(hub, doc, row):
                break
    return True


def cancel_row(hub, doc, row):
    """False when Hub refused, so the row stays Queued and counted as queued."""
    try:
        if hub.call_tool('whatsapp.deliveries', hub_arguments(doc.channel, {'cancel_id': row.delivery_id})).get('cancelled') is True:
            frappe.db.sql(f"UPDATE `tab{RECIPIENT}` SET status='Cancelled' WHERE name=%s AND status='Queued'", row.name)
            from relay_core.bulk_timeline import cancelled
            cancelled(row.request_key)
    except whatsapp.HubError as exc:
        if NOT_QUEUED not in (exc.detail or ''):
            retry_later(doc, CANCEL_REFUSED + whatsapp.failure_message(exc))
            return False
    if doc.last_error:
        clear_error(doc)
    frappe.cache.set_value(CANCEL_AFTER + doc.name, row.name, expires_in_sec=86400)
    frappe.db.commit()
    return True


def finish_cancel(doc):
    frappe.cache.delete_value(CANCEL_AFTER + doc.name)
    frappe.cache.delete_value(RETRIES + doc.name)
    frappe.db.set_value('Relay Campaign', doc.name, {'status': 'Cancelled', 'finished_at': frappe.utils.now_datetime(),
                                                     'last_error': ''})
    frappe.db.commit()


def recover():
    from relay_core.campaign_schedule import start_due
    start_due()
    for row in frappe.get_all('Relay Campaign', filters={'operation': ['in', OPERATIONS],
                              'status': ['in', ['Importing', 'Running', 'Cancelling']]},
                              # Older non-bulk text campaigns must not take the 20 places.
                              or_filters={'template_name': ['is', 'set'], 'arguments': ['like', '%"message"%']},
                              fields=['name', 'status', 'operation', 'template_name', 'arguments'],
                              order_by='modified asc', limit_page_length=20):
        if is_bulk(row):
            enqueue('import_job' if row.status == 'Importing' else 'send_job', row.name)
    from relay_core.bulk_updates import recover as publish_marked
    publish_marked()
