"""Business details the admin enters once; Meta's signup window opens prefilled with them."""
import json
import re
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe

# Meta's WhatsApp business verticals.
CATEGORIES = (('AUTO', 'Automotive'), ('BEAUTY', 'Beauty, spa and salon'), ('APPAREL', 'Clothing and apparel'),
              ('EDU', 'Education'), ('ENTERTAIN', 'Entertainment'), ('EVENT_PLAN', 'Event planning and service'),
              ('FINANCE', 'Finance and banking'), ('GROCERY', 'Food and grocery'), ('GOVT', 'Public service'),
              ('HOTEL', 'Hotel and lodging'), ('HEALTH', 'Medical and health'), ('NONPROFIT', 'Non-profit'),
              ('PROF_SERVICES', 'Professional services'), ('RETAIL', 'Shopping and retail'),
              ('TRAVEL', 'Travel and transportation'), ('RESTAURANT', 'Restaurant'), ('OTHER', 'Other'))
EMAIL = re.compile(r'[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,63}')
TIMEZONE = re.compile(r'UTC[+-](0\d|1[0-4]):[0-5]\d')
LIMITS = {'name': 100, 'email': 200, 'website': 200, 'display_name': 100, 'description': 256}


def utc_offset(zone):
    """'Asia/Kolkata' -> 'UTC+05:30'."""
    try:
        offset = datetime.now(ZoneInfo(zone)).utcoffset()
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return 'UTC+00:00'
    minutes = int(offset.total_seconds() // 60)
    sign = '-' if minutes < 0 else '+'
    return f'UTC{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}'


def company():
    if not frappe.db.exists('DocType', 'Company'):
        return None
    name = frappe.defaults.get_global_default('company')
    return frappe.db.get_value('Company', name, ['company_name', 'website', 'country'], as_dict=True) if name else None


def country_code(country):
    code = frappe.db.get_value('Country', country, 'code') if country else None
    return code.upper() if isinstance(code, str) and len(code) == 2 else ''


def defaults():
    """Prefill from the default company, System Settings and the current user."""
    found = company() or {}
    name = found.get('company_name') or frappe.db.get_single_value('System Settings', 'app_name') or frappe.local.site
    zone = frappe.db.get_single_value('System Settings', 'time_zone')
    return {'name': str(name)[:100], 'email': frappe.session.user if EMAIL.fullmatch(frappe.session.user or '') else '',
            'website': found.get('website') or '', 'no_website': not found.get('website'),
            'country': country_code(found.get('country') or frappe.db.get_single_value('System Settings', 'country')),
            'timezone': utc_offset(zone), 'timezone_name': zone or '', 'display_name': str(name)[:100],
            'category': 'OTHER', 'description': ''}


def saved():
    """The saved draft, or None before the admin saved one."""
    raw = frappe.db.get_single_value('Relay Settings', 'onboarding_draft')
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    return value if isinstance(value, dict) and value.get('name') else None


def options():
    return {'countries': [{'value': row.code.upper(), 'label': row.name} for row in frappe.get_all(
                'Country', fields=['name', 'code'], filters={'code': ['is', 'set']}, order_by='name asc',
                limit_page_length=400) if len(row.code or '') == 2],
            'categories': [{'value': value, 'label': label} for value, label in CATEGORIES]}


def checked(values):
    """The draft fields, or a ValidationError naming the first wrong one."""
    values = frappe.parse_json(values) if isinstance(values, str) else values
    if not isinstance(values, dict):
        frappe.throw('Send the business details as an object')
    draft = {key: ' '.join(str(values.get(key) or '').split()) for key in
             ('name', 'email', 'website', 'country', 'timezone', 'timezone_name', 'display_name', 'category')}
    draft['description'] = str(values.get('description') or '').strip()
    draft['no_website'] = bool(values.get('no_website'))
    for key, limit in LIMITS.items():
        if len(draft[key]) > limit:
            frappe.throw(f'{key.replace("_", " ").capitalize()} can have at most {limit} characters')
    if not draft['name']:
        frappe.throw('Enter the business name')
    if not EMAIL.fullmatch(draft['email']):
        frappe.throw('Enter a valid business email')
    if draft['no_website']:
        draft['website'] = ''
    elif not website(draft['website']):
        frappe.throw('Enter the website as https://example.com, or select "We have no website"')
    if not frappe.db.exists('Country', {'code': draft['country'].lower()}) or len(draft['country']) != 2:
        frappe.throw('Choose the country')
    if not TIMEZONE.fullmatch(draft['timezone']):
        frappe.throw('Choose the time zone')
    if draft['category'] not in dict(CATEGORIES):
        frappe.throw('Choose the business category')
    draft['display_name'] = draft['display_name'] or draft['name']
    draft['country'] = draft['country'].upper()
    return draft


def website(value):
    parsed = urlsplit(value)
    return parsed.scheme in ('http', 'https') and bool(parsed.hostname) and '.' in parsed.hostname


def save(values):
    draft = checked(values)
    frappe.db.set_single_value('Relay Settings', 'onboarding_draft', json.dumps(draft, sort_keys=True))
    return draft


def prefill(draft):
    """Meta's `extras.setup` values; the Hub builds the rest of the extras."""
    business = {'name': draft['name'], 'email': draft['email'], 'country': draft['country'],
                'timezone': draft['timezone'], **({'website': draft['website']} if draft.get('website') else {})}
    phone = {'display_name': draft['display_name'], 'category': draft['category'],
             **({'description': draft['description']} if draft.get('description') else {})}
    return {'business': business, 'phone': phone}
