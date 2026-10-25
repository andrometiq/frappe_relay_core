"""WhatsApp template campaigns from an uploaded sheet, pushed to Hub 50 rows at a time."""
import hashlib
import json
import time
import frappe
from redis.exceptions import LockError
from relay_core import bulk_sheet, whatsapp
from relay_core.automation.contracts import canonical
from relay_core.automation.service import internal_save
from relay_core.identity import default_region
from relay_core.permissions import require_access
from relay_core.settings import value as connection_value

RECIPIENT = 'Relay Campaign Recipient'
BATCH = 50
CHUNK = 1000
HIGH_WATER = 1000
LOW_WATER = 500
DEFAULT_RATE = 50
SLICE_SECONDS = 45
JOB_TIMEOUT = 1800  # A 100,000-row import; a send slice ends long before.
RETRY_SECONDS = 60
WAIT = 'relay-bulk-wait:'
CANCEL_AFTER = 'relay-bulk-cancel-after:'
ADMISSION = {'queued': 'Queued', 'submitting': 'Queued', 'submitted': 'Queued', 'rejected': 'Failed',
             'uncertain': 'Uncertain', 'cancelled': 'Cancelled'}


def is_bulk(doc):
    return doc.operation == 'templates.send' and bool(doc.template_name)


def bulk(name, statuses=None):
    require_access(manage=True)
    doc = frappe.get_doc('Relay Campaign', name)
    doc.check_permission('read')
    if not is_bulk(doc):
        frappe.throw('This is not a WhatsApp template campaign')
    if statuses and doc.status not in statuses:
        frappe.throw(f'Campaign is {doc.status}')
    return doc


def whatsapp_channel(channel=None):
    filters = {'channel': 'WhatsApp', 'account': connection_value('relay_hub_account'), 'enabled': 1}
    if channel:
        filters['name'] = channel
    rows = frappe.get_all('Relay Channel', filters=filters, pluck='name', limit_page_length=2)
    if len(rows) != 1:
        frappe.throw('Choose the enabled WhatsApp channel for this Hub account')
    return rows[0]


def approved_template(hub, name, language):
    from relay_core.whatsapp_templates import overlay
    after = ''
    for _ in range(20):
        page = overlay(hub.execute({'operation': 'templates.list', **({'after': after} if after else {})}))
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
def create(title, template_name, language, channel=None, reply_window_hours=72):
    require_access(manage=True)
    title = (title or '').strip() if isinstance(title, str) else ''
    if not 3 <= len(title) <= 100 or any(c in title for c in '/\\%#?<>'):
        frappe.throw('Give the campaign a readable title of 3-100 characters')
    hours = frappe.utils.cint(reply_window_hours)
    if not 1 <= hours <= 720:
        frappe.throw('Reply window must be 1-720 hours')
    if frappe.db.exists('Relay Campaign', title):
        frappe.throw('A campaign with this title already exists')
    target = whatsapp_channel(channel)
    try:
        hub, _ = whatsapp.checked_client()
        snapshot = template_snapshot(approved_template(hub, template_name, language))
    except whatsapp.HubError as exc:
        frappe.throw(whatsapp.failure_message(exc))
    except ValueError as exc:
        frappe.throw(str(exc))
    doc = frappe.get_doc(dict(doctype='Relay Campaign', title=title, channel=target, operation='templates.send',
        template_name=template_name, language=language, arguments=canonical(snapshot),
        status='Draft', account=connection_value('relay_hub_account'), country=default_region(),
        reply_window_hours=hours, request_key='bulk-' + hashlib.sha256(title.encode()).hexdigest()[:40]))
    internal_save(doc, new=True)
    return read(doc.name)


