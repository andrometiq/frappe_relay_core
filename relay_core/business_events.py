"""Business transactions capture immutable intents; workers use the action journal."""
from contextvars import ContextVar
import hashlib
import json
import frappe
from relay_core.ai.tools import as_user
from relay_core.permissions import require_access
from relay_core.business_references import RELAY_DOCTYPES
from relay_core.automation.service import internal_save
from relay_core.inbound import retry_callback

FIELDS = ('title', 'enabled', 'source_doctype', 'event', 'recipient_field', 'business_doctype',
          'channel', 'run_as_user', 'template', 'parameter_mapping', 'contact',
          'use_preferences', 'telegram_body', 'email_subject', 'email_body', 'email_signature')
EVENTS = ('after_insert', 'on_submit', 'on_cancel')
RULE_PAIRS_CACHE_KEY = 'relay_business_event_rule_pairs'
outgoing_event = ContextVar('relay_outgoing_business_event', default=None)


def mapping(rule):
    value = json.loads(rule.parameter_mapping or '[]')
    if not isinstance(value, list) or len(value) > 20 or any(not isinstance(item, str) for item in value):
        raise ValueError('Parameters must be a list of up to 20 source fields')
    meta = frappe.get_meta(rule.source_doctype)
    for key in value:
        if key == 'items_summary':
            field = meta.get_field('items')
            if not field or field.fieldtype != 'Table': raise ValueError('Source needs an items table')
            continue
        field = meta.get_field(key)
        if key != 'name' and (not field or field.fieldtype in ('Table', 'Password', 'Code', 'HTML')):
            raise ValueError('Use scalar source fields or items_summary')
    return value


def approved(rule):
    template = frappe.get_doc('Relay WhatsApp Template', rule.template)
    channel = frappe.get_doc('Relay Channel', rule.channel)
    if template.status != 'APPROVED' or not template.template_name or not template.language or template.account != channel.account or channel.channel != 'WhatsApp' or not channel.enabled:
        raise ValueError('Choose an approved template on an enabled WhatsApp channel')
    return template


def validate_rule(rule):
    require_access(configure=True)
    if rule.event not in EVENTS or rule.source_doctype in RELAY_DOCTYPES:
        raise ValueError('Choose a business document and supported event')
    field = frappe.get_meta(rule.source_doctype).get_field(rule.recipient_field)
    if not field or field.fieldtype != 'Link' or field.options != rule.business_doctype:
        raise ValueError('Recipient field must link to the business DocType')
    mapping(rule)
    if rule.enabled:
        with as_user(rule.run_as_user): require_access(manage=True)
        if rule.use_preferences:
            if not any((rule.template, rule.telegram_body, rule.email_body)):
                raise ValueError('Configure content for at least one channel')
        else:
            channel = frappe.get_doc('Relay Channel', rule.channel)
            if not channel.enabled:
                raise ValueError('Choose an enabled channel')
            if channel.channel == 'WhatsApp':
                approved(rule)
            elif channel.channel == 'Telegram':
                if not rule.telegram_body:
                    raise ValueError('Configure Telegram text')
            elif channel.channel == 'Email':
                if not rule.email_subject or not rule.email_body:
                    raise ValueError('Configure an email subject and body')
            else:
                raise ValueError('Unsupported event channel')
        values = {key: 'sample' for key in mapping(rule)}
        from relay_core.email_templates import render, render_text
        if rule.telegram_body:
            render_text(rule.telegram_body, values, limit=4096)
        if rule.email_body:
            render(rule.email_subject, rule.email_body, values, rule.email_signature or '')


def parameters(rule, doc):
    result = []
    for key in mapping(rule):
        if key == 'items_summary':
            value = ', '.join(f"{row.get('item_name') or row.get('item_code')}: {row.get('qty')} {row.get('uom')}" for row in (doc.get('items') or []))
        else:
            value = str(doc.get(key)) if doc.get(key) is not None else ''
        if len(value) > 2000: raise ValueError('Template parameter exceeds 2000 characters')
        result.append({'type': 'text', 'text': value})
    return result


