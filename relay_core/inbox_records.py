"""Inbox rows by business record, read from Relay Chat: one row per readable record, and one row per visible chat
whose messages name no record."""
import json

import frappe

from relay_core.relay_chats import CHAT, CONTACT

PAGE = 30
MAX_WORDS = 5
FIELDS = ['name', 'business_doctype', 'business_name', 'title', 'last_contact', 'last_message', 'last_message_preview',
          'last_message_at', 'last_channel', 'unread_count']
MAX_ROW_CHANNELS = 6


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
        filters.append(unlinked_condition())
    elif business_type:
        filters.append([CHAT, 'business_doctype', '=', business_type])
        if business_name:
            filters.append([CHAT, 'business_name', '=', business_name])
    if channels is not None:
        filters.append([CHAT, 'last_channel', 'in', channels])
    if contacts is not None:
        filters.append([CHAT, 'last_contact', 'in', contacts])
    return filters


def unlinked_condition():
    """A contact row is unlinked only when its person has no enabled business links.

    A legacy message without business context does not make a linked person unlinked.
    Keep this in SQL so linked rows cannot consume a page or inflate its queue count.
    """
    from relay_core.inbox import filtered_contacts
    contact = frappe.qb.DocType('Relay Contact')
    people = filtered_contacts(frappe.qb.from_(contact).select(contact.name), mode='unlinked')
    return frappe.qb.DocType(CHAT).business_name.isin(people)


def search_filters(query):
    """A record whose title or name has every word, in order, or a chat whose last writer has that number or email."""
    words = query.split()[:MAX_WORDS]
    pattern = '%' + '%'.join(like(word)[1:-1] for word in words) + '%'
    from relay_core.business_access import allowed_types
    from relay_core.business_groups import title_field
    chat = frappe.qb.DocType(CHAT)
    titles = (chat.business_doctype == CONTACT) & chat.title.like(pattern)
    for doctype in sorted(allowed_types()):
        field = title_field(doctype)
        if field == 'name':
            continue
        record = frappe.qb.DocType(doctype)
        matches = frappe.qb.from_(record).select(record.name).where(record[field].like(pattern))
        titles |= (chat.business_doctype == doctype) & chat.business_name.isin(matches)
    found = titles | chat.business_name.like(pattern)
    values = search_values(query)
    if 'endpoint' in values:
        contacts = [row[0] for row in endpoint_contacts(values['endpoint']).limit(100).run()]
        found |= chat.last_contact.isin(contacts or [''])
    return [found]


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
    if query.strip():
        filters += search_filters(query)
    rows = frappe.get_list(CHAT, fields=FIELDS, filters=filters,
                           order_by='last_message_at desc, name desc', limit_page_length=PAGE + 1)
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    return {'items': items(rows), 'previous': None, 'next': {'after': encode_cursor(rows)} if more else None}


def counts(channels=None, business_type=None, business_name=None):
    """Row counts for the All, Unread, Read, Unlinked and Assigned to me views and the unread message total, with the same business-link predicate as the queue."""
    rows = frappe.get_list(CHAT, filters=scope_filters('all', channels, business_type, business_name), group_by='business_doctype',
                           fields=['business_doctype', {'COUNT': '*', 'as': 'total'}, {'SUM': 'is_unread', 'as': 'unread'},
                                   {'SUM': 'unread_count', 'as': 'messages'}], order_by='business_doctype')
    total, unread = (sum(int(row[field] or 0) for row in rows) for field in ('total', 'unread'))
    unlinked = frappe.get_list(CHAT, filters=[*scope_filters('all', channels, business_type, business_name),
        [CHAT, 'business_doctype', '=', CONTACT], unlinked_condition()], fields=[{'COUNT': '*', 'as': 'total'}])
    return {'all': total, 'unread': unread, 'read': total - unread,
            'unlinked': int(unlinked[0].total or 0) if unlinked else 0, 'mine': assigned_count(channels, business_type, business_name),
            'unread_messages': sum(int(row.messages or 0) for row in rows)}


def assigned_count(channels=None, business_type=None, business_name=None):
    """Rows whose last writer is a chat assigned to the session user, as the Assigned to me view lists them."""
    from relay_core.inbox import chosen_contacts
    contacts = chosen_contacts(assigned='me')
    if not contacts:
        return 0
    found = frappe.get_list(CHAT, filters=scope_filters('all', channels, business_type, business_name, contacts), fields=[{'COUNT': '*', 'as': 'total'}])
    return int(found[0].total or 0) if found else 0


