"""Account-scoped template records from Hub status events, scheduled list sync and Core requests."""
import hashlib
import json
import re
import frappe
from relay_core.automation.service import internal_save
from relay_core.hub import safe_text
from relay_core.settings import value as connection_value

EVENT_STATUSES = {'APPROVED','REJECTED','PENDING','PAUSED','DISABLED','IN_APPEAL','DELETED','PENDING_DELETION','REINSTATED','FLAGGED'}
QUALITY_SCORES = {'GREEN','YELLOW','RED','UNKNOWN'}
TEMPLATE_FIELDS = {'message_template_status_update', 'message_template_quality_update'}
SYNC_PAGES = 20  # Hub pages hold 50 templates.
FIELDS = ('template_name', 'language', 'category', 'status', 'quality', 'reason')
DEFINITIONS = 'relay-template-definitions:'
SYNCED = 'relay-template-synced:'
SYNC_REQUESTED = 'relay-template-sync-requested:'
SYNC_AFTER_SECONDS = 60
PLACEHOLDER = re.compile(r'\{\{\s*([a-z0-9_]+)\s*\}\}')


def record(account, identifier):
    key = hashlib.sha256((account + ':' + str(identifier)).encode()).hexdigest()
    name = frappe.db.get_value('Relay WhatsApp Template', {'record_key':key}, 'name')
    if name:
        return frappe.get_doc('Relay WhatsApp Template', name), False
    return frappe.get_doc({'doctype':'Relay WhatsApp Template', 'record_key':key, 'account':account,
                           'template_id':str(identifier), 'hub_event_id':'0'}), True


def lock_account(account):
    # Serializes webhook, sync and request writes for one account.
    frappe.db.get_value('Relay Channel', {'account':account, 'channel':'WhatsApp'}, 'name', for_update=True)


def publish():
    frappe.publish_realtime('relay_changed', {'kind':'templates'},
        room=frappe.realtime.get_doctype_room('Relay WhatsApp Template'), after_commit=True)


def event_reason(value):
    info = value.get('other_info') if isinstance(value.get('other_info'), dict) else {}
    parts = [value.get('reason'), info.get('title'), info.get('description')]
    return ' · '.join(text for text in map(safe_text, parts) if text and text != 'NONE')


def template_event(payload):
    """True when every change of a Meta envelope is a template status or quality update."""
    try:
        changes = [change for entry in payload['entry'] for change in entry['changes']]
        return bool(changes) and all(change.get('field') in TEMPLATE_FIELDS for change in changes)
    except (KeyError, TypeError, AttributeError):
        return False


def event_values(field, value):
    """The template fields a status or quality webhook sets."""
    if field == 'message_template_quality_update':
        quality = value.get('new_quality_score')
        if quality not in QUALITY_SCORES:
            raise ValueError('Invalid template quality')
        return {'quality':quality}
    if value.get('event') not in EVENT_STATUSES:
        raise ValueError('Invalid template status')
    return {'status':value['event'], 'reason':event_reason(value)}


def project(payload, event):
    """Apply Meta template status and quality updates; the envelope's entry id is the WABA of the template."""
    applied = False
    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            if change.get('field') not in TEMPLATE_FIELDS: continue
            value = change.get('value') or {}
            identifier = value.get('message_template_id')
            if type(identifier) not in (str, int) or not str(identifier).isdigit() or len(str(identifier)) > 100:
                raise ValueError('Invalid template identity')
            values = event_values(change['field'], value)
            lock_account(event.account)
            doc, new = record(event.account, identifier)
            if new and 'status' not in values: continue  # The next list sync brings the unknown template with its quality.
            applied = True
            if not new and int(doc.hub_event_id) >= int(event.hub_event_id): continue
            doc.update({'template_name':value.get('message_template_name'), 'language':value.get('message_template_language'),
                        **values, 'hub_event_id':event.hub_event_id,
                        'waba_id':waba_of(entry.get('id')) or doc.get('waba_id')})
            internal_save(doc, new=new)
            publish()
    return applied


