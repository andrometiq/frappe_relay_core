"""Staff create contacts and link them to business records. Contact.links stays the source of
links; Relay Contact keeps only which link is primary."""
import hashlib

import frappe
from relay_core.permissions import readable_contact, require_access


def business_links(links):
    """Validate requested links: configured types and records the user can read."""
    links = frappe.parse_json(links) if isinstance(links, str) else links
    if not isinstance(links, list) or len(links) > 50:
        frappe.throw('Choose at most 50 business records')
    result = []
    for row in links:
        doctype, name = (row.get('doctype'), row.get('name')) if isinstance(row, dict) else (None, None)
        if not isinstance(doctype, str) or not isinstance(name, str) or not name or len(name) > 140:
            frappe.throw('Choose a business type and record')
        if not frappe.db.exists('Relay Contact Type', {'business_doctype': doctype, 'enabled': 1}):
            frappe.throw('Choose a configured business type', frappe.PermissionError)
        frappe.get_doc(doctype, name).check_permission('read')
        result.append((doctype, name))
    return list(dict.fromkeys(result))


def display_name(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 140 or any(ord(c) < 32 for c in value):
        frappe.throw('Enter a name of at most 140 characters')
    return value.strip()


def whatsapp_channel(channel):
    from relay_core.api import validate_reference
    validate_reference(channel, 'CH')
    doc = frappe.get_doc('Relay Channel', channel)
    doc.check_permission('read')
    if doc.channel != 'WhatsApp' or not doc.enabled:
        frappe.throw('Choose an enabled WhatsApp channel')
    return doc


@frappe.whitelist(methods=['POST'])
def create(name, phone, channel, links=None):
    """New Frappe Contact, Relay Contact and verified WhatsApp endpoint for one number."""
    require_access(manage=True)
    name, channel = display_name(name), whatsapp_channel(channel)
    from relay_core.identity import bindings, phone_number
    number = phone_number(phone)
    if not number:
        frappe.throw('Enter a valid phone number')
    links = business_links(links or [])
    key = hashlib.sha256((channel.name + ':' + number).encode()).hexdigest()
    with frappe.cache.lock('relay-enroll:' + key, timeout=30):
        if any(bindings(channel.name, 'WhatsApp', number)):
            frappe.throw('This number already belongs to a contact', frappe.DuplicateEntryError)
        person = frappe.get_doc({'doctype': 'Contact', 'first_name': name,
            'phone_nos': [{'phone': '+' + number, 'is_primary_mobile_no': 1}],
            'links': [{'link_doctype': doctype, 'link_name': record} for doctype, record in links]}).insert()
        relay = frappe.get_doc({'doctype': 'Relay Contact', 'contact': person.name,
                                'display_name': name}).insert(ignore_permissions=True)
        previous = getattr(frappe.flags, 'relay_endpoint_enrollment', False)
        frappe.flags.relay_endpoint_enrollment = True
        try:
            endpoint = frappe.get_doc({'doctype': 'Relay Contact Endpoint', 'channel': channel.name,
                'relay_contact': relay.name, 'endpoint': number, 'verified': 1}).insert(ignore_permissions=True)
        finally:
            frappe.flags.relay_endpoint_enrollment = previous
    return {'contact': person.name, 'relay_contact': relay.name, 'endpoint': endpoint.name}


@frappe.whitelist(methods=['POST'])
def set_links(contact, links):
    """Replace the business links the user can read; other links stay as they are."""
    require_access()
    person = frappe.get_doc('Contact', contact)
    person.check_permission('write')
    wanted = business_links(links)
    configured = set(frappe.get_all('Relay Contact Type', filters={'enabled': 1}, pluck='business_doctype'))
    kept = [row for row in person.links if row.link_doctype not in configured or not readable(row)]
    person.set('links', [{'link_doctype': row.link_doctype, 'link_name': row.link_name} for row in kept]
               + [{'link_doctype': doctype, 'link_name': name} for doctype, name in wanted])
    person.save()
    return summary(person.name)


def readable(row):
    try:
        return frappe.get_doc(row.link_doctype, row.link_name).has_permission('read')
    except frappe.DoesNotExistError:
        return False


@frappe.whitelist(methods=['POST'])
def set_primary(contact, doctype=None, name=None):
    """Mark one linked record as primary; no record clears the mark."""
    require_access()
    person = frappe.get_doc('Contact', contact)
    person.check_permission('write')
    relay = frappe.db.get_value('Relay Contact', {'contact': person.name}, 'name')
    if not relay:
        frappe.throw('This contact has no Relay conversation')
    readable_contact(relay)  # The primary routes the conversation, so only its readers set it.
    target = (None, None)
    if doctype or name:
        from relay_core.business_access import candidates
        target = business_links([{'doctype': doctype, 'name': name}])[0]
        if target not in candidates(relay):
            frappe.throw('Link the record to this contact first')
    doc = frappe.get_doc('Relay Contact', relay)
    doc.primary_doctype, doc.primary_name = target
    doc.save(ignore_permissions=True)
    return summary(person.name)


def summary(contact):
    from relay_core.business_access import primary_record
    relay = frappe.db.get_value('Relay Contact', {'contact': contact}, 'name')
    configured = set(frappe.get_all('Relay Contact Type', filters={'enabled': 1}, pluck='business_doctype'))
    links = [{'doctype': row.link_doctype, 'name': row.link_name}
             for row in frappe.get_doc('Contact', contact).links
             if row.link_doctype in configured and readable(row)]
    return {'contact': contact, 'relay_contact': relay, 'links': links,
            'primary': primary_record(relay) if relay else None}
