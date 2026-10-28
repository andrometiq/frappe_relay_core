"""Staff create contacts and link them to business records. Contact.links stays the source of
links; Relay Contact keeps only which link is primary."""
import hashlib

import frappe
from relay_core.permissions import can_manage, readable_contact, require_access


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


HIDDEN_CHARACTERS = {*range(0x200B, 0x2010), *range(0x202A, 0x202F), *range(0x2066, 0x206A)}


def display_name(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 140:
        frappe.throw('Enter a name of at most 140 characters')
    if any(c in '<>' for c in value):
        frappe.throw('Name cannot contain < or >')
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        frappe.throw('Name cannot contain tabs or line breaks')
    if any(ord(c) in HIDDEN_CHARACTERS for c in value):
        frappe.throw('Name cannot contain hidden or direction-control characters')
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
        person = new_person(name, number, links)
        relay = ensure_relay(person)
        from relay_core.contact_lifecycle import enroll
        endpoint = enroll(relay, channel.name, 'WhatsApp', number, locked=True)
    return {'contact': person.name, 'relay_contact': relay, 'endpoint': endpoint.name}


def new_person(name, number, links=(), *, ignore_permissions=False):
    return frappe.get_doc({'doctype': 'Contact', 'first_name': name,
        'phone_nos': [{'phone': '+' + number, 'is_primary_mobile_no': 1}],
        'links': [{'link_doctype': doctype, 'link_name': record} for doctype, record in links]
    }).insert(ignore_permissions=ignore_permissions)


def ensure_relay(person):
    """One Relay conversation per Frappe Contact, including concurrent channel enrollment."""
    with frappe.cache.lock('relay-person:' + person.name, timeout=30):
        name = frappe.db.get_value('Relay Contact', {'contact': person.name}, 'name')
        if name:
            return name
        return frappe.get_doc({'doctype': 'Relay Contact', 'contact': person.name,
            'display_name': person.get('full_name') or person.get('first_name') or person.name
        }).insert(ignore_permissions=True).name


@frappe.whitelist(methods=['POST'])
def set_links(contact, links):
    """Replace the business links the user can read; other links stay as they are."""
    require_access()
    person = frappe.get_doc('Contact', contact)
    manager = can_manage_links(person.name)
    if not manager:
        person.check_permission('write')
    wanted = business_links(links)
    configured = set(frappe.get_all('Relay Contact Type', filters={'enabled': 1}, pluck='business_doctype'))
    kept = [row for row in person.links if row.link_doctype not in configured or not readable(row)]
    person.set('links', [{'link_doctype': row.link_doctype, 'link_name': row.link_name} for row in kept]
               + [{'link_doctype': doctype, 'link_name': name} for doctype, name in wanted])
    if manager:
        person.save(ignore_permissions=True)
    else:
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
    if not can_manage_links(person.name):
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


def can_manage_links(contact):
    """Relay managers edit the business links of a Relay conversation's Contact without general Contact write access.
    Links to records they cannot read stay as they are."""
    return can_manage() and bool(frappe.db.get_value('Relay Contact', {'contact': contact}, 'name'))


def linked_contacts(names):
    """Business membership for a page, independent of the viewer's business permissions."""
    if not names:
        return set()
    rows = frappe.db.sql("""SELECT DISTINCT r.name FROM `tabRelay Contact` r
        JOIN `tabDynamic Link` l ON l.parent=r.contact AND l.parenttype='Contact' AND l.parentfield='links'
        JOIN `tabRelay Contact Type` t ON t.business_doctype=l.link_doctype AND t.enabled=1
        WHERE r.name IN %(names)s""", {'names': names})
    return {row[0] for row in rows}


@frappe.whitelist(methods=['GET'])
def unlinked(query='', after=None, before=None):
    """Manager contact queue, newest activity first, with stable keyset pagination."""
    require_access(manage=True)
    if not isinstance(query, str) or len(query) > 80:
        frappe.throw('Search must be at most 80 characters')
    values = {'query': '%' + query.strip() + '%'}
    cursor = ''
    if after:
        from relay_core.api import validate_reference
        validate_reference(after, 'CON')
        values.update(after=after, before=frappe.utils.get_datetime(before))
        cursor = 'AND (COALESCE(r.last_message_at,r.creation),r.name) < (%(before)s,%(after)s)'
    rows = frappe.db.sql("""SELECT r.name, r.contact, r.display_name, r.last_message_at, r.creation,
            COALESCE(NULLIF(c.mobile_no,''),c.phone) phone
        FROM `tabRelay Contact` r LEFT JOIN `tabContact` c ON c.name=r.contact
        WHERE NOT EXISTS (SELECT 1 FROM `tabDynamic Link` l
            JOIN `tabRelay Contact Type` t ON t.business_doctype=l.link_doctype AND t.enabled=1
            WHERE l.parent=r.contact AND l.parenttype='Contact' AND l.parentfield='links')
        AND (r.display_name LIKE %(query)s OR c.full_name LIKE %(query)s OR c.mobile_no LIKE %(query)s
            OR c.phone LIKE %(query)s OR EXISTS (SELECT 1 FROM `tabContact Phone` p
                WHERE p.parent=c.name AND p.parenttype='Contact' AND p.phone LIKE %(query)s)
            OR EXISTS (SELECT 1 FROM `tabRelay Contact Endpoint` e
                WHERE e.relay_contact=r.name AND e.endpoint LIKE %(query)s)) """ + cursor + """
        ORDER BY COALESCE(r.last_message_at,r.creation) DESC, r.name DESC LIMIT 31""", values, as_dict=True)
    from relay_core.inbox import directory_items
    items = directory_items(rows[:30])
    return {'items': items, 'next': {'after': rows[29].name,
        'before': str(rows[29].last_message_at or rows[29].creation)} if len(rows) > 30 else None}