def list_values(row):
    identifier, status = str(row.get('id') or ''), str(row.get('status') or '').upper()
    if not identifier.isdigit() or len(identifier) > 100 or not re.fullmatch(r'[A-Z_]{1,40}', status):
        raise ValueError('Hub returned an invalid template row')
    values = {'template_name':row.get('name'), 'language':row.get('language'), 'category':row.get('category'),
              'status':status, 'quality':(row.get('quality_score') or {}).get('score')}
    reason = safe_text(row.get('rejected_reason'))
    if reason and reason != 'NONE':
        values['reason'] = reason
    return identifier, {key:value for key, value in values.items() if value}


def waba_of(value):
    value = str(value or '')
    return value if value.isdigit() and len(value) <= 40 else ''


def store(account, rows, complete=False, waba=''):
    """Upsert listed templates of one WABA; a complete list also marks missing local rows of it deleted.

    Template ids are unique across Meta, so the record key stays (account, template id)."""
    lock_account(account)
    changed, seen = False, set()
    for row in rows:
        identifier, values = list_values(row)
        if waba:
            values['waba_id'] = waba
        seen.add(identifier)
        doc, new = record(account, identifier)
        if new or any(str(doc.get(key) or '') != str(value) for key, value in values.items()):
            doc.update(values)
            internal_save(doc, new=new)
            changed = True
    if complete:
        for name in frappe.get_all('Relay WhatsApp Template', pluck='name', filters={'account':account,
                'status':['!=', 'DELETED'], **({'waba_id':waba} if waba else {}),
                **({'template_id':['not in', list(seen)]} if seen else {})}):
            doc = frappe.get_doc('Relay WhatsApp Template', name)
            doc.status = 'DELETED'
            internal_save(doc)
            changed = True
    if changed:
        publish()
    return changed


def listed(hub, channel=None):
    """Every template of the channel's WABA, and whether the list is complete."""
    from relay_core.hub_channels import hub_arguments
    rows, after = [], None
    for _ in range(SYNC_PAGES):
        page = hub.execute(hub_arguments(channel, {'operation':'templates.list', **({'after':after} if after else {})}))
        rows += page.get('data') or []
        paging = page.get('paging') or {}
        cursor = (paging.get('cursors') or {}).get('after')
        if not paging.get('has_more') or not cursor or cursor == after:
            return rows, True
        after = cursor
    return rows, False


def sync(notify=False):
    """Scheduled or requested local copy; Meta may deliver WABA status webhooks to another site.

    `notify` publishes the finished sync even without changes, so an open list leaves its syncing state."""
    account = connection_value('relay_hub_account')
    if not account or not frappe.db.exists('Relay Channel', {'account':account, 'channel':'WhatsApp', 'enabled':1}):
        return False
    from relay_core.hub import HubError
    from relay_core.whatsapp import checked_client
    changed, total = False, 0
    for channel in waba_channels(account):
        try:
            hub, capabilities = checked_client()
            if not capabilities.get('templates'):
                return False
            rows, complete = listed(hub, channel)
        except (HubError, ValueError, frappe.ValidationError) as error:
            frappe.log_error('Relay WhatsApp template sync failed', getattr(error, 'detail', '') or str(error))
            if notify: publish()
            return False
        changed = store(account, rows, complete, channel.waba_id or '') or changed
        remember(account, rows, channel.waba_id)
        total += len(rows)
    frappe.cache.set_value(SYNCED + account, {'synced_at': frappe.utils.now(), 'templates': total})
    if notify and not changed: publish()
    return changed


def waba_channels(account):
    """One enabled WhatsApp channel per WABA; templates are synced once per WABA, not per number."""
    rows = frappe.get_all('Relay Channel', fields=['name', 'channel', 'account', 'hub_channel', 'waba_id'],
                          filters={'account': account, 'channel': 'WhatsApp', 'enabled': 1},
                          order_by='is_default desc, creation asc')
    return list({row.waba_id or '': row for row in reversed(rows)}.values())


def definitions_key(account, waba=None):
    return DEFINITIONS + account + (':' + waba if waba else '')


def remember(account, rows, waba=None):
    """Cache listed template rows per WABA so sends render and the Templates tab lists without another Hub list.

    Two WABAs can have a template with the same name and language, so the WABA is part of the key."""
    for row in rows:
        if row.get('name') and row.get('language'):
            frappe.cache.hset(definitions_key(account, waba), row['name'] + '|' + row['language'], row)


