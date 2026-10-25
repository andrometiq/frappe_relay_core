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


def contact_number(value):
    """WhatsApp digits for a typed Contact number; national numbers take the system country code."""
    digits = re.sub(r'[ .+()\-]', '', value or '')
    if not digits.isdigit():
        return None
    if (value or '').strip().startswith('+'):
        number = digits
    elif digits.startswith('00'):
        number = digits[2:]
    elif digits.startswith('0') or len(digits) <= 10:
        code = default_calling_code()
        if not code:
            return None
        number = code + digits.lstrip('0')
    else:
        number = digits
    return number if re.fullmatch(r'[1-9][0-9]{6,14}', number) else None


def default_calling_code():
    import frappe
    from frappe.geo.country_info import get_country_info
    country = frappe.db.get_single_value('System Settings', 'country')
    code = (get_country_info(country) or {}).get('isd', '') if country else ''
    return code.lstrip('+')


def contact_identities(person):
    """Provider identities typed on a Frappe Contact: WhatsApp numbers and email addresses."""
    numbers = [row.phone for row in person.get('phone_nos') or []] + [person.get('mobile_no'), person.get('phone')]
    emails = [row.email_id for row in person.get('email_ids') or []] + [person.get('email_id')]
    identities = {'WhatsApp': {contact_number(value) for value in numbers if value}, 'Email': set()}
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
