"""Inbox rows by business record: one row for each readable record that the visible chats link to,
and one contact row for each visible chat that no readable record covers."""
import json
import re

import frappe
from frappe.query_builder.terms import NamedParameterWrapper

from relay_core.business_access import MAX_LINKS

PAGE = 30
MAX_WORDS = 5
LINKS = "l.parent=f.contact AND l.parenttype='Contact' AND l.parentfield='links'"
ENABLED = "SELECT t.business_doctype FROM `tabRelay Contact Type` t WHERE t.enabled=1"


def like(text):
    return '%' + text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def search_values(query):
    """Every word must be in the name, in any order; a number or email matches the chat endpoints."""
    words = query.split()[:MAX_WORDS]
    values = {f'word{index}': like(word) for index, word in enumerate(words)}
    values['prefix'] = like(query.strip())[1:]
    digits = ''.join(character for character in query if character.isdigit())
    if '@' in query:
        values['endpoint'] = like(query.strip())
    elif len(digits) >= 4 and len(digits) >= len(query.replace(' ', '')) - 2:
        values['endpoint'] = like(digits)
    return values


def words_match(column, values):
    return '(' + ' AND '.join(f'{column} LIKE %({key})s' for key in values if key.startswith('word')) + ')'


def endpoint_match(contact, values):
    if 'endpoint' not in values:
        return '0'
    return (f'{contact} IN (SELECT e.relay_contact FROM `tabRelay Contact Endpoint` e '
            f'WHERE e.endpoint LIKE %(endpoint)s)')


def contact_search(query):
    """The Relay Contact condition for a search: all words in the name, or a number or email of the chat."""
    from pypika.terms import Criterion
    contact = frappe.qb.DocType('Relay Contact')
    words = query.split()[:MAX_WORDS]
    condition = Criterion.all([contact.display_name.like(like(word)) for word in words])
    values = search_values(query)
    if 'endpoint' in values:
        endpoints = frappe.qb.DocType('Relay Contact Endpoint')
        condition = condition | contact.name.isin(
            frappe.qb.from_(endpoints).select(endpoints.relay_contact).where(endpoints.endpoint.like(values['endpoint'])))
    return condition


def bind(values, value):
    """A placeholder for one value of a raw statement; the value goes to the database driver, never into the SQL text."""
    key = f'qb{len(values)}'
    values[key] = value
    return f'%({key})s'


class Bound(NamedParameterWrapper):
    """Binds each string of a generated query into the statement values."""

    def __init__(self, values):
        self.parameters = values

    def get_sql(self, param_value, **kwargs):
        return '\0' + bind(self.parameters, param_value)[2:-2] + '\0'


def embedded(query, values):
    """Generated SQL inside a statement that takes %(name)s values. Strings are bound into `values`;
    any other percent sign is escaped."""
    sql = query.get_sql(param_wrapper=Bound(values)).replace('%', '%%')
    return re.sub('\0(qb\\d+)\0', r'%(\1)s', sql)


def scoped_types(business_type=None):
    from relay_core.api import business_types
    return [doctype for doctype in business_types() if not business_type or business_type == doctype]


def record_query(doctype, fields, business_name=None):
    query = frappe.qb.get_query(doctype, fields=fields, ignore_permissions=False, order_by='')
    return query.where(frappe.qb.DocType(doctype).name == business_name) if business_name else query


def readable_records(values, business_type=None, business_name=None):
    """Readable records of the enabled business types, under each type's permission query, with their titles."""
    parts = []
    for doctype in scoped_types(business_type):
        meta = frappe.get_meta(doctype)
        title = meta.title_field if meta.title_field and meta.has_field(meta.title_field) else 'name'
        query = record_query(doctype, ['name', title], business_name)
        parts.append(f"SELECT {bind(values, doctype)} doctype, x.`name` name, COALESCE(NULLIF(x.`{title}`, ''), x.`name`) title "
                     f'FROM ({embedded(query, values)}) x')
    return ' UNION ALL '.join(parts) or "SELECT '' doctype, '' name, '' title FROM DUAL WHERE 0"


