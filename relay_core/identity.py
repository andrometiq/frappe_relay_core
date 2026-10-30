"""Canonical provider identities shared by enrollment and projection."""
import re


def authenticated_sender(message, channel):
    """Resolve a private sender from persisted transport evidence, never message text."""
    import hashlib
    import frappe
    from relay_core.automation.provenance import context_of, telegram_route
    from relay_core.email_preferences import automatic_allowed

    provider = channel.channel
    evidence = context_of(message)
    endpoint = normalize(provider, message.sender_endpoint)
    if evidence.get('provider') != provider:
        raise ValueError('Authenticated sender evidence is required')
    if provider == 'Telegram':
        telegram_route(message, '')
        if (evidence.get('chat_type') != 'private' or evidence.get('sender_chat_id')
                or str(evidence.get('participant_id')) != endpoint):
            raise ValueError('Personal records require a private sender')
    elif provider == 'WhatsApp':
        if (not endpoint.isdigit() or evidence.get('group_id')
                or normalize(provider, evidence.get('participant_id')) != endpoint):
            raise ValueError('Personal records require a private sender')
    elif not automatic_allowed(evidence):
        raise ValueError('Authenticated email sender is required')
    key = hashlib.sha256((message.channel + ':' + endpoint).encode()).hexdigest()
    # Canonical enrollment keys are indexed and unique. Legacy aliases need explicit
    # enrollment repair; reading never scans records to discover matching numbers.
    binding = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': key},
        ['name', 'channel', 'endpoint', 'relay_contact', 'verified'], as_dict=True)
    if (not binding or not binding.verified or binding.channel != message.channel
            or binding.endpoint != endpoint or binding.relay_contact != message.relay_contact):
        raise ValueError('Endpoint verification is missing or revoked')
    return {'provider': provider, 'endpoint': endpoint, 'binding': binding.name}


def normalize(provider, value):
    if not isinstance(value, str) or not value or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid endpoint')
    if provider == 'Email':
        value = value.strip().lower()
        if not re.fullmatch(r'[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+', value):
            raise ValueError('Provide a plain email address')
    elif provider == 'Telegram':
        if not re.fullmatch(r'-?[0-9]+', value.strip()) or not 0 < abs(int(value)) < 2**52:
            raise ValueError('Provide a numeric Telegram chat identity')
        value = str(int(value))
    elif provider == 'WhatsApp':
        # Group identities are opaque provider values.
        number = re.sub(r'[ +()\-]', '', value)
        if number.isdigit():
            value = number
    else:
        raise ValueError('Unsupported identity channel')
    return value


def phone_number(value, region=None):
    """E.164 digits without '+', or None. A number without + follows the length rules of the
    region (default: the System Settings country); a long number that is not valid there is
    read as international, as Contacts often store numbers without the +."""
    import phonenumbers
    text = re.sub(r'[\s().-]', '', str(value or ''))
    if text.startswith('00'):
        text = '+' + text[2:]
    if not re.fullmatch(r'\+?[0-9]{4,17}', text):
        return None
    if text.startswith('+'):
        return parsed(text, None, phonenumbers.is_possible_number)
    region = default_region() if region is None else region
    found = parsed(text, region, phonenumbers.is_valid_number) if region else None
    if not found and len(text) >= 11 and text[0] != '0':
        found = parsed('+' + text, None, phonenumbers.is_possible_number)
    return found


def parsed(text, region, accept):
    import phonenumbers
    try:
        number = phonenumbers.parse(text, region)
    except phonenumbers.NumberParseException:
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164).lstrip('+') if accept(number) else None


def default_region():
    """Two-letter code of the System Settings country, or ''."""
    import frappe
    from frappe.geo.country_info import get_country_info
    country = frappe.db.get_single_value('System Settings', 'country')
    code = (get_country_info(country) or {}).get('code') if country else None
    return code.upper() if isinstance(code, str) and len(code) == 2 else ''


def contact_identities(person):
    """Provider identities typed on a Frappe Contact: WhatsApp numbers and email addresses."""
    numbers = [row.phone for row in person.get('phone_nos') or []] + [person.get('mobile_no'), person.get('phone')]
    emails = [row.email_id for row in person.get('email_ids') or []] + [person.get('email_id')]
    identities = {'WhatsApp': {phone_number(value) for value in numbers if value}, 'Email': set()}
    for value in filter(None, emails):
        try:
            identities['Email'].add(normalize('Email', value))
        except ValueError:
            continue
    identities['WhatsApp'].discard(None)
    return identities


def bindings(channel, provider, value):
    """Find canonical aliases without rewriting pre-normalization stored keys."""
    import frappe
    canonical = normalize(provider, value)
    start = 0
    while True:
        rows = frappe.get_all('Relay Contact Endpoint', filters={'channel': channel},
            fields=['name', 'endpoint', 'relay_contact', 'verified'], order_by='name asc',
            limit_start=start, limit_page_length=500)
        for row in rows:
            try:
                matches = normalize(provider, row.endpoint) == canonical
            except ValueError:
                continue
            if matches:
                yield row
        if len(rows) < 500:
            break
        start += len(rows)


def contacts_by_phone(number=None, *, region=None):
    """Normalized number -> its Frappe Contacts: ones with a Relay Contact first, then ones linked to a Customer, then oldest.
    With a number, only Contacts whose stored phones end in its last ten digits are read."""
    import frappe
    digits = lambda column: f"REPLACE(REPLACE(REPLACE(REPLACE(REPLACE({column},' ',''),'-',''),'(',''),')',''),'.','') LIKE %(tail)s"
    narrow = 'WHERE ' + ' OR '.join(map(digits, ('p.phone', 'c.mobile_no', 'c.phone'))) if number else ''
    rows = frappe.db.sql("""SELECT c.name, c.creation, p.phone, c.mobile_no, c.phone contact_phone, r.name relay,
            EXISTS(SELECT 1 FROM `tabDynamic Link` l WHERE l.parent = c.name AND l.parenttype = 'Contact'
                AND l.link_doctype = 'Customer') customer
        FROM `tabContact` c LEFT JOIN `tabContact Phone` p ON p.parent = c.name AND p.parenttype = 'Contact'
        LEFT JOIN `tabRelay Contact` r ON r.contact = c.name """ + narrow, {'tail': '%' + (number or '')[-10:]}, as_dict=True)
    rows.sort(key=lambda row: (not row.relay, not row.customer, row.creation, row.name))
    result = {}
    for row in rows:
        for value in (row.phone, row.mobile_no, row.contact_phone):
            found = phone_number(value, region) if value else None
            if found and row.name not in result.setdefault(found, []):
                result[found].append(row.name)
    return result