def source_path(file_url):
    if not isinstance(file_url, str) or not file_url.lower().endswith(('.xlsx', '.csv')):
        frappe.throw('Upload a .xlsx or .csv file')
    name = frappe.db.get_value('File', {'file_url': file_url}, 'name')
    if not name:
        frappe.throw('Uploaded file not found')
    file = frappe.get_doc('File', name)
    file.check_permission('read')
    return file.get_full_path()


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
    doc.source_file = file_url
    internal_save(doc)
    fields = json.loads(doc.arguments)['fields']
    return {'columns': header, 'sample': sample, 'fields': fields, 'mapping': bulk_sheet.suggest(header, fields)}


@frappe.whitelist(methods=['POST'])
def import_rows(name, mapping):
    doc = bulk(name, ('Draft',))
    if not doc.source_file:
        frappe.throw('Upload the recipient file first')
    mapping = frappe.parse_json(mapping) if isinstance(mapping, str) else mapping
    try:
        header, _ = bulk_sheet.columns(source_path(doc.source_file), sample=1)
        mapping = bulk_sheet.check_mapping(mapping, header, json.loads(doc.arguments)['fields'])
    except ValueError as exc:
        frappe.throw(str(exc))
    doc.column_map, doc.status, doc.last_error = canonical(mapping), 'Importing', ''
    internal_save(doc)
    enqueue('import_job', name)
    return read(name)


def enqueue(method, name, step=0):
    """Short jobs at the back of the queue. A slice continues under the other of two job IDs,
    because its own ID is still running and deduplication would drop it."""
    frappe.enqueue(f'relay_core.bulk_campaigns.{method}', name=name, queue='long', timeout=JOB_TIMEOUT,
                   job_id=f'relay-bulk-{method}:{name}:{step % 2}', deduplicate=True, enqueue_after_commit=True,
                   **({'step': step} if step else {}))


def import_job(name):
    doc = frappe.get_doc('Relay Campaign', name)
    if doc.status != 'Importing':
        return
    remove_unsent(name)
    mapping, fields = json.loads(doc.column_map), json.loads(doc.arguments)['fields']
    seen, chunk = set(), []
    try:
        for number, row in bulk_sheet.read_rows(source_path(doc.source_file)):
            destination, values, problem = bulk_sheet.prepare_row(row, mapping, fields, doc.country)
            if not problem and destination in seen:
                problem = 'Duplicate number'
            seen.add(destination)
            chunk.append((number, destination, values, problem))
            if len(chunk) == CHUNK:
                insert_chunk(doc, chunk)
                chunk = []
        insert_chunk(doc, chunk)
        doc.last_error = ''
    except ValueError as exc:
        frappe.db.rollback()
        remove_unsent(name)  # Chunks before the error were committed; none of them may start.
        doc.last_error = str(exc)[:500]
    doc.status = 'Draft'
    internal_save(doc)
    frappe.db.commit()
    from relay_core.bulk_updates import changed
    changed(name)


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
                               fields=['name', 'endpoint_key', 'relay_contact', 'verified'], limit_page_length=0)
    verified = [e for e in endpoints if e.verified]
    people = dict(frappe.get_all('Relay Contact', filters={'name': ['in', [e.relay_contact for e in verified]]},
                                 fields=['name', 'contact'], as_list=True, limit_page_length=0)) if verified else {}
    denied = set(frappe.get_all('Relay Channel Preference', filters={'endpoint': ['in', [e.name for e in endpoints]],
                 'consent': 'Denied'}, pluck='endpoint', limit_page_length=0)) if endpoints else set()
    contacts = {keys[e.endpoint_key]: people.get(e.relay_contact) for e in verified}
    return contacts, {keys[e.endpoint_key] for e in endpoints if e.name in denied}


def insert_chunk(doc, chunk):
    if not chunk:
        return
    contacts, opted_out = endpoint_facts(doc.channel, [d for _, d, _, p in chunk if d and not p])
    now, user = frappe.utils.now(), frappe.session.user
    values = []
    for number, destination, arguments, problem in chunk:
        if not problem and destination in opted_out:
            problem = 'Opted out'
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
    return {**{key: doc.get(key) for key in ('name', 'title', 'channel', 'status', 'template_name', 'language',
               'source_file', 'country', 'reply_window_hours', 'started_at', 'finished_at', 'last_error')},
            'mapping': json.loads(doc.column_map) if doc.column_map else None,
            'fields': json.loads(doc.arguments)['fields'], 'counts': counts(doc), 'issues': issues,
            'recipients': rows[:50], 'next': rows[49].sheet_row if len(rows) > 50 else None}