def readable_condition(values, alias, business_type=None, business_name=None):
    """A semi-join per readable business type, so only linked records are probed."""
    clauses = [f'({alias}.link_doctype={bind(values, doctype)} AND {alias}.link_name IN '
               f'({embedded(record_query(doctype, ["name"], business_name), values)}))' for doctype in scoped_types(business_type)]
    return '(' + (' OR '.join(clauses) or '0') + ')'


def unread_sql(values, channels):
    from relay_core.inbox import _unread_query
    query = _unread_query(['relay_contact', 'business_doctype', 'business_name'])
    if channels:
        query = query.where(frappe.qb.DocType('Relay Message').channel.isin(channels))
    return embedded(query, values)


def time_column():
    has_column = frappe.conf.db_type != 'postgres' and frappe.db.has_column('Relay Message', 'relay_timeline_time')
    return 'm.relay_timeline_time' if has_column else 'COALESCE(m.sent_at, m.creation)'


def enabled_types():
    return sorted(set(frappe.get_all('Relay Contact Type', filters={'enabled': 1}, pluck='business_doctype')))


def candidate_sql(values, alias):
    """True when link `alias` is a business_access.candidates choice: an enabled type whose record exists."""
    clauses = []
    for doctype in enabled_types():
        table = frappe.qb.DocType(doctype)
        clauses.append(f'({alias}.link_doctype={bind(values, doctype)} AND {alias}.link_name IN '
                       f'({embedded(frappe.qb.from_(table).select(table.name), values)}))')
    return '(' + (' OR '.join(clauses) or '0') + ')'


def owner_sql(values):
    """True when unstamped messages of chat f belong to its readable record l, as business_access.primary decides:
    the chat's only candidate, or its marked primary. A Contact with more than MAX_LINKS raw links has no candidate."""
    links = "x.parent=f.contact AND x.parenttype='Contact' AND x.parentfield='links'"
    raw = f'(SELECT COUNT(*) FROM `tabDynamic Link` x WHERE {links})'
    count = f'(SELECT COUNT(DISTINCT x.link_doctype, x.link_name) FROM `tabDynamic Link` x WHERE {links} AND {candidate_sql(values, "x")})'
    return (f'({raw}<={MAX_LINKS} AND (f.primary_doctype=l.link_doctype AND f.primary_name=l.link_name '
            f'OR {count}=1))')


def latest_sql(owned):
    """The newest message of chat f that belongs to record l."""
    unstamped = " OR COALESCE(m.business_name, '')=''" if owned else ''
    return (f'(SELECT {time_column()} FROM `tabRelay Message` m WHERE m.relay_contact=f.name AND (m.business_doctype=l.link_doctype '
            f'AND m.business_name=l.link_name{unstamped}) ORDER BY {time_column()} DESC LIMIT 1)')


def record_rows_sql(chats, values, scope, searching, with_unread):
    """One row per readable record. Unstamped messages count only for the record that owns them, as in its thread."""
    titled = f"JOIN ({readable_records(values, *scope)}) b ON b.doctype=l.link_doctype AND b.name=l.link_name" if searching else ''
    readable = '1=1' if searching else readable_condition(values, 'l', *scope)
    record_match = words_match('b.title', values) if 'word0' in values else '0'
    rank = ('MIN(CASE WHEN b.title LIKE %(prefix)s THEN 0 WHEN ' + record_match + ' OR f.display_name LIKE %(prefix)s THEN 2 '
            'ELSE 4 END)') if searching else '0'
    owned = owner_sql(values)
    stamped = 'lm.business_doctype=l.link_doctype AND lm.business_name=l.link_name'
    activity = (f"CASE WHEN {stamped} OR COALESCE(lm.business_name, '')='' AND {owned} THEN f.activity "
                f'WHEN {owned} THEN COALESCE({latest_sql(True)}, f.creation) ELSE COALESCE({latest_sql(False)}, f.creation) END')
    unread = '0' if not with_unread else ('MAX((f.name, l.link_doctype, l.link_name) IN (SELECT u.relay_contact, u.business_doctype, u.business_name FROM unseen u) '
              f"OR f.name IN (SELECT u.relay_contact FROM unseen u WHERE COALESCE(u.business_name, '')='') AND {owned})")
    search = f"AND ({contact_match_sql(values)} OR {record_match})" if searching else ''
    return f"""SELECT l.link_doctype doctype, l.link_name record, MAX({activity}) activity,
            {rank} search_rank, {unread} has_unread, 0 is_unlinked
        FROM ({chats}) f JOIN `tabDynamic Link` l ON {LINKS}
        {titled}
        LEFT JOIN `tabRelay Message` lm ON lm.name=f.last_message
        WHERE {readable} {search}
        GROUP BY l.link_doctype, l.link_name"""


