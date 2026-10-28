"""Inbox rows by business record, read from Relay Chat: one row per readable record, and one row per visible chat
whose messages name no record."""
import json

import frappe

from relay_core.relay_chats import CHAT, CONTACT

PAGE = 30
MAX_WORDS = 5
FIELDS = ['name', 'business_doctype', 'business_name', 'title', 'last_contact', 'last_message_preview', 'last_message_at',
          'last_channel', 'unread_count']


def like(text):
    return '%' + text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def search_values(query):
    """Every word must be in the name, in any order; a number or email matches the chat endpoints."""
    words = query.split()[:MAX_WORDS]
    values = {f'word{index}': like(word) for index, word in enumerate(words)}
    digits = ''.join(character for character in query if character.isdigit())
    if '@' in query:
        values['endpoint'] = like(query.strip())
    elif len(digits) >= 4 and len(digits) >= len(query.replace(' ', '')) - 2:
        values['endpoint'] = like(digits)
    return values


def contact_search(query):
    """The Relay Contact condition for a search: all words in the name, or a number or email of the chat."""
    from pypika.terms import Criterion
    contact = frappe.qb.DocType('Relay Contact')
    condition = Criterion.all([contact.display_name.like(like(word)) for word in query.split()[:MAX_WORDS]])
    values = search_values(query)
    if 'endpoint' in values:
        condition = condition | contact.name.isin(endpoint_contacts(values['endpoint']))
    return condition


def endpoint_contacts(pattern):
    endpoints = frappe.qb.DocType('Relay Contact Endpoint')
    return frappe.qb.from_(endpoints).select(endpoints.relay_contact).where(endpoints.endpoint.like(pattern))


def scope_filters(mode='all', channels=None, business_type=None, business_name=None, contacts=None):
    """Relay Chat filters for a tab, channels, a business type or record (`none`: chats without one) and chosen chats."""
    filters = [[CHAT, 'is_unread', '=', 1]] if mode == 'unread' else [[CHAT, 'is_unread', '=', 0]] if mode == 'read' else []
    if mode == 'unlinked' or business_type == 'none':
        filters.append([CHAT, 'business_doctype', '=', CONTACT])
    elif business_type:
        filters.append([CHAT, 'business_doctype', '=', business_type])
        if business_name:
            filters.append([CHAT, 'business_name', '=', business_name])
    if channels is not None:
        filters.append([CHAT, 'last_channel', 'in', channels])
    if contacts is not None:
        filters.append([CHAT, 'last_contact', 'in', contacts])
    return filters


def search_filters(query):
    """A record whose title or name has every word, in order, or a chat whose last writer has that number or email."""
    words = query.split()[:MAX_WORDS]
    pattern = '%' + '%'.join(like(word)[1:-1] for word in words) + '%'
    found = [[CHAT, 'title', 'like', pattern], [CHAT, 'business_name', 'like', pattern]]
    values = search_values(query)
    if 'endpoint' in values:
        contacts = [row[0] for row in endpoint_contacts(values['endpoint']).limit(100).run()]
        found.append([CHAT, 'last_contact', 'in', contacts or ['']])
    return found


def encode_cursor(rows):
    """The last row's time and the names at that time, so rows sharing the time are neither repeated nor skipped."""
    at = rows[-1].last_message_at
    return json.dumps([str(at), [row.name for row in rows if row.last_message_at == at]], separators=(',', ':'))


def decode_cursor(value):
    try:
        at, names = json.loads(value)
        if not isinstance(at, str) or not isinstance(names, list) or not 0 < len(names) <= PAGE + 1 \
                or not all(isinstance(name, str) and len(name) <= 140 for name in names):
            raise ValueError
        return frappe.utils.get_datetime(at), names
    except (TypeError, ValueError):
        frappe.throw('Invalid conversation cursor')


def page(*, query='', mode='all', after=None, since=None, channels=None, business_type=None, business_name=None, contacts=None):
    """One page of inbox rows, newest activity first, in one Relay Chat query under its permission query."""
    filters = scope_filters(mode, channels, business_type, business_name, contacts)
    if after:
        at, names = decode_cursor(after)
        filters += [[CHAT, 'last_message_at', '<=', at], [CHAT, 'name', 'not in', names]]
    if since:
        filters.append([CHAT, 'last_message_at', '>=', since])
    rows = frappe.get_list(CHAT, fields=FIELDS, filters=filters, or_filters=search_filters(query) if query.strip() else None,
                           order_by='last_message_at desc, name desc', limit_page_length=PAGE + 1)
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    return {'items': items(rows), 'previous': None, 'next': {'after': encode_cursor(rows)} if more else None}


def counts(channels=None, business_type=None, business_name=None):
    """Row counts for the All, Unread, Read and Unlinked tabs and the unread message total, in one statement."""
    rows = frappe.get_list(CHAT, filters=scope_filters('all', channels, business_type, business_name), group_by='business_doctype',
                           fields=['business_doctype', {'COUNT': '*', 'as': 'total'}, {'SUM': 'is_unread', 'as': 'unread'},
                                   {'SUM': 'unread_count', 'as': 'messages'}], order_by='business_doctype')
    total, unread = (sum(int(row[field] or 0) for row in rows) for field in ('total', 'unread'))
    return {'all': total, 'unread': unread, 'read': total - unread,
            'unlinked': sum(int(row.total) for row in rows if row.business_doctype == CONTACT),
            'unread_messages': sum(int(row.messages or 0) for row in rows)}


def items(rows):
    providers = dict(frappe.get_list('Relay Channel', fields=['name', 'channel'], as_list=True, limit_page_length=0))
    chats = contact_rows([row.business_name for row in rows if row.business_doctype == CONTACT])
    result = []
    for row in rows:
        item = {'id': row.name, 'title': row.title, 'display_name': row.title, 'channel': row.last_channel,
                'provider': providers.get(row.last_channel), 'latest_preview': row.last_message_preview or '',
                'latest_at': row.last_message_at, 'last_message_at': str(row.last_message_at), 'unread': row.unread_count or 0,
                'unread_more': False, 'starred': 0, 'folder': '', 'unlinked': False, 'assignment': {}}
        if row.business_doctype == CONTACT:
            item.update(chats.get(row.business_name, {}), kind='contact', name=row.business_name)
        else:
            business = {'doctype': row.business_doctype, 'name': row.business_name}
            item.update(kind='business', name=row.business_doctype + ':' + row.business_name, doctype=row.business_doctype,
                        record=row.business_name, business=business, contact=row.last_contact)
        result.append(item)
    return result


def contact_rows(names):
    """Frappe Contact, link state, star and folder of the session user's chats on a page."""
    if not names:
        return {}
    from relay_core.contacts import linked_contacts
    from relay_core.inbox import state_key
    linked = linked_contacts(names)
    states = {row.relay_contact: row for row in frappe.get_all('Relay Conversation State', fields=['relay_contact', 'starred', 'folder'],
                                                               filters={'state_key': ['in', [state_key(name) for name in names]]})}
    people = dict(frappe.get_all(CONTACT, filters={'name': ['in', names]}, fields=['name', 'contact'], as_list=True))
    return {name: {'contact': people.get(name), 'unlinked': name not in linked, 'starred': (states.get(name) or {}).get('starred', 0),
                   'folder': (states.get(name) or {}).get('folder') or ''} for name in names}