def items(rows):
    from relay_core.relay_chats import title
    providers = dict(frappe.get_list('Relay Channel', fields=['name', 'channel'], as_list=True, limit_page_length=0))
    chats = contact_rows([row.business_name for row in rows if row.business_doctype == CONTACT])
    channels, directions, tickets = row_channels(rows, providers), last_directions(rows), open_tickets(rows)
    result = []
    for row in rows:
        caption = row.title if row.business_doctype == CONTACT else title((row.business_doctype, row.business_name))
        item = {'id': row.name, 'title': caption, 'display_name': caption, 'channel': row.last_channel,
                'provider': providers.get(row.last_channel), 'latest_preview': row.last_message_preview or '',
                'latest_at': row.last_message_at, 'last_message_at': str(row.last_message_at), 'unread': row.unread_count or 0,
                'unread_more': False, 'starred': 0, 'folder': '', 'unlinked': False, 'assignment': {},
                'threads': channels.get(row.name, []), 'last_direction': directions.get(row.last_message),
                'open_tickets': tickets.get((row.business_doctype, row.business_name), 0)}
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


def row_channels(rows, providers):
    """Each row's contact endpoints as channel marks {channel, provider, endpoint, unread}, unread first.

    A record row shows the endpoints of its linked Contacts and a chat row its own; a thread with unread messages is
    marked even when it has no stored endpoint. Only readable channels count."""
    from relay_core.relay_chats import thread_unread
    endpoints = record_endpoints([row for row in rows if row.business_doctype != CONTACT])
    endpoints.update(chat_endpoints([row.business_name for row in rows if row.business_doctype == CONTACT]))
    result = {}
    for row in rows:
        key = (row.business_doctype, row.business_name)
        unread = {thread[1:] for thread in thread_unread(key)} if row.unread_count else set()
        marks = {(channel, endpoint): False for channel, endpoint in endpoints.get(key, ())}
        marks.update({thread: True for thread in unread})
        result[row.name] = sorted(({'channel': channel, 'provider': providers[channel], 'endpoint': endpoint, 'unread': flag}
                                   for (channel, endpoint), flag in marks.items() if channel in providers),
                                  key=lambda mark: (not mark['unread'], mark['provider'], mark['endpoint']))[:MAX_ROW_CHANNELS]
    return result


def record_endpoints(rows):
    """{(doctype, record): {(channel, endpoint)}} of the Contacts linked to each record, in one query."""
    if not rows:
        return {}
    endpoint, relay, link = (frappe.qb.DocType(name) for name in ('Relay Contact Endpoint', CONTACT, 'Dynamic Link'))
    found = (frappe.qb.from_(endpoint).join(relay).on(endpoint.relay_contact == relay.name).join(link).on(link.parent == relay.contact)
             .select(link.link_doctype, link.link_name, endpoint.channel, endpoint.endpoint)
             .where((link.parenttype == 'Contact') & (link.parentfield == 'links'))
             .where(link.link_doctype.isin(list({row.business_doctype for row in rows})))
             .where(link.link_name.isin(list({row.business_name for row in rows}))).limit(1000).run())
    wanted, result = {(row.business_doctype, row.business_name) for row in rows}, {}
    for doctype, name, channel, address in found:
        if (doctype, name) in wanted:
            result.setdefault((doctype, name), set()).add((channel, address or ''))
    return result


def chat_endpoints(contacts):
    if not contacts:
        return {}
    result = {}
    for row in frappe.get_all('Relay Contact Endpoint', filters={'relay_contact': ['in', contacts]},
                              fields=['relay_contact', 'channel', 'endpoint'], limit_page_length=1000):
        result.setdefault((CONTACT, row.relay_contact), set()).add((row.channel, row.endpoint or ''))
    return result


def last_directions(rows):
    names = [row.last_message for row in rows if row.last_message]
    if not names:
        return {}
    return dict(frappe.get_all('Relay Message', filters={'name': ['in', names]}, fields=['name', 'direction'], as_list=True))


def open_tickets(rows):
    """{(doctype, record): open ticket count} of the record rows the user can read tickets of."""
    records = [row for row in rows if row.business_doctype != CONTACT]
    if not records:
        return {}
    statuses = frappe.get_all('Relay Ticket Status', filters={'state': 'Open'}, pluck='name')
    if not statuses:
        return {}
    result = {}
    for ticket in frappe.get_list('Relay Ticket', fields=['business_doctype', 'business_name'], limit_page_length=1000, filters={
            'business_doctype': ['in', list({row.business_doctype for row in records})],
            'business_name': ['in', list({row.business_name for row in records})], 'ticket_status': ['in', statuses]}):
        key = (ticket.business_doctype, ticket.business_name)
        result[key] = result.get(key, 0) + 1
    return result
