"""WhatsApp sends to a phone number for API clients and AI, through the Core action journal and timeline."""
import hashlib
import inspect
import json
import re
import time
import frappe
from relay_core import bulk_sheet, service_window, whatsapp
from relay_core.bulk_campaigns import parsed
from relay_core.contact_lifecycle import sibling_contact
from relay_core.hub_channels import choose
from relay_core.hub import HubError
from relay_core.identity import phone_number
from relay_core.permissions import require_access
from relay_core.settings import value as connection_value

MAX_ITEMS = 100
KEY = re.compile(r'[A-Za-z0-9_-]{1,100}')
MEDIA = ('image', 'video', 'audio', 'document')
AUTO_KEY_SECONDS = 600
BATCH_CACHE = 'relay-send-batch:'
BATCH_SECONDS = 86400
PENDING = 'Pending'
OUTSIDE_WINDOW = 'Outside the 24-hour reply window. Send an approved template instead'


@frappe.whitelist(methods=['POST'])
def send_text(number, body, key=None, business_doctype=None, business_name=None, channel=None):
    """One text inside the 24-hour reply window."""
    require_access()
    return sent(*text_message(number, body, key, business_doctype, business_name, channel))


@frappe.whitelist(methods=['POST'])
def send_media(number, media_url, media_type, caption=None, filename=None, key=None, business_doctype=None,
               business_name=None, channel=None):
    """One photo, video, audio or document from an HTTPS link, inside the 24-hour reply window."""
    require_access()
    return sent(*media_message(number, media_url, media_type, caption, filename, key, business_doctype, business_name,
                               channel))


@frappe.whitelist(methods=['POST'])
def send_template(number, template, language, params=None, header_media_url=None, key=None, business_doctype=None,
                  business_name=None, channel=None):
    """One approved template. params is an object of named values (or field keys such as button:0), or a list
    of every value in template order; header_media_url fills an image, video or document header."""
    require_access()
    return sent(*template_message(number, template, language, params, header_media_url, key, business_doctype,
                                  business_name, channel))


def text_message(number, body, key=None, business_doctype=None, business_name=None, channel=None):
    return prepared(number, 'messages.send', {'body': body}, key, business_doctype, business_name, channel)


def media_message(number, media_url, media_type, caption=None, filename=None, key=None, business_doctype=None,
                  business_name=None, channel=None):
    if media_type not in MEDIA:
        frappe.throw('media_type must be image, video, audio or document')
    if filename and media_type != 'document':
        frappe.throw('Only a document has a file name')
    arguments = {'media_type': media_type, 'media_url': link(media_url),
                 **({'caption': caption} if caption else {}), **({'filename': filename} if filename else {})}
    return prepared(number, 'messages.media', arguments, key, business_doctype, business_name, channel)


def template_message(number, template, language, params=None, header_media_url=None, key=None, business_doctype=None,
                     business_name=None, channel=None):
    from relay_core.whatsapp_templates import definition
    destination = destination_number(number)
    channel = sending_channel(destination, channel)
    found = definition(template, language, channel) if isinstance(template, str) and isinstance(language, str) else None
    if not found:
        frappe.throw('Template not found for this WhatsApp account')
    params = parsed(params)
    try:
        fields = bulk_sheet.template_fields(found)
        components = bulk_sheet.build_components(fields, template_values(fields, params, header_media_url))
    except ValueError as exc:
        frappe.throw(str(exc))
    return prepared(number, 'templates.send', {'name': template, 'language': language, 'components': components}, key,
                    business_doctype, business_name, channel)


MESSAGES = {'text': text_message, 'media': media_message, 'template': template_message}


@frappe.whitelist(methods=['POST'])
def send_messages(items):
    """Checks 1-100 sends of {type: text, media or template, number, ...the arguments of that send} at once and
    queues the accepted ones as one background job. Each item gets its own result; poll send_status(batch)."""
    require_access()
    items = parsed(items)
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        frappe.throw(f'Send 1-{MAX_ITEMS} items')
    results, accepted = [], []
    for index, item in enumerate(items):
        result, message = checked_item(index, item)
        results.append(result)
        if message:
            accepted.append((index, message))
    return {'batch': queue_batch(accepted) if accepted else None, 'results': results}