def readable_parameters(rule, source, payload):
    fields = mapping(rule)
    permitted = set(frappe.get_meta(rule.source_doctype).get_permitted_fieldnames(permission_type='read')) | {'name'}
    required = {'items' if field == 'items_summary' else field for field in fields}
    if not required.issubset(permitted):
        raise ValueError('Template fields are not readable')
    if 'items_summary' in fields:
        child_type = frappe.get_meta(rule.source_doctype).get_field('items').options
        child_fields = set(frappe.get_meta(child_type).get_permitted_fieldnames(parenttype=rule.source_doctype, permission_type='read'))
        if not {'item_name', 'item_code', 'qty', 'uom'}.issubset(child_fields):
            raise ValueError('Item fields are not readable')
    snapshot = json.loads(payload)
    if 'selection' in snapshot:
        return
    if parameters(rule, source) != snapshot['components'][0]['parameters']:
        raise ValueError('Source data changed before delivery')


def log_failure(context=''):
    frappe.log_error(title='Relay business event failed', message='Business transaction retained; review event rule and delivery configuration. ' + context)


def clear_rule_cache():
    frappe.cache.delete_value(RULE_PAIRS_CACHE_KEY)
    frappe.db.after_commit.add(lambda: frappe.cache.delete_value(RULE_PAIRS_CACHE_KEY))


def enabled_rule_pairs():
    pairs = frappe.cache.get_value(RULE_PAIRS_CACHE_KEY)
    if pairs is None:
        pairs = {(row.source_doctype, row.event) for row in frappe.get_all(
            'Relay Business Event Rule', filters={'enabled': 1}, fields=['source_doctype', 'event'])}
        frappe.cache.set_value(RULE_PAIRS_CACHE_KEY, pairs, expires_in_sec=60)
    return pairs


def on_event(doc, method=None):
    """Capture configured business events; a Relay failure never fails the business transaction.

    Only a deadlock or a failed savepoint rollback escapes, as the transaction is then no longer usable."""
    if any(getattr(frappe.flags, flag, False) for flag in ('in_import', 'in_migrate', 'in_install', 'in_patch')):
        return
    if method not in EVENTS or doc.doctype in RELAY_DOCTYPES or getattr(frappe.flags, 'relay_business_event', False):
        return
    frappe.flags.relay_business_event = True
    try:
        try:
            if (doc.doctype, method) not in enabled_rule_pairs():
                return
            rules = frappe.get_all('Relay Business Event Rule', filters={'enabled': 1,
                'source_doctype': doc.doctype, 'event': method}, pluck='name')
        except frappe.QueryDeadlockError:
            raise
        except Exception:
            log_failure(f'{doc.doctype}/{doc.name}; {method}; rule lookup')
            return
        for name in rules:
            try:
                frappe.db.savepoint('relay_business_event')
                capture(frappe.get_doc('Relay Business Event Rule', name), doc, method)
            except frappe.QueryDeadlockError:
                raise
            except Exception:
                frappe.db.rollback(save_point='relay_business_event')
                log_failure(f'{doc.doctype}/{doc.name}; {method}; rule {name}')
    finally:
        frappe.flags.relay_business_event = False