def template_channel(account, channel=None):
    """The named channel, or the site default WhatsApp channel when none is named; its WABA keys the cache."""
    rows = frappe.get_all('Relay Channel', fields=['name', 'waba_id'], order_by='is_default desc, creation asc',
                          filters={'name': channel} if channel else {'account': account, 'channel': 'WhatsApp', 'enabled': 1},
                          limit_page_length=1)
    return rows[0] if rows else frappe._dict(name=channel, waba_id='')


def definition(name, language, channel=None):
    """Template content of the channel's WABA (the default channel's without one) from the sync cache,
    or from one Hub list scan of that channel on a miss."""
    account = connection_value('relay_hub_account')
    target = template_channel(account, channel)
    waba = target.waba_id or None
    key = f'{name}|{language}'
    found = frappe.cache.hget(definitions_key(account, waba), key)
    if found is None:
        from relay_core.hub import HubError
        from relay_core.whatsapp import checked_client
        try:
            rows, _ = listed(checked_client()[0], target.name)
        except (HubError, ValueError):
            return None
        remember(account, rows, waba)
        found = frappe.cache.hget(definitions_key(account, waba), key)
    return found


def parameter_value(parameter):
    kind = parameter.get('type')
    if kind == 'text':
        return parameter.get('text')
    return (parameter.get(kind) or {}).get('fallback_value') if kind in ('currency', 'date_time') else None


def render(template, sent):
    """Header, body, footer and button labels with the sent parameter values filled in."""
    values = {}
    for component in sent or []:
        for index, parameter in enumerate(component.get('parameters') or [], 1):
            value = parameter_value(parameter)
            if isinstance(value, str):
                values[(str(component.get('type')).upper(), parameter.get('parameter_name') or str(index))] = value

    def fill(kind, text):
        return PLACEHOLDER.sub(lambda match: values.get((kind, match.group(1)), match.group(0)), text or '')

    result = {}
    for component in template.get('components') or []:
        kind = str(component.get('type') or '').upper()
        if kind == 'HEADER' and str(component.get('format') or 'TEXT').upper() == 'TEXT':
            result['header'] = fill(kind, component.get('text'))
        elif kind == 'BODY':
            result['body'] = fill(kind, component.get('text'))
        elif kind == 'FOOTER' and component.get('text'):
            result['footer'] = component['text']
        elif kind == 'BUTTONS':
            # Meta sets the copy code label itself, so the definition can leave text out.
            labels = [button.get('text') or ('Copy offer code' if button.get('type') == 'COPY_CODE' else '')
                      for button in component.get('buttons') or []]
            result['buttons'] = [label for label in labels if label]
    return {key: value for key, value in result.items() if value}


def message_content(arguments, template=None, channel=None):
    """Stored outgoing template message: the rendered body as text, the rest beside the template name."""
    sent = {key: arguments[key] for key in ('name', 'language', 'components') if key in arguments}
    template = template or definition(sent['name'], sent.get('language') or '', channel)
    rendered = render(template, sent.get('components')) if template else {}
    body = rendered.pop('body', '') or 'Template: ' + sent['name']
    document = next((parameter['document'] for component in sent.get('components') or []
                     if str(component.get('type')).lower() == 'header'
                     for parameter in component.get('parameters') or [] if parameter.get('type') == 'document'), None)
    if document:
        rendered['document'] = {'file_name': str(document.get('filename') or 'document.pdf')[:120]}
    return {'kind': 'text', 'text': body[:4096], 'template': {**sent, **rendered}}


@frappe.whitelist(methods=['GET'])
def sync_status():
    """When the scheduled local template copy last finished."""
    from relay_core.permissions import require_access
    require_access()
    return frappe.cache.get_value(SYNCED + (connection_value('relay_hub_account') or '')) or {'synced_at': None, 'templates': 0}


@frappe.whitelist(methods=['GET'])
def directory(channel=None):
    """The local template copy in the Hub list shape, without a Hub call; a stale copy queues one background sync.

    `channel` limits the list to the templates of that number's WABA. Each row takes its content from its own WABA."""
    from relay_core.permissions import require_access
    require_access()
    account = connection_value('relay_hub_account') or ''
    waba = template_channel(account, channel).waba_id if channel else None
    rows = frappe.get_all('Relay WhatsApp Template', filters={'account':account, 'status':['!=', 'DELETED'],
                                                             **({'waba_id': waba} if waba else {})},
        fields=['template_id', 'template_name', 'language', 'category', 'status', 'quality', 'reason', 'waba_id'],
        order_by='template_name asc, language asc', limit_page_length=SYNC_PAGES * 50)
    definitions = {row_waba: cached_definitions(account, row_waba) for row_waba in {row.get('waba_id') or '' for row in rows}}
    data = [local_row(row, definitions[row.get('waba_id') or ''].get(f'{row.template_name}|{row.language}')) for row in rows]
    synced = frappe.cache.get_value(SYNCED + account) or {'synced_at': None, 'templates': 0}
    missing = any(not row.get('components') for row in data)
    return {'data': data, 'sync': dict(synced, syncing=request_sync(account, synced, missing))}


