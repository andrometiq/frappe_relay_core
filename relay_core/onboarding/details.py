"""Business details the admin enters once; Meta's signup window opens prefilled with them."""
import json
import re
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
import phonenumbers
from frappe.utils import strip_html

# Meta's WhatsApp business verticals.
CATEGORIES = (('AUTO', 'Automotive'), ('BEAUTY', 'Beauty, spa and salon'), ('APPAREL', 'Clothing and apparel'),
              ('EDU', 'Education'), ('ENTERTAIN', 'Entertainment'), ('EVENT_PLAN', 'Event planning and service'),
              ('FINANCE', 'Finance and banking'), ('GROCERY', 'Food and grocery'), ('GOVT', 'Public service'),
              ('HOTEL', 'Hotel and lodging'), ('HEALTH', 'Medical and health'), ('NONPROFIT', 'Non-profit'),
              ('PROF_SERVICES', 'Professional services'), ('RETAIL', 'Shopping and retail'),
              ('TRAVEL', 'Travel and transportation'), ('RESTAURANT', 'Restaurant'), ('OTHER', 'Other'))
EMAIL = re.compile(r'[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,63}')
TIMEZONE = re.compile(r'UTC[+-](0\d|1[0-4]):[0-5]\d')
PHONE_CODE = re.compile(r'[1-9]\d{0,3}')
PHONE_NUMBER = re.compile(r'\d{4,15}')
FIELDS = ('name', 'email', 'website', 'country', 'timezone', 'timezone_name', 'display_name', 'category',
          'street1', 'street2', 'city', 'state', 'zip_code', 'phone_code', 'phone_number')
LIMITS = {'name': 100, 'email': 200, 'website': 200, 'display_name': 100, 'description': 512,
          'street1': 140, 'street2': 140, 'city': 100, 'state': 100, 'zip_code': 20}
# Values an older, incomplete draft keeps; its time zone and host-name defaults are recomputed.
KEPT = ('name', 'email', 'website', 'no_website', 'country', 'display_name', 'category', 'description',
        'street1', 'street2', 'city', 'state', 'zip_code', 'phone_code', 'phone_number')
REQUIRED = {'street1': 'Enter the street address', 'city': 'Enter the city', 'state': 'Enter the state',
            'zip_code': 'Enter the PIN or ZIP code', 'description': 'Enter the business description'}


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
    fields = ['name', 'company_name', 'website', 'country', 'phone_no', 'company_description']
    return frappe.db.get_value('Company', name, fields, as_dict=True) if name else None


def country_code(country):
    code = frappe.db.get_value('Country', country, 'code') if country else None
    return code.upper() if isinstance(code, str) and len(code) == 2 else ''


def timezone_name(country):
    """The site's time zone when it belongs to the country, else the country's first time zone."""
    zone = frappe.db.get_single_value('System Settings', 'time_zone') or ''
    zones = str(frappe.db.get_value('Country', country, 'time_zones') or '').split() if country else []
    return zones[0] if zones and zone not in zones else zone


def business_name(found=None):
    """The default company, else the website or site app name. Frappe's default app name is no business name."""
    found = company() if found is None else found
    if (found or {}).get('company_name'):
        return found['company_name']
    for doctype in ('Website Settings', 'System Settings'):
        app_name = frappe.db.get_single_value(doctype, 'app_name')
        if app_name and app_name != 'Frappe':
            return app_name
    return ''


def company_address(found):
    """The company's primary address, else its first address."""
    if not found.get('name'):
        return {}
    names = frappe.get_all('Dynamic Link', filters={'link_doctype': 'Company', 'link_name': found['name'], 'parenttype': 'Address'},
                           pluck='parent', limit_page_length=20)
    rows = frappe.get_all('Address', filters={'name': ['in', names]} if names else {'name': ''},
                          fields=['address_line1', 'address_line2', 'city', 'state', 'pincode', 'phone'],
                          order_by='is_primary_address desc, creation asc', limit_page_length=1)
    return rows[0] if rows else {}


def business_phone(raw, country):
    """{'phone_code': '91', 'phone_number': '9000000000'} from a stored phone and the country."""
    try:
        parsed = phonenumbers.parse(raw or '', country or None)
    except phonenumbers.NumberParseException:
        parsed = None
    if parsed and parsed.country_code and parsed.national_number:
        return {'phone_code': str(parsed.country_code), 'phone_number': str(parsed.national_number)}
    code = phonenumbers.country_code_for_region(country) if country else 0
    return {'phone_code': str(code) if code else '', 'phone_number': ''}


def defaults():
    """Prefill from the default company, its address, System Settings and the current user, under any saved values."""
    found = company() or {}
    name = business_name(found)
    country = found.get('country') or frappe.db.get_single_value('System Settings', 'country')
    code = country_code(country)
    zone = timezone_name(country)
    address = company_address(found)
    computed = {'name': str(name)[:100], 'email': frappe.session.user if EMAIL.fullmatch(frappe.session.user or '') else '',
                'website': found.get('website') or '', 'no_website': not found.get('website'),
                'country': code, 'timezone': utc_offset(zone), 'timezone_name': zone,
                'display_name': str(name)[:100], 'category': 'OTHER',
                'description': strip_html(found.get('company_description') or '').strip()[:512],
                'street1': address.get('address_line1') or '', 'street2': address.get('address_line2') or '',
                'city': address.get('city') or '', 'state': address.get('state') or '', 'zip_code': address.get('pincode') or '',
                **business_phone(address.get('phone') or found.get('phone_no'), code)}
    kept = {key: value for key, value in (stored() or {}).items()
            if key in KEPT and value not in (None, '') and value != frappe.local.site}
    return {**computed, **kept}


def stored():
    raw = frappe.db.get_single_value('Relay Settings', 'onboarding_draft')
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def saved():
    """The saved draft, or None before the admin saved a complete one."""
    value = stored()
    return value if value and value.get('name') and value.get('phone_number') and value.get('street1') else None


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
    draft = {key: ' '.join(str(values.get(key) or '').split()) for key in FIELDS}
    draft['description'] = str(values.get('description') or '').strip()
    draft['no_website'] = bool(values.get('no_website'))
    draft['phone_code'] = draft['phone_code'].lstrip('+')
    draft['phone_number'] = re.sub(r'[\s()-]', '', draft['phone_number'])
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
    for key, message in REQUIRED.items():
        if not draft[key]:
            frappe.throw(message)
    if not PHONE_CODE.fullmatch(draft['phone_code']) or not PHONE_NUMBER.fullmatch(draft['phone_number']):
        frappe.throw('Enter the business phone as a country code and a number')
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
    business = {'name': draft['name'], 'email': draft['email'], 'country': draft['country'], 'timezone': draft['timezone'],
                'street_address1': draft['street1'], 'street_address2': draft.get('street2') or '', 'city': draft['city'],
                'state': draft['state'], 'zip_postal': draft['zip_code'],
                'phone': {'code': draft['phone_code'], 'number': draft['phone_number']},
                **({'website': draft['website']} if draft.get('website') else {})}
    phone = {'display_name': draft['display_name'], 'category': draft['category'], 'description': draft['description']}
    return {'business': business, 'phone': phone}
