"""Account-scoped template records from Hub status events, scheduled list sync and Core requests."""
import hashlib
import json
import re
import frappe
from relay_core.automation.service import internal_save
from relay_core.hub import safe_text
from relay_core.settings import value as connection_value

EVENT_STATUSES = {'APPROVED','REJECTED','PENDING','PAUSED','DISABLED','IN_APPEAL','DELETED','PENDING_DELETION','REINSTATED','FLAGGED'}
SYNC_PAGES = 20  # Hub pages hold 50 templates.
FIELDS = ('template_name', 'language', 'category', 'status', 'quality', 'reason')
DEFINITIONS = 'relay-template-definitions:'
SYNCED = 'relay-template-synced:'
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


def project(payload, event):
    applied = False
    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            if change.get('field') != 'message_template_status_update': continue
            value = change.get('value') or {}
            identifier, status = value.get('message_template_id'), value.get('event')
            if type(identifier) not in (str, int) or not str(identifier).isdigit() or len(str(identifier)) > 100:
                raise ValueError('Invalid template identity')
            if status not in EVENT_STATUSES:
                raise ValueError('Invalid template status')
            lock_account(event.account)
            doc, new = record(event.account, identifier)
            applied = True
            if not new and int(doc.hub_event_id) >= int(event.hub_event_id): continue
            doc.update({'template_name':value.get('message_template_name'), 'language':value.get('message_template_language'),
                        'status':status, 'reason':event_reason(value), 'hub_event_id':event.hub_event_id})
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


def store(account, rows, complete=False):
    """Upsert listed templates; a complete list also marks missing local rows deleted."""
    lock_account(account)
    changed, seen = False, set()
    for row in rows:
        identifier, values = list_values(row)
        seen.add(identifier)
        doc, new = record(account, identifier)
        if new or any(str(doc.get(key) or '') != str(value) for key, value in values.items()):
            doc.update(values)
            internal_save(doc, new=new)
            changed = True
    if complete:
        for name in frappe.get_all('Relay WhatsApp Template', pluck='name', filters={'account':account,
                'status':['!=', 'DELETED'], **({'template_id':['not in', list(seen)]} if seen else {})}):
            doc = frappe.get_doc('Relay WhatsApp Template', name)
            doc.status = 'DELETED'
            internal_save(doc)
            changed = True
    if changed:
        publish()
    return changed


def listed(hub):
    rows, after = [], None
    for _ in range(SYNC_PAGES):
        page = hub.execute({'operation':'templates.list', **({'after':after} if after else {})})
        rows += page.get('data') or []
        paging = page.get('paging') or {}
        cursor = (paging.get('cursors') or {}).get('after')
        if not paging.get('has_more') or not cursor or cursor == after:
            return rows, True
        after = cursor
    return rows, False


def sync():
    """Scheduled local copy; Meta may deliver WABA status webhooks to another site."""
    account = connection_value('relay_hub_account')
    if not account or not frappe.db.exists('Relay Channel', {'account':account, 'channel':'WhatsApp', 'enabled':1}):
        return False
    from relay_core.hub import HubError
    from relay_core.whatsapp import checked_client
    try:
        hub, capabilities = checked_client()
        if not capabilities.get('templates'):
            return False
        rows, complete = listed(hub)
    except (HubError, ValueError, frappe.ValidationError) as error:
        frappe.log_error('Relay WhatsApp template sync failed', getattr(error, 'detail', '') or str(error))
        return False
    changed = store(account, rows, complete)
    remember(account, rows)
    frappe.cache.set_value(SYNCED + account, {'synced_at': frappe.utils.now(), 'templates': len(rows)})
    return changed


def remember(account, rows):
    """Cache listed template content so sends render without another Hub list."""
    for row in rows:
        if row.get('name') and row.get('language'):
            frappe.cache.hset(DEFINITIONS + account, row['name'] + '|' + row['language'],
                              {key: row.get(key) for key in ('parameter_format', 'components')})


def definition(name, language):
    """Template content from the sync cache, or from one Hub list scan on a miss."""
    account = connection_value('relay_hub_account')
    key = f'{name}|{language}'
    found = frappe.cache.hget(DEFINITIONS + account, key)
    if found is None:
        from relay_core.hub import HubError
        from relay_core.whatsapp import checked_client
        try:
            rows, _ = listed(checked_client()[0])
        except (HubError, ValueError):
            return None
        remember(account, rows)
        found = frappe.cache.hget(DEFINITIONS + account, key)
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
            result['buttons'] = [button['text'] for button in component.get('buttons') or [] if button.get('text')]
    return {key: value for key, value in result.items() if value}


def message_content(arguments, template=None):
    """Stored outgoing template message: the rendered body as text, the rest beside the template name."""
    sent = {key: arguments[key] for key in ('name', 'language', 'components') if key in arguments}
    template = template or definition(sent['name'], sent.get('language') or '')
    rendered = render(template, sent.get('components')) if template else {}
    body = rendered.pop('body', '') or 'Template: ' + sent['name']
    return {'kind': 'text', 'text': body[:4096], 'template': {**sent, **rendered}}


@frappe.whitelist(methods=['GET'])
def sync_status():
    """When the scheduled local template copy last finished."""
    from relay_core.permissions import require_access
    require_access()
    return frappe.cache.get_value(SYNCED + (connection_value('relay_hub_account') or '')) or {'synced_at': None, 'templates': 0}


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
        frappe.cache.delete_value(DEFINITIONS + account)
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