def capture(rule, doc, event):
    business = doc.get(rule.recipient_field)
    if not business: raise ValueError('Business recipient is missing')
    # No guessing among several contacts. Configuration can be corrected and replayed.
    people = [rule.contact] if rule.get('contact') else frappe.get_all('Dynamic Link', filters={'parenttype': 'Contact', 'parentfield': 'links',
        'link_doctype': rule.business_doctype, 'link_name': business}, pluck='parent', distinct=True, limit_page_length=2)
    if len(people) != 1: raise ValueError('Business needs exactly one recipient contact')
    key = hashlib.sha256(json.dumps([frappe.local.site, doc.doctype, doc.name, event, rule.name, people[0]], separators=(',', ':')).encode()).hexdigest()
    # The business document transaction serializes lifecycle callbacks; unique key is final protection.
    if frappe.db.exists('Relay Business Event Delivery', {'event_key': key}): return
    payload = snapshot(rule, doc, people[0], business)
    snapshot_ownership(payload, rule, people[0], business)
    delivery = frappe.get_doc({'doctype': 'Relay Business Event Delivery', 'event_key': key,
        'rule': rule.name, 'rule_version': str(rule.modified), 'source_doctype': doc.doctype,
        'source_name': doc.name, 'event': event, 'business_doctype': rule.business_doctype,
        'business_name': business, 'contact': people[0], 'payload': json.dumps(payload),
        'payload_hash': hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        'execution_user': rule.run_as_user,
        'channel': payload.get('selection', {}).get('channel') or rule.channel,
        'endpoint': payload.get('selection', {}).get('endpoint'), 'status': 'Pending'})
    internal_save(delivery, new=True)
    frappe.db.after_commit.add(lambda: enqueue_delivery(delivery.name))


def snapshot_ownership(payload, rule, contact, business):
    """Freeze lifecycle ownership with the intent, before any queued dispatch."""
    from relay_core.conversation_start import ensure_business_binding, target
    from relay_core.messaging import delivery_episodes
    selection = payload.get('selection', {})
    with as_user(rule.run_as_user):
        relay, endpoint = ensure_business_binding(contact, selection.get('channel') or rule.channel,
            rule.business_doctype, business, selection.get('endpoint'))
        source, _, context = target(relay, endpoint, rule.business_doctype, business)
        payload['delivery_episodes'] = [[row.name, int(row.generation or 0)]
                                       for row in delivery_episodes(source, context)]


def snapshot(rule, source, contact, business):
    provider = frappe.db.get_value('Relay Channel', rule.channel, 'channel') if rule.channel else None
    if not rule.get('use_preferences') and provider == 'WhatsApp':
        template = approved(rule)
        return {'name': template.template_name, 'language': template.language,
                'components': [{'type': 'body', 'parameters': parameters(rule, source)}]}
    from relay_core.channel_preferences import resolve
    from relay_core.email_templates import render, render_text
    with as_user(rule.run_as_user):
        source.check_permission('read')
        selection = resolve(contact, rule.business_doctype, business,
                            channels=None if rule.get('use_preferences') else [rule.channel],
                            providers=[provider for provider, content in (('WhatsApp', rule.template),
                                ('Telegram', rule.telegram_body), ('Email', rule.email_body)) if content])
        values = {key: value['text'] for key, value in zip(mapping(rule), parameters(rule, source))}
        payload = {'selection': selection}
        readable_parameters(rule, source, json.dumps(payload))
        provider = selection['provider']
        if provider == 'Telegram':
            payload.update(kind='text', data={'text': render_text(rule.telegram_body, values, limit=4096)})
        elif provider == 'Email':
            payload.update(kind='email', data=render(rule.email_subject, rule.email_body, values, rule.email_signature or ''))
        elif provider == 'WhatsApp':
            selected_rule = frappe._dict(rule.as_dict())
            selected_rule.channel = selection['channel']
            template = approved(selected_rule)
            payload.update(kind='template', data={'name': template.template_name, 'language': template.language,
                'components': [{'type': 'body', 'parameters': parameters(rule, source)}]})
        else:
            raise ValueError('Unsupported event channel')
        return payload


def action_key(delivery, rule):
    prefix = 'email:' if json.loads(delivery.payload).get('kind') == 'email' else ''
    return hashlib.sha256((prefix + (delivery.get('execution_user') or rule.run_as_user) + ':' + delivery.event_key).encode()).hexdigest()