def checked_item(index, item):
    """(result, journal message) of one list item; a refused item has no message."""
    try:
        if not isinstance(item, dict) or item.get('type') not in MESSAGES:
            frappe.throw('type must be text, media or template')
        build = MESSAGES[item['type']]
        arguments = {key: value for key, value in item.items() if key != 'type'}
        try:
            inspect.signature(build).bind(**arguments)
        except TypeError:
            frappe.throw(f"Give the fields a {item['type']} send needs and no others")
        message, destination = build(**arguments)
        return {'index': index, 'ok': True, 'status': PENDING, 'number': destination, 'contact': message['contact'],
                'key': message['key']}, message
    except (frappe.ValidationError, frappe.PermissionError, frappe.DuplicateEntryError) as exc:
        frappe.db.rollback()  # This item's uncommitted writes only; a new Contact commits its own.
        frappe.clear_messages()
        return {'index': index, 'ok': False, 'error': str(exc) or 'Not permitted'}, None


def queue_batch(accepted):
    """One long-queue job per distinct request, so a retried request finds the same batch and job."""
    user = frappe.session.user
    content = json.dumps([user, accepted], sort_keys=True, separators=(',', ':'), default=str)
    batch = hashlib.sha256(content.encode()).hexdigest()[:32]
    if not frappe.cache.get_value(BATCH_CACHE + batch, user=user):
        frappe.cache.set_value(BATCH_CACHE + batch, {'items': [(index, message['key']) for index, message in accepted],
                                                     'errors': {}}, user=user, expires_in_sec=BATCH_SECONDS)
    frappe.enqueue('relay_core.messaging_api.deliver_batch', queue='long', timeout=1800, job_id='relay-send-' + batch,
                   deduplicate=True, enqueue_after_commit=True, batch=batch,
                   messages=[message for _, message in accepted])
    return batch


def deliver_batch(batch, messages):
    """Background job: send each message through the journal. Each item's key makes a rerun safe."""
    for message in messages:
        try:
            whatsapp.send(message)
            frappe.db.commit()
            error = None
        except (ValueError, HubError, frappe.ValidationError, frappe.PermissionError, frappe.DuplicateEntryError) as exc:
            frappe.db.rollback()
            frappe.clear_messages()
            error = str(exc) or 'Not permitted'
        record_error(batch, message['key'], error)


def record_error(batch, key, error):
    """Set or clear one item's error; a rerun that succeeds clears the error of an earlier run."""
    state = frappe.cache.get_value(BATCH_CACHE + batch, user=frappe.session.user)
    if not state or state['errors'].get(key) == error:
        return
    if error:
        state['errors'][key] = error
    else:
        state['errors'].pop(key)
    frappe.cache.set_value(BATCH_CACHE + batch, state, user=frappe.session.user, expires_in_sec=BATCH_SECONDS)


@frappe.whitelist(methods=['GET'])
def send_status(batch):
    """Per-item status of the caller's send_messages batch, for 24 hours."""
    require_access()
    state = frappe.cache.get_value(BATCH_CACHE + batch, user=frappe.session.user) if isinstance(batch, str) else None
    if not state:
        frappe.throw('Batch not found or expired', frappe.DoesNotExistError)
    return {'batch': batch, 'results': [item_status(index, key, state['errors']) for index, key in state['items']]}


def item_status(index, key, errors):
    """Failed with its error, Pending before the job reaches it, else the journal action's status."""
    if key in errors:
        return {'index': index, 'key': key, 'status': 'Failed', 'error': errors[key]}
    request_key = hashlib.sha256((frappe.session.user + ':' + key).encode()).hexdigest()
    action = frappe.db.get_value('Relay Message Action', {'request_key': request_key},
                                 ['name', 'status', 'outbound_message'], as_dict=True)
    if not action:
        return {'index': index, 'key': key, 'status': PENDING}
    return {'index': index, 'key': key, 'status': action.status, 'action': action.name,
            'message': action.outbound_message}


def template_values(fields, params, header_media_url):
    """Field key -> value for a template send."""
    if params is not None and not isinstance(params, (dict, list)):
        raise ValueError('params must be an object or a list')
    params = params or {}
    ordered = iter(params) if isinstance(params, list) else iter(())
    values = {}
    for field in fields:
        if field.get('media'):
            value = link(header_media_url) if header_media_url else None
        elif isinstance(params, dict):
            value = params.get(field.get('name') or field['key'], params.get(field['key']))
        else:
            value = next(ordered, None)
        if value is None or not str(value).strip():
            raise ValueError(f"Missing {field['label']}")
        values[field['key']] = str(value)
    if next(ordered, None) is not None:
        raise ValueError('params has more values than the template uses')
    return values