def contact_match_sql(values):
    return f"({words_match('f.display_name', values) if 'word0' in values else '0'} OR {endpoint_match('f.name', values)})"


def rows_sql(contacts, values, *, channels=None, business_type=None, business_name=None, unlinked=False, with_unread=True):
    """The WITH clause and the union of every inbox row: (doctype, record, activity, search_rank, has_unread, is_unlinked).

    A record row's activity is the newest message of its chats that belongs to it, so a chat linked to two
    records moves only the record it wrote to. Contact rows have an empty doctype. Every value is bound into `values`."""
    unseen = f'WITH unseen AS ({unread_sql(values, channels)})' if with_unread else ''
    chats = embedded(contacts, values)
    scope = (None if business_type == 'none' else business_type, business_name)
    searching = 'word0' in values or 'endpoint' in values
    parts = []
    if business_type != 'none' and not unlinked:
        parts.append(record_rows_sql(chats, values, scope, searching, with_unread))
    covered = '' if business_type == 'none' else f"""AND NOT EXISTS (SELECT 1 FROM `tabDynamic Link` l
        WHERE {LINKS} AND {readable_condition(values, 'l', *scope)})"""
    rank = ('CASE WHEN f.display_name LIKE %(prefix)s THEN 1 WHEN ' + (words_match('f.display_name', values) if 'word0' in values else '0')
            + ' THEN 3 ELSE 5 END') if searching else '0'
    unread_contact = 'f.name IN (SELECT u.relay_contact FROM unseen u)' if with_unread else '0'
    parts.append(f"""SELECT '' doctype, f.name record, f.activity, {rank} search_rank, {unread_contact} has_unread,
            NOT EXISTS (SELECT 1 FROM `tabDynamic Link` l WHERE {LINKS} AND l.link_doctype IN ({ENABLED})) is_unlinked
        FROM ({chats}) f WHERE 1=1 {covered} {'AND ' + contact_match_sql(values) if searching else ''}""")
    return unseen, ' UNION ALL '.join(parts)


def chats_query(contacts):
    """The scoped Relay Contact query with the columns rows_sql reads."""
    from pypika.functions import Coalesce
    contact = frappe.qb.DocType('Relay Contact')
    return contacts.select(contact.last_message, contact.primary_doctype, contact.primary_name,
                           Coalesce(contact.last_message_at, contact.creation).as_('activity'))


def encode_cursor(row):
    return json.dumps([int(row.search_rank), str(row.activity), row.doctype, row.record], separators=(',', ':'))


def decode_cursor(value):
    try:
        rank, activity, doctype, record = json.loads(value)
        valid = (isinstance(rank, int) and 0 <= rank <= 5 and all(isinstance(item, str) for item in (activity, doctype, record))
                 and len(doctype) <= 140 and len(record) <= 140)
        if not valid:
            raise ValueError
        return {'cursor_rank': rank, 'cursor_activity': frappe.utils.get_datetime(activity), 'cursor_doctype': doctype, 'cursor_record': record}
    except (TypeError, ValueError):
        frappe.throw('Invalid conversation cursor')