def delivery_status(status, result=None):
    if status == 'Rejected' and (result or {}).get('suppressed'):
        return 'Suppressed'
    return {'Submitted': 'Submitted', 'Queued': 'Queued', 'Rejected': 'Failed'}.get(status, 'Uncertain')


def enqueue_delivery(name):
    try:
        frappe.enqueue('relay_core.business_events.dispatch', name=name, queue='short')
    except Exception:
        # The committed Pending intent is recovered by the scheduler.
        log_failure()


@retry_callback
def dispatch(name):
    frappe.db.get_value('Relay Business Event Delivery', name, 'name', for_update=True)
    delivery = frappe.get_doc('Relay Business Event Delivery', name)
    if delivery.status != 'Pending': return
    key = None
    try:
        rule = frappe.get_doc('Relay Business Event Rule', delivery.rule)
        key = action_key(delivery, rule)
        existing = frappe.db.get_value('Relay Message Action', {'request_key': key}, ['name', 'status'], as_dict=True)
        if existing:
            result = {'action': existing.name, 'status': existing.status}
            if existing.status == 'Dispatching':
                from relay_core.messaging import reconcile
                with as_user(delivery.get('execution_user') or rule.run_as_user):
                    result = reconcile(existing.name)
        else:
            rule = delivery_scope(delivery)
            with as_user(rule.run_as_user):
                from relay_core.conversation_start import send_business
                token = outgoing_event.set(delivery.name)
                try:
                    payload = json.loads(delivery.payload)
                    selection = payload.get('selection', {})
                    result = send_business(delivery.contact, selection.get('channel') or rule.channel,
                        payload.get('kind', 'template'), payload.get('data') or {key: payload[key] for key in ('name', 'language', 'components')}, delivery.event_key,
                        delivery.business_doctype, delivery.business_name, **({'endpoint': selection['endpoint']} if selection else {}))
                finally:
                    outgoing_event.reset(token)
        frappe.db.get_value('Relay Business Event Delivery', name, 'name', for_update=True)
        delivery.reload()
        if delivery.status not in ('Submitted', 'Suppressed'):
            action_result = json.loads(frappe.db.get_value('Relay Message Action', result.get('action'), 'result') or '{}') if result.get('action') else {}
            delivery.status = delivery_status(result['status'], action_result)
        delivery.action = result.get('action')
        internal_save(delivery); frappe.db.commit()
    except frappe.QueryDeadlockError:
        raise
    except Exception as exc:
        frappe.db.rollback()
        frappe.db.get_value('Relay Business Event Delivery', name, 'name', for_update=True)
        delivery.reload()
        action = frappe.db.get_value('Relay Message Action', {'request_key': key}, ['name', 'status'], as_dict=True) if key else None
        terminal = (isinstance(exc, (ValueError, frappe.ValidationError, frappe.PermissionError, frappe.DoesNotExistError))
                    and not isinstance(exc, frappe.TimestampMismatchError))
        delivery.status = delivery_status(action.status) if action else ('Failed' if terminal else 'Pending')
        delivery.action = action.name if action else None
        frappe.db.set_value('Relay Business Event Delivery', name,
                            {'status': delivery.status, 'action': delivery.action})
        log_failure(type(exc).__name__); frappe.db.commit()


def delivery_scope(delivery):
    rule = frappe.get_doc('Relay Business Event Rule', delivery.rule)
    if (not rule.enabled or str(rule.modified) != delivery.rule_version
            or delivery.get('execution_user') and delivery.execution_user != rule.run_as_user):
        raise ValueError('Rule changed')
    payload = json.loads(delivery.payload)
    if delivery.get('payload_hash') and hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() != delivery.payload_hash:
        raise ValueError('Delivery content changed')
    with as_user(rule.run_as_user):
        source = frappe.get_doc(delivery.source_doctype, delivery.source_name)
        source.check_permission('read')
        readable_parameters(rule, source, delivery.payload)
        if source.get(rule.recipient_field) != delivery.business_name:
            raise ValueError('Business changed')
        if payload.get('selection'):
            from relay_core.channel_preferences import recheck
            recheck(delivery.contact, delivery.business_doctype, delivery.business_name, payload['selection'])
        else:
            approved(rule)
    return rule