def link(value):
    try:
        return bulk_sheet.media_url(value if isinstance(value, str) else '')
    except ValueError as exc:
        frappe.throw(str(exc))


def destination_number(number):
    destination = phone_number(number) if isinstance(number, (str, int)) and not isinstance(number, bool) else None
    if not destination:
        frappe.throw('Give the phone number with its country code')
    return destination


def sending_channel(destination, requested=None):
    """The number a send leaves from: the caller's pick, else the one the customer wrote to last, else the default."""
    names = frappe.get_all('Relay Channel', pluck='name', filters={
        'channel': 'WhatsApp', 'enabled': 1, 'account': connection_value('relay_hub_account')})
    keys = [endpoint_key(name, destination) for name in names]
    contact = keys and frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': ['in', keys], 'verified': 1},
                                           'relay_contact')
    return choose('WhatsApp', contact=contact or None, requested=requested)


def prepared(number, operation, arguments, key, business_doctype, business_name, channel=None):
    """(journal message, number) after the number, reply window, recipient and key checks."""
    destination = destination_number(number)
    channel = sending_channel(destination, channel)
    if operation != 'templates.send' and not service_window.open_numbers(channel, [destination]):
        frappe.throw(OUTSIDE_WINDOW)
    contact, business = recipient(channel, destination, business_doctype, business_name)
    return {'key': message_key(key, destination, operation, arguments), 'operation': operation, 'arguments': arguments,
            'contact': contact, 'business_doctype': business[0], 'business_name': business[1], 'channel': channel}, destination


def sent(message, destination):
    try:
        result = whatsapp.send(message)
    except ValueError as exc:
        frappe.throw(str(exc))
    return {**result, 'number': destination, 'contact': message['contact'], 'key': message['key']}


def message_key(key, destination, operation, arguments):
    """The caller's key, else one from the content and the current 10-minute bucket: a double click stays one
    message, and the same content later is a new one."""
    if key in (None, ''):
        bucket = int(time.time() // AUTO_KEY_SECONDS)
        content = json.dumps([destination, operation, arguments, bucket], sort_keys=True, separators=(',', ':'))
        return 'api-' + hashlib.sha256(content.encode()).hexdigest()[:64]
    if not isinstance(key, str) or not KEY.fullmatch(key):
        frappe.throw('key must be 1-100 letters, digits, _ or -')
    return 'api-' + key


def recipient(channel, destination, business_doctype, business_name):
    """(Frappe Contact, business record) of the number. An unknown number gets a new Contact (managers only)."""
    from relay_core.business_access import primary
    binding = endpoint_binding(channel, destination)
    if not binding and sibling_contact(channel, destination):
        binding = endpoint_binding(channel, destination)
    if not binding:
        return new_contact(channel, destination, business_doctype, business_name), (business_doctype, business_name)
    if not binding.verified:
        frappe.throw('This number is revoked for WhatsApp')
    if not business_doctype and not business_name:
        business_doctype, business_name = primary(binding.relay_contact) or (None, None)
        if not business_name:
            frappe.throw('Give business_doctype and business_name: the number has no primary business record')
    person = frappe.db.get_value('Relay Contact', binding.relay_contact, 'contact')
    mobile = frappe.db.get_value('Contact', person, ['mobile_no', 'phone'], as_dict=True) or {}
    if phone_number(mobile.get('mobile_no') or mobile.get('phone') or '') != destination:
        frappe.throw('The number is not the main mobile number of its Contact')
    return person, (business_doctype, business_name)


def endpoint_binding(channel, destination):
    return frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': endpoint_key(channel, destination)},
                               ['relay_contact', 'verified'], as_dict=True)


def endpoint_key(channel, destination):
    return hashlib.sha256((channel + ':' + destination).encode()).hexdigest()


def new_contact(channel, destination, business_doctype, business_name):
    """A Contact for the number, linked to the business record, with a verified WhatsApp endpoint."""
    if not business_doctype or not business_name:
        frappe.throw('The number has no contact yet. Give business_doctype and business_name to create one')
    from relay_core.contacts import create
    person = create('+' + destination, destination, channel, [{'doctype': business_doctype, 'name': business_name}])
    frappe.db.commit()  # A parallel send of this number finds the endpoint instead of a second Contact.
    return person['contact']
