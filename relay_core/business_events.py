"""Business transactions capture intents; workers deliver approved templates."""
from contextvars import ContextVar
import hashlib
import json
import frappe
from relay_core.ai.tools import as_user
from relay_core.permissions import require_access
from relay_core.business_references import RELAY_DOCTYPES
from relay_core.automation.service import internal_save

FIELDS = ('title', 'enabled', 'source_doctype', 'event', 'recipient_field', 'business_doctype',
          'channel', 'run_as_user', 'template', 'parameter_mapping')
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
        approved(rule)


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
    if parameters(rule, source) != json.loads(payload)['components'][0]['parameters']:
        raise ValueError('Source data changed before delivery')


def log_failure(context=''):
    try:
        frappe.log_error(title='Relay business event failed', message='Business transaction retained; review event rule and delivery configuration. ' + context)
    except Exception:
        pass


def clear_rule_cache():
    frappe.cache.delete_value(RULE_PAIRS_CACHE_KEY)
    frappe.db.after_commit.add(lambda: frappe.cache.delete_value(RULE_PAIRS_CACHE_KEY))


def enabled_rule_pairs():
    pairs = frappe.cache.get_value(RULE_PAIRS_CACHE_KEY)
    if pairs is None:
        pairs = {(row.source_doctype, row.event) for row in frappe.get_all(
            'Relay Business Event Rule', filters={'enabled': 1}, fields=['source_doctype', 'event'])}
        frappe.cache.set_value(RULE_PAIRS_CACHE_KEY, pairs)
    return pairs


def on_event(doc, method=None):
    if any(getattr(frappe.flags, flag, False) for flag in ('in_import', 'in_migrate', 'in_install', 'in_patch')):
        return
    if method not in EVENTS or doc.doctype in RELAY_DOCTYPES or getattr(frappe.flags, 'relay_business_event', False):
        return
    frappe.flags.relay_business_event = True
    try:
        if (doc.doctype, method) not in enabled_rule_pairs():
            return
        rules = frappe.get_all('Relay Business Event Rule', filters={'enabled': 1,
            'source_doctype': doc.doctype, 'event': method}, pluck='name')
        for name in rules:
            try:
                frappe.db.savepoint('relay_business_event')
                capture(frappe.get_doc('Relay Business Event Rule', name), doc, method)
            except Exception:
                try: frappe.db.rollback(save_point='relay_business_event')
                except Exception: pass
                log_failure(f'{doc.doctype}/{doc.name}; {method}; rule {name}')
    except Exception:
        log_failure(f'{doc.doctype}/{doc.name}; {method}')
    finally:
        frappe.flags.relay_business_event = False


def capture(rule, doc, event):
    business = doc.get(rule.recipient_field)
    if not business: raise ValueError('Business recipient is missing')
    # No guessing among several contacts. Configuration can be corrected and replayed.
    people = frappe.get_all('Dynamic Link', filters={'parenttype': 'Contact', 'parentfield': 'links',
        'link_doctype': rule.business_doctype, 'link_name': business}, pluck='parent', distinct=True, limit_page_length=2)
    if len(people) != 1: raise ValueError('Business needs exactly one recipient contact')
    key = hashlib.sha256(json.dumps([frappe.local.site, doc.doctype, doc.name, event, rule.name, people[0]], separators=(',', ':')).encode()).hexdigest()
    # The business document transaction serializes lifecycle callbacks; unique key is final protection.
    if frappe.db.exists('Relay Business Event Delivery', {'event_key': key}): return
    template = approved(rule)
    payload = {'name': template.template_name, 'language': template.language,
        'components': [{'type': 'body', 'parameters': parameters(rule, doc)}]}
    delivery = frappe.get_doc({'doctype': 'Relay Business Event Delivery', 'event_key': key,
        'rule': rule.name, 'rule_version': str(rule.modified), 'source_doctype': doc.doctype,
        'source_name': doc.name, 'event': event, 'business_doctype': rule.business_doctype,
        'business_name': business, 'contact': people[0], 'payload': json.dumps(payload), 'status': 'Pending'})
    internal_save(delivery, new=True)
    frappe.db.after_commit.add(lambda: enqueue_delivery(delivery.name))


def enqueue_delivery(name):
    try:
        frappe.enqueue('relay_core.business_events.dispatch', name=name, queue='short')
    except Exception:
        # The committed Pending intent is recovered by the scheduler.
        log_failure()


def dispatch(name):
    frappe.db.get_value('Relay Business Event Delivery', name, 'name', for_update=True)
    delivery = frappe.get_doc('Relay Business Event Delivery', name)
    if delivery.status != 'Pending': return
    try:
        rule = delivery_scope(delivery)
        with as_user(rule.run_as_user):
            from relay_core.conversation_start import send_business
            token = outgoing_event.set(delivery.name)
            try:
                result = send_business(delivery.contact, rule.channel, 'template', json.loads(delivery.payload),
                    delivery.event_key, delivery.business_doctype, delivery.business_name)
            finally:
                outgoing_event.reset(token)
        delivery.status = 'Submitted' if result['status'] == 'Submitted' else 'Uncertain'
        delivery.action = result.get('action')
        internal_save(delivery); frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        # Recover an existing journal entry rather than resending an uncertain send.
        delivery.reload()
        key = hashlib.sha256((rule.run_as_user + ':' + delivery.event_key).encode()).hexdigest() if 'rule' in locals() else None
        action = frappe.db.get_value('Relay Message Action', {'request_key': key}, 'name') if key else None
        delivery.status, delivery.action = ('Uncertain' if action else 'Failed'), action
        internal_save(delivery); log_failure(); frappe.db.commit()


def delivery_scope(delivery):
    rule = frappe.get_doc('Relay Business Event Rule', delivery.rule)
    if not rule.enabled or str(rule.modified) != delivery.rule_version:
        raise ValueError('Rule changed')
    with as_user(rule.run_as_user):
        source = frappe.get_doc(delivery.source_doctype, delivery.source_name)
        source.check_permission('read')
        readable_parameters(rule, source, delivery.payload)
        if source.get(rule.recipient_field) != delivery.business_name:
            raise ValueError('Business changed')
        approved(rule)
    return rule


def recover():
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