def page(contacts, *, query='', mode='all', after=None, since=None, channels=None, business_type=None, business_name=None):
    """One page of inbox rows: best search rank first, then newest activity.

    Ranks: a title that starts with the search, then all words in the name, then a number or email match;
    at each level a business record comes before a chat."""
    values = search_values(query) if query.strip() else {}
    unseen, sql = rows_sql(chats_query(contacts), values, channels=channels, business_type=business_type,
                   business_name=business_name, unlinked=mode == 'unlinked', with_unread=mode in ('unread', 'read'))
    where = {'unread': 'has_unread=1', 'read': 'has_unread=0', 'unlinked': "doctype='' AND is_unlinked=1"}.get(mode, '1=1')
    if after:
        values.update(decode_cursor(after))
        where += """ AND (search_rank>%(cursor_rank)s OR search_rank=%(cursor_rank)s AND (activity<%(cursor_activity)s
            OR activity=%(cursor_activity)s AND (doctype, record)<(%(cursor_doctype)s, %(cursor_record)s)))"""
    if since:
        values['since'] = since
        where += ' AND activity>=%(since)s'
    rows = frappe.db.sql(f"""{unseen} SELECT * FROM ({sql}) inbox_rows WHERE {where}
        ORDER BY search_rank, activity DESC, doctype DESC, record DESC LIMIT {PAGE + 1}""", values, as_dict=True)
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    return {'items': items(rows, contacts, channels), 'previous': None,
            'next': {'after': encode_cursor(rows[-1])} if more else None}


def counts(contacts, channels=None, business_type=None, business_name=None):
    """Row counts for the All, Unread, Read and Unlinked tabs, in one statement."""
    values = {}
    unseen, sql = rows_sql(chats_query(contacts), values, channels=channels, business_type=business_type, business_name=business_name)
    total, unread, unlinked = frappe.db.sql(f"""{unseen} SELECT COUNT(*), COALESCE(SUM(has_unread), 0), COALESCE(SUM(doctype='' AND is_unlinked), 0)
        FROM ({sql}) inbox_rows""", values)[0]
    return {'all': int(total), 'unread': int(unread), 'read': int(total) - int(unread), 'unlinked': int(unlinked)}


def items(rows, contacts, channels):
    """Record rows with title, newest message and unread count; contact rows as inbox.directory_items gives them."""
    from relay_core.inbox import directory_items
    contact = frappe.qb.DocType('Relay Contact')
    chat_names = [row.record for row in rows if not row.doctype]
    chats = {}
    if chat_names:
        found = contacts.where(contact.name.isin(chat_names)).run(as_dict=True)
        chats = {item['name']: dict(item, kind='contact') for item in directory_items(found, channels)}
    records = record_items([row for row in rows if row.doctype], contacts, channels)
    result = []
    for row in rows:
        item = records.get((row.doctype, row.record)) if row.doctype else chats.get(row.record)
        if item:
            result.append(dict(item, last_message_at=str(row.activity), search_rank=int(row.search_rank)))
    return result


def record_titles(pairs):
    """Titles of the records the user can read; a record missing here is never shown."""
    titles = {}
    for doctype in {pair[0] for pair in pairs}:
        meta = frappe.get_meta(doctype)
        title = meta.title_field if meta.title_field and meta.has_field(meta.title_field) else 'name'
        names = [pair[1] for pair in pairs if pair[0] == doctype]
        for row in frappe.get_list(doctype, filters={'name': ['in', names]}, fields=['name', title], limit_page_length=0):
            titles[(doctype, row.name)] = row.get(title) or row.name
    return titles