def cached_definitions(account, waba):
    return {key.decode() if isinstance(key, bytes) else key: value
            for key, value in (frappe.cache.hgetall(definitions_key(account, waba)) or {}).items()}


def local_row(row, listed=None):
    """The last listed Hub row with the newer local status, quality and rejection reason."""
    values = {'id':row.template_id, 'name':row.template_name, 'language':row.language, 'category':row.category,
              'status':row.status, 'quality_score':{'score':row.quality} if row.quality else None, 'rejected_reason':row.reason}
    return {**(listed or {}), **{key:value for key, value in values.items() if value is not None}}


def request_sync(account, synced, missing_content=False):
    """Queue one background sync when the copy is stale; at most one request per account each minute."""
    if not account: return False
    synced_at = synced.get('synced_at')
    fresh = synced_at and frappe.utils.time_diff_in_seconds(frappe.utils.now(), synced_at) < SYNC_AFTER_SECONDS
    if fresh and not missing_content: return False
    if not frappe.cache.set(frappe.cache.make_key(SYNC_REQUESTED + account), '1', nx=True, ex=SYNC_AFTER_SECONDS):
        return False
    frappe.enqueue('relay_core.whatsapp_templates.sync', queue='short', timeout=300, notify=True)
    return True


def record_request(operation, arguments, result=None, error=''):
    """Audit one template management request without uploaded bytes or credentials."""
    request = {key:value for key, value in arguments.items() if key != 'content_base64'}
    if 'content_base64' in arguments:
        request['content_bytes'] = len(arguments['content_base64']) * 3 // 4
    internal_save(frappe.get_doc({'doctype':'Relay WhatsApp Template Request', 'operation':operation,
        'template_name':arguments.get('name'), 'language':arguments.get('language'),
        'account':connection_value('relay_hub_account'), 'status':'Failed' if error else 'Succeeded',
        'request':json.dumps(request), 'result':json.dumps(result) if result is not None else None,
        'error':error}), new=True)


def apply_request(operation, arguments, result):
    """Reflect a successful create or delete locally before Meta's status arrives."""
    account = connection_value('relay_hub_account')
    if operation == 'templates.create' and result.get('id'):
        store(account, [{'id':result['id'], 'name':arguments.get('name'), 'language':arguments.get('language'),
                         'category':result.get('category') or arguments.get('category'),
                         'status':result.get('status') or 'PENDING'}])
    if operation in ('templates.update', 'templates.delete'):
        frappe.cache.delete_keys(DEFINITIONS + account)
    if operation == 'templates.delete':
        filters = {'account':account, 'template_name':arguments.get('name'), 'status':['!=', 'DELETED']}
        if arguments.get('id'):
            filters['template_id'] = str(arguments['id'])
        lock_account(account)
        names = frappe.get_all('Relay WhatsApp Template', filters=filters, pluck='name')
        for name in names:
            doc = frappe.get_doc('Relay WhatsApp Template', name)
            doc.status = 'DELETED'
            internal_save(doc)
        if names:
            publish()


def overlay(page):
    """Hub supplies live template content and status; local records add Meta's rejection reason."""
    rows = page.get('data') or []
    if not rows: return page
    reasons = {row.template_id:row.reason for row in frappe.get_all('Relay WhatsApp Template',
        filters={'account':connection_value('relay_hub_account'),'template_id':['in',[str(row['id']) for row in rows]]},
        fields=['template_id','reason']) if row.reason}
    return dict(page, data=[dict(row, rejected_reason=row['rejected_reason'])
        if row.get('rejected_reason') not in (None, '', 'NONE') else
        dict(row, rejected_reason=reasons[str(row['id'])]) if str(row['id']) in reasons else row for row in rows])
