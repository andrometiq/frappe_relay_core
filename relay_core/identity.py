"""Canonical provider identities shared by enrollment and projection."""
import re


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