def record_chats(pairs, contacts):
    """Every visible chat of each record, newest first. Each chat carries `owner`: the record its unstamped messages belong to."""
    if not pairs:
        return {}
    from pypika import Tuple
    links = frappe.qb.DocType('Dynamic Link')
    linked = (frappe.qb.from_(links).select(links.parent, links.link_doctype, links.link_name)
              .where((links.parenttype == 'Contact') & (links.parentfield == 'links'))
              .where(Tuple(links.link_doctype, links.link_name).isin([Tuple(*pair) for pair in pairs])).run(as_dict=True))
    people = {}
    for row in linked:
        people.setdefault(row.parent, []).append((row.link_doctype, row.link_name))
    if not people:
        return {}
    owners = unstamped_owners(list(people))
    contact = frappe.qb.DocType('Relay Contact')
    rows = contacts.select(contact.last_message, contact.primary_doctype, contact.primary_name).where(
        contact.contact.isin(list(people))).run(as_dict=True)
    chats = {}
    for row in sorted(rows, key=lambda item: str(item.get('last_message_at') or item.creation), reverse=True):
        row.owner = owners(row)
        for pair in dict.fromkeys(people.get(row.contact, ())):
            chats.setdefault(pair, []).append(row)
    return chats


def contact_candidates(people):
    """business_access.candidates for many Contacts in a few statements: enabled links whose records exist,
    and none for a Contact with more than MAX_LINKS raw links."""
    from pypika.functions import Count
    links = frappe.qb.DocType('Dynamic Link')
    scope = (links.parenttype == 'Contact') & (links.parentfield == 'links')
    totals = (frappe.qb.from_(links).select(links.parent, Count('*')).where(scope).where(links.parent.isin(people))
              .groupby(links.parent).run())
    within = [parent for parent, total in totals if total <= MAX_LINKS]
    enabled = enabled_types()
    if not within or not enabled:
        return {}
    rows = (frappe.qb.from_(links).select(links.parent, links.link_doctype, links.link_name).distinct().where(scope)
            .where(links.parent.isin(within)).where(links.link_doctype.isin(enabled)).run())
    existing = set()
    for doctype in {row[1] for row in rows}:
        names = list({row[2] for row in rows if row[1] == doctype})
        existing.update((doctype, name) for name in frappe.get_all(doctype, filters={'name': ['in', names]}, pluck='name', limit_page_length=0))
    found = {}
    for parent, doctype, name in rows:
        if (doctype, name) in existing:
            found.setdefault(parent, set()).add((doctype, name))
    return found


def unstamped_owners(people):
    """A function that gives a chat's owner of unstamped messages, as business_access.primary decides."""
    candidates = contact_candidates(people)

    def owner(chat):
        found = candidates.get(chat.contact, set())
        if len(found) == 1:
            return next(iter(found))
        marked = (chat.get('primary_doctype'), chat.get('primary_name'))
        return marked if marked in found else None
    return owner


def business_scope(pair, owned):
    """The messages of one chat in a record's thread: those stamped to it, and unstamped ones when the record owns them."""
    message = frappe.qb.DocType('Relay Message')
    stamped = (message.business_doctype == pair[0]) & (message.business_name == pair[1])
    return stamped | message.business_name.isnull() | (message.business_name == '') if owned else stamped


def belongs(message, pair, chat):
    return ((message.business_doctype, message.business_name) == pair if message.business_name
            else chat.owner == pair)


def record_items(rows, contacts, channels):
    if not rows:
        return {}
    pairs = [(row.doctype, row.record) for row in rows]
    titles = record_titles(pairs)
    chats = record_chats([pair for pair in pairs if pair in titles], contacts)
    latest = pair_latest(chats, channels)
    unread = pair_unread(chats, channels)
    providers = dict(frappe.get_list('Relay Channel', fields=['name', 'channel'], as_list=True, limit_page_length=0))
    from relay_core.inbox import directory_preview
    result = {}
    for pair, group in chats.items():
        last = latest.get(pair) or {}
        if last.get('channel') not in providers:
            last = {}
        names = {chat.name: chat.display_name or chat.name for chat in group}
        result[pair] = {'kind': 'business', 'name': pair[0] + ':' + pair[1], 'id': pair[0] + ':' + pair[1],
                        'doctype': pair[0], 'record': pair[1], 'title': titles[pair], 'display_name': titles[pair],
                        'business': {'doctype': pair[0], 'name': pair[1]}, 'contact': last.get('relay_contact') or group[0].name,
                        'contact_name': names.get(last.get('relay_contact')) or names[group[0].name], 'contact_count': len(group),
                        'provider': providers.get(last.get('channel')), 'channel': last.get('channel'),
                        'latest_preview': directory_preview(last) if last else '', 'latest_at': last.get('sent_at') or last.get('creation'),
                        'unread': unread.get(pair, 0), 'unread_more': False,
                        'unlinked': False, 'starred': 0, 'folder': '', 'assignment': {}}
    return result