def complete(action):
    name = json.loads(action.payload).get('business_event')
    if not name or action.status == 'Dispatching':
        return
    status = frappe.db.get_value('Relay Business Event Delivery', name, 'status', for_update=True)
    if status and status != 'Submitted':
        frappe.db.set_value('Relay Business Event Delivery', name,
            {'status': delivery_status(action.status, json.loads(action.result or '{}')), 'action': action.name})


def recover():
    delivery = frappe.qb.DocType('Relay Business Event Delivery')
    action = frappe.qb.DocType('Relay Message Action')
    # Only finished actions need repair; unresolved rows cannot starve later receipts.
    rows = (frappe.qb.from_(delivery).join(action).on(delivery.action == action.name)
        .select(action.name).where(delivery.status.isin(['Queued', 'Uncertain']))
        .where(action.status.isin(['Submitted', 'Rejected'])).limit(20).run(as_dict=True))
    for row in rows:
        complete(frappe.get_doc('Relay Message Action', row.name))
    for name in frappe.get_all('Relay Business Event Delivery', filters={'status': 'Pending'},
        pluck='name', order_by='creation asc', limit_page_length=20):
        enqueue_delivery(name)


@frappe.whitelist(methods=['GET'])
def directory(after=None):
    require_access(configure=True)
    rows = frappe.get_list('Relay Business Event Rule', filters={'name': ['>', after]} if after else {},
        fields=['name', *FIELDS], order_by='name asc', page_length=31)
    return {'items': rows[:30], 'next': rows[29].name if len(rows) > 30 else None}


@frappe.whitelist(methods=['POST'])
def save(values, name=None):
    require_access(configure=True)
    if isinstance(values, str): values = frappe.parse_json(values)
    if not isinstance(values, dict) or set(values) - set(FIELDS): raise ValueError('Invalid event rule fields')
    doc = frappe.get_doc('Relay Business Event Rule', name) if name else frappe.new_doc('Relay Business Event Rule')
    doc.update(values); doc.save()
    return {'name': doc.name}


def install_samples():
    for source, title, params in (
        ('Delivery Note', 'We have delivered {name}: {items_summary}', ['name', 'items_summary']),
        ('Sales Order', 'Order {name} received: {total_qty}', ['name', 'total_qty']),
    ):
        if not frappe.db.exists('DocType', source) or frappe.db.exists('Relay Business Event Rule', {'sample_key': source}): continue
        frappe.get_doc({'doctype': 'Relay Business Event Rule', 'title': title, 'sample_key': source,
            'enabled': 0, 'source_doctype': source, 'event': 'on_submit', 'recipient_field': 'customer',
            'business_doctype': 'Customer', 'parameter_mapping': json.dumps(params)}).insert(ignore_permissions=True)
    clear_rule_cache()


@frappe.whitelist(methods=['GET'])
def template_preview(name):
    """Read template wording from Hub for the editor; never sends a message."""
    require_access(configure=True)
    template = frappe.get_doc('Relay WhatsApp Template', name)
    template.check_permission('read')
    from relay_core.whatsapp import execute
    from relay_core.settings import value
    if template.account != value('relay_hub_account'):
        raise ValueError('Template belongs to another Hub account')
    after = None
    for _ in range(20):
        page = execute('templates.list', {'after': after} if after else {})
        for row in page.get('data', []):
            if str(row['id']) == template.template_id:
                return {'body': next((part.get('text', '') for part in row.get('components', [])
                    if part.get('type', '').upper() == 'BODY'), '')}
        cursor = page.get('paging', {}).get('cursors', {}).get('after')
        if not cursor or cursor == after:
            break
        after = cursor
    raise ValueError('Template wording unavailable; refresh Templates and try again')