def counts(doc):
    return {key: doc.get(key + '_count') or 0 for key in
            ('total', 'skipped', 'queued', 'sent', 'delivered', 'read', 'failed', 'replied')}


@frappe.whitelist(methods=['POST'])
def control(name, action):
    transitions = {'start': (('Draft',), 'Running'), 'pause': (('Running',), 'Paused'),
                   'resume': (('Paused',), 'Running'), 'cancel': (('Draft', 'Running', 'Paused'), 'Cancelling')}
    if action not in transitions:
        frappe.throw('Invalid campaign action')
    allowed, target = transitions[action]
    require_access(manage=True)
    if target == 'Running':
        check_ready(bulk(name, allowed))  # Hub calls stay outside the lock.
    with frappe.cache.lock('relay-bulk-control:' + name, timeout=30):
        doc = bulk(name, allowed)
        if target == 'Running':
            doc.execution_user, doc.started_at = frappe.session.user, doc.started_at or frappe.utils.now_datetime()
            from relay_core.bulk_updates import open_reply_window
            open_reply_window(doc.reply_window_hours)
        doc.status, doc.last_error = target, ''
        internal_save(doc)
    if target in ('Running', 'Cancelling'):
        enqueue('send_job', name)
    return read(name)


def check_ready(doc):
    whatsapp_channel(doc.channel)
    if doc.status == 'Draft' and doc.last_error:
        frappe.throw('The last import failed. Fix the file and import the recipients again')
    if not frappe.db.exists(RECIPIENT, {'campaign': doc.name, 'status': 'Pending'}):
        frappe.throw('Import recipients with at least one valid row first')
    try:
        hub, _ = whatsapp.checked_client()
        approved_template(hub, doc.template_name, doc.language)
    except whatsapp.HubError as exc:
        frappe.throw(whatsapp.failure_message(exc))


def send_job(name, step=0):
    """One slice of at most SLICE_SECONDS; it enqueues the next slice instead of sleeping."""
    deadline, more = time.monotonic() + SLICE_SECONDS, False
    try:
        with frappe.cache.lock('relay-bulk-send:' + name, timeout=SLICE_SECONDS + 300, blocking_timeout=1):
            doc = frappe.get_doc('Relay Campaign', name)
            if doc.status == 'Cancelling':
                more = cancel_remaining(doc, deadline)
            elif doc.status == 'Running' and is_due(name):
                frappe.cache.delete_value(WAIT + name)
                more = push(doc, deadline)
    except LockError:
        return  # Another worker owns this campaign.
    from relay_core.bulk_updates import changed
    changed(name)
    if more:
        enqueue('send_job', name, step + 1)
    frappe.db.commit()


def is_due(name):
    return frappe.utils.flt(frappe.cache.get_value(WAIT + name)) <= time.time()


def wait(name, seconds):
    """Backpressure and retry: the next Hub progress update or recovery run after this time resumes sending."""
    frappe.cache.set_value(WAIT + name, time.time() + seconds, expires_in_sec=int(seconds) + 3600)


def resume(name):
    """Called when Hub reports progress for this campaign; restarts a waiting campaign once it is due."""
    if frappe.cache.get_value(WAIT + name) and is_due(name):
        frappe.cache.delete_value(WAIT + name)
        enqueue('send_job', name)