def message_order(message):
    return str(message.get('sent_at') or message.creation), message.name


def pair_latest(chats, channels):
    """The newest readable message of each record over all its chats, in at most two statements.

    A chat's newest message settles the record when it belongs there; older chats cannot beat it. Each newer chat
    whose newest message belongs elsewhere needs one indexed LIMIT 1 seek."""
    if not chats or (channels is not None and not channels):
        return {}
    from pypika.terms import ValueWrapper

    from relay_core.inbox import PREVIEW_FIELDS
    from relay_core.timeline import page_query
    message = frappe.qb.DocType('Relay Message')
    filters = {'channel': ['in', channels]} if channels is not None else {}
    newest = list({chat.last_message for group in chats.values() for chat in group if chat.get('last_message')})
    own = {row.name: row for row in page_query(PREVIEW_FIELDS, dict(filters, name=['in', newest]), len(newest)).run(as_dict=True)} if newest else {}
    base = page_query(PREVIEW_FIELDS, filters, 1)
    found, seeks, union = {}, [], None
    for pair, group in chats.items():
        for chat in group:
            last = own.get(chat.get('last_message'))
            if last and belongs(last, pair, chat):
                found[pair] = last
                break
            part = (base.select(ValueWrapper(len(seeks)).as_('pair_index')).where(message.relay_contact == chat.name)
                    .where(business_scope(pair, chat.owner == pair)))
            seeks.append(pair)
            union = part if union is None else union * part
    for row in union.run(as_dict=True) if union is not None else []:
        pair = seeks[int(row.pair_index)]
        if pair not in found or message_order(row) > message_order(found[pair]):
            found[pair] = row
    return found


def pair_unread(chats, channels):
    """Unread messages of each record over all its chats, in one statement: one seek per chat from its read position,
    grouped by the business each message belongs to."""
    if not chats or (channels is not None and not channels):
        return {}
    from pypika.functions import Count
    from pypika.terms import ValueWrapper

    from relay_core.inbox import READ_FIELDS, contact_unread, read_position, state_key, unread_base
    message = frappe.qb.DocType('Relay Message')
    names = list({chat.name for group in chats.values() for chat in group})
    states = {row.relay_contact: row for row in frappe.get_all('Relay Conversation State',
        filters={'state_key': ['in', [state_key(name) for name in names]]}, fields=['relay_contact', *READ_FIELDS])}
    base = unread_base(['relay_contact', 'business_doctype', 'business_name'])
    if channels is not None:
        base = base.where(message.channel.isin(channels))
    union = None
    for index, name in enumerate(names):
        unseen = contact_unread(base, name, read_position(states.get(name))).as_('unseen')
        part = (frappe.qb.from_(unseen).select(ValueWrapper(index), unseen.business_doctype, unseen.business_name, Count('*'))
                .groupby(unseen.business_doctype, unseen.business_name))
        union = part if union is None else union * part
    counts = {}
    for index, doctype, record, total in union.run():
        key = (names[int(index)], (doctype, record) if record else None)
        counts[key] = counts.get(key, 0) + int(total)
    result = {}
    for pair, group in chats.items():
        for chat in group:
            result[pair] = result.get(pair, 0) + counts.get((chat.name, pair), 0)
            if chat.owner == pair:
                result[pair] += counts.get((chat.name, None), 0)
    return result
