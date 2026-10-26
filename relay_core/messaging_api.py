"""WhatsApp sends to a phone number for API clients and AI, through the Core action journal and timeline."""
import hashlib
import inspect
import json
import re
import time
import frappe
from relay_core import bulk_sheet, service_window, whatsapp
from relay_core.bulk_campaigns import parsed, whatsapp_channel
from relay_core.identity import phone_number
from relay_core.permissions import require_access

MAX_ITEMS = 100
KEY = re.compile(r'[A-Za-z0-9_-]{1,100}')
MEDIA = ('image', 'video', 'audio', 'document')
AUTO_KEY_SECONDS = 600
OUTSIDE_WINDOW = 'Outside the 24-hour reply window. Send an approved template instead'


@frappe.whitelist(methods=['POST'])
def send_text(number, body, key=None, business_doctype=None, business_name=None):
    """One text inside the 24-hour reply window."""
    require_access()
    return send(number, 'messages.send', {'body': body}, key, business_doctype, business_name)


@frappe.whitelist(methods=['POST'])
def send_media(number, media_url, media_type, caption=None, filename=None, key=None, business_doctype=None,
               business_name=None):
    """One photo, video, audio or document from an HTTPS link, inside the 24-hour reply window."""
    require_access()
    if media_type not in MEDIA:
        frappe.throw('media_type must be image, video, audio or document')
    if filename and media_type != 'document':
        frappe.throw('Only a document has a file name')
    arguments = {'media_type': media_type, 'media_url': link(media_url),
                 **({'caption': caption} if caption else {}), **({'filename': filename} if filename else {})}
    return send(number, 'messages.media', arguments, key, business_doctype, business_name)


@frappe.whitelist(methods=['POST'])
def send_template(number, template, language, params=None, header_media_url=None, key=None, business_doctype=None,
                  business_name=None):
    """One approved template. params is an object of named values (or field keys such as button:0), or a list
    of every value in template order; header_media_url fills an image, video or document header."""
    require_access()
    from relay_core.whatsapp_templates import definition
    found = definition(template, language) if isinstance(template, str) and isinstance(language, str) else None
    if not found:
        frappe.throw('Template not found for this WhatsApp account')
    params = parsed(params)
    try:
        fields = bulk_sheet.template_fields(found)
        components = bulk_sheet.build_components(fields, template_values(fields, params, header_media_url))
    except ValueError as exc:
        frappe.throw(str(exc))
    return send(number, 'templates.send', {'name': template, 'language': language, 'components': components}, key,
                business_doctype, business_name)


SENDS = {'text': send_text, 'media': send_media, 'template': send_template}


@frappe.whitelist(methods=['POST'])
def send_messages(items):
    """Up to 100 sends of {type: text, media or template, number, ...the arguments of that send}. Each item gets
    its own result; one failed item does not stop the others."""
    require_access()
    items = parsed(items)
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        frappe.throw(f'Send 1-{MAX_ITEMS} items')
    return {'results': [send_item(index, item) for index, item in enumerate(items)]}


def send_item(index, item):
    try:
        if not isinstance(item, dict) or item.get('type') not in SENDS:
            frappe.throw('type must be text, media or template')
        method = SENDS[item['type']]
        arguments = {key: value for key, value in item.items() if key != 'type'}
        try:
            inspect.signature(method).bind(**arguments)
        except TypeError:
            frappe.throw(f"Give the fields a {item['type']} send needs and no others")
        return {'index': index, 'ok': True, **method(**arguments)}
    except (frappe.ValidationError, frappe.PermissionError, frappe.DuplicateEntryError) as exc:
        frappe.db.rollback()  # This item's uncommitted writes only; each send commits its own.
        frappe.clear_messages()
        return {'index': index, 'ok': False, 'error': str(exc) or 'Not permitted'}


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


def send(number, operation, arguments, key, business_doctype, business_name):
    destination = phone_number(number) if isinstance(number, (str, int)) and not isinstance(number, bool) else None
    if not destination:
        frappe.throw('Give the phone number with its country code')
    channel = whatsapp_channel()
    if operation != 'templates.send' and not service_window.open_numbers(channel, [destination]):
        frappe.throw(OUTSIDE_WINDOW)
    contact, business = recipient(channel, destination, business_doctype, business_name)
    request_key = message_key(key, destination, operation, arguments)
    try:
        result = whatsapp.send({'key': request_key, 'operation': operation, 'arguments': arguments, 'contact': contact,
                                'business_doctype': business[0], 'business_name': business[1]})
    except ValueError as exc:
        frappe.throw(str(exc))
    return {**result, 'number': destination, 'contact': contact, 'key': request_key}


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
    binding = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': endpoint_key(channel, destination)},
                                  ['relay_contact', 'verified'], as_dict=True)
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