def push(doc, deadline):
    """Push Pending rows 50 at a time. True when the slice ran out of time with rows left."""
    snapshot = json.loads(doc.arguments)
    hub = whatsapp.client()
    while time.monotonic() < deadline:
        if frappe.db.get_value('Relay Campaign', doc.name, 'status') != 'Running':
            return False
        rows = frappe.db.sql(f'''SELECT name, request_key, destination, arguments FROM `tab{RECIPIENT}`
            WHERE campaign=%s AND status='Pending' ORDER BY sheet_row LIMIT {BATCH}''', doc.name, as_dict=True)
        if not rows:
            return False
        for row in rows:
            row.components = bulk_sheet.build_components(snapshot['fields'], json.loads(row.arguments)['values'])
        messages = [{'key': row.request_key, 'message': {'operation': 'templates.send', 'to': row.destination,
                     'name': doc.template_name, 'language': doc.language, 'components': row.components}}
                    for row in rows]
        try:
            result = hub.call_tool('whatsapp.bulk', {'messages': messages})
        except whatsapp.HubError as exc:
            # Same keys are pushed again after the wait; Hub returns the rows it already holds.
            frappe.db.set_value('Relay Campaign', doc.name, 'last_error', whatsapp.failure_message(exc)[:500],
                                update_modified=False)
            wait(doc.name, RETRY_SECONDS)
            return False
        admitted = admit(rows, result.get('deliveries') or [])
        from relay_core.bulk_timeline import record
        record(doc, snapshot, [row for row in rows if row.request_key in admitted])
        if doc.last_error:  # Hub accepted again after a retry.
            frappe.db.set_value('Relay Campaign', doc.name, 'last_error', '', update_modified=False)
            doc.last_error = ''
        frappe.db.commit()
        from relay_core.bulk_updates import changed
        changed(doc.name)
        queued = frappe.utils.cint(result.get('queued'))
        if queued >= HIGH_WATER:
            rate = frappe.utils.cint(result.get('messages_per_second')) or DEFAULT_RATE
            wait(doc.name, (queued - LOW_WATER) / rate)
            return False
    return True


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
    """Cancel every row Hub still holds, paging past rows Hub already sends. True when time ran out."""
    in_chunks(doc.name, 'Pending', lambda names: frappe.db.sql(f'''UPDATE `tab{RECIPIENT}` SET status='Cancelled',
        modified=NOW(6) WHERE name IN %s AND status='Pending' ''', (names,)))
    hub = whatsapp.client()
    from relay_core.bulk_timeline import cancelled
    while True:
        after = frappe.cache.get_value(CANCEL_AFTER + doc.name) or ''
        rows = frappe.get_all(RECIPIENT, filters={'campaign': doc.name, 'status': 'Queued', 'delivery_id': ['!=', ''],
                              'name': ['>', after]}, fields=['name', 'delivery_id', 'request_key'],
                              order_by='name asc', limit_page_length=CHUNK)
        if not rows:
            break
        for row in rows:
            if time.monotonic() >= deadline:
                return True
            try:
                if hub.call_tool('whatsapp.deliveries', {'cancel_id': row.delivery_id}).get('cancelled') is True:
                    frappe.db.sql(f"UPDATE `tab{RECIPIENT}` SET status='Cancelled' WHERE name=%s AND status='Queued'", row.name)
                    cancelled(row.request_key)
            except whatsapp.HubError:
                pass  # Already sending; its Hub update records the real outcome.
            frappe.cache.set_value(CANCEL_AFTER + doc.name, row.name, expires_in_sec=86400)
            frappe.db.commit()
    frappe.cache.delete_value(CANCEL_AFTER + doc.name)
    frappe.db.set_value('Relay Campaign', doc.name, {'status': 'Cancelled', 'finished_at': frappe.utils.now_datetime()})
    frappe.db.commit()
    return False


def recover():
    for row in frappe.get_all('Relay Campaign', filters={'operation': 'templates.send', 'template_name': ['is', 'set'],
                              'status': ['in', ['Importing', 'Running', 'Cancelling']]}, fields=['name', 'status'],
                              order_by='modified asc', limit_page_length=20):
        enqueue('import_job' if row.status == 'Importing' else 'send_job', row.name)
    from relay_core.bulk_updates import recover as publish_marked
    publish_marked()
