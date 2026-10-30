"""Read-time business grouping. Relay type access applies before counts and pagination."""
import hashlib
import json
import re
import frappe
from relay_core.business_inbox import check_type
from relay_core.permissions import require_access

PAGE = 30


def configuration(doctype, config=None):
    """The single reader of configured levels, including the one-release scalar fallback.

    No permission checks here: permission predicates themselves use this configuration.
    Public callers check the business type before querying its records.
    """
    config = config if config is not None else frappe.get_cached_doc('Relay Contact Type', doctype)
    rows = config.get('grouping_fields') or []
    fields = [row.get('fieldname') for row in sorted(rows, key=lambda row: (int(row.get('priority') or 0), int(row.get('idx') or 0)))]
    if not fields and config.get('grouping_field'):
        fields = [config.get('grouping_field')]
    from relay_core.relay_core.doctype.relay_contact_type.relay_contact_type import _is_grouping_field
    meta = frappe.get_meta(doctype)
    if len(fields) > 6 or len(set(fields)) != len(fields) or any(not _is_grouping_field(meta.get_field(field)) for field in fields):
        frappe.throw('Business grouping configuration is invalid')
    return fields


def validate_text(value):
    if not isinstance(value, str) or len(value) > 140 or any(ord(c) < 32 for c in value):
        frappe.throw('Invalid group or search value')
    return value


def key(doctype, field, value):
    return hashlib.sha256(json.dumps([doctype, field, value]).encode()).hexdigest()


def install_indexes(doctype, config=None):
    for field in configuration(doctype, config=config):
        index = 'relay_group_' + hashlib.sha256(field.encode()).hexdigest()[:12]
        frappe.db.add_index(doctype, [field], index)


def group_filters(field, value):
    if value == '__all__':
        return []
    if not field:
        if value:
            frappe.throw('This business type has no grouping field')
        return []
    return [[field, '=', value]] if value else [[field, 'is', 'not set']]


def path_values(path, fields):
    path = frappe.parse_json(path) if isinstance(path, str) else ([] if path is None else path)
    if not isinstance(path, list) or len(path) > len(fields):
        frappe.throw('Invalid grouping path')
    for value in path:
        validate_text(value)
    return path


def page_start(start):
    if isinstance(start, bool) or not str(start).isdigit() or not 0 <= int(start) <= 100000:
        frappe.throw('Invalid page')
    return int(start)


def identifier(value):
    # Identifiers come only from configured DocTypes and validated metadata.
    return '`' + value.replace('`', '``') + '`'


def title_field(doctype):
    meta = frappe.get_meta(doctype)
    field = meta.get_field(meta.title_field) if meta.title_field else None
    return meta.title_field if field and not field.hidden and not field.permlevel else 'name'


def bound_query(query, values, prefix):
    """Keep QB parameters separate and escape percent literals in raw permission hooks."""
    sql, parameters = query.walk()
    values.update({prefix + name: value for name, value in parameters.items()})
    return re.sub(r'%\(([^)]+)\)s|%',
                  lambda match: '%(' + prefix + match[1] + ')s' if match[1] in parameters else match[0].replace('%', '%%'), sql)


def record_scope(doctype, values, prefix='record_'):
    """Relay business scope, or the existing Relay document/channel query hooks."""
    from relay_core.business_access import require_type, people_query
    if doctype == 'Contact':
        query = people_query(fields=['name'], order_by='')
    elif doctype in ('Relay Message', 'Relay Contact', 'Relay Channel'):
        query = frappe.qb.get_query(doctype, fields=['name'], ignore_permissions=False, order_by='')
    else:
        require_type(doctype)
        query = frappe.qb.get_query(doctype, fields=['name'], ignore_permissions=True, order_by='')
    return bound_query(query, values, prefix)


def message_scope(values, prefix='message_'):
    # Check the contact and channel too, as the business thread does before displaying a message.
    messages = record_scope('Relay Message', values, prefix)
    contacts = record_scope('Relay Contact', values, prefix + 'contact_')
    channels = record_scope('Relay Channel', values, prefix + 'channel_')
    return f"m.name IN ({messages}) AND m.relay_contact IN ({contacts}) AND m.channel IN ({channels})"


def aggregate(doctype, fields, path, query='', start=0, *, records=False, totals=False, after=None,
              group_search=False, contact_search=False, channels=None, business_name=None, contacts=False):
    validate_text(query)
    offset = page_start(start)
    title = 'b.' + identifier(title_field(doctype))
    values = {'doctype': doctype, 'query': '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%', 'start': offset}
    conditions = [f'b.name IN ({record_scope(doctype, values)})']
    for index, value in enumerate(path):
        column = 'b.' + identifier(fields[index])
        if value:
            conditions.append(f'{column}=%(level{index})s')
            values[f'level{index}'] = value
        else:
            conditions.append(f"({column} IS NULL OR {column}='')")
    field = fields[len(path)] if not records and not totals and len(path) < len(fields) else ''
    bucket = f"COALESCE(b.{identifier(field)}, '')" if field else 'b.name'
    if query:
        search = f'b.name LIKE %(query)s OR {title} LIKE %(query)s'
        if group_search:
            search = f'{bucket} LIKE %(query)s'
        elif contact_search:
            people = record_scope('Contact', values, 'search_contact_')
            search += f""" OR EXISTS (SELECT 1 FROM `tabDynamic Link` l JOIN `tabContact` p ON p.name=l.parent
                WHERE l.parenttype='Contact' AND l.parentfield='links' AND l.link_doctype=%(doctype)s
                  AND l.link_name=b.name AND p.name IN ({people})
                  AND (p.name LIKE %(query)s OR p.full_name LIKE %(query)s OR p.mobile_no LIKE %(query)s
                       OR p.phone LIKE %(query)s OR p.email_id LIKE %(query)s))"""
        conditions.append('(' + search + ')')
    if business_name:
        validate_text(business_name)
        conditions.append('b.name=%(business_name)s')
        values['business_name'] = business_name
    if after is not None:
        validate_text(after)
        conditions.append(f'{bucket}>%(after)s')
        values['after'] = after
    table = identifier('tab' + doctype)
    matching = f"SELECT b.name FROM {table} b WHERE {' AND '.join(conditions)}"
    limit = '' if totals else ' LIMIT 31 OFFSET %(start)s'
    if not field and not totals and (contacts or channels is None):
        # Record order does not depend on activity here, so only one page of records needs it.
        page = frappe.db.sql(matching + ' ORDER BY b.name ASC' + limit, values, as_dict=True)
        if not page:
            return []
        values['page'] = tuple(row['name'] for row in page)
        conditions.append('b.name IN %(page)s')
        limit = ''
    selection = '' if totals else (f'{bucket} AS value, ' if field else f"b.name, COALESCE(NULLIF({title}, ''), b.name) AS label, ")
    grouping = '' if totals else (' GROUP BY ' + bucket + (', ' + title if not field and title != 'b.`name`' else ''))
    order = '' if totals else (' ORDER BY value ASC' if field else ' ORDER BY b.name ASC')
    if contacts:
        people = record_scope('Contact', values, 'count_contact_')
        joins = f"""LEFT JOIN `tabDynamic Link` l ON l.link_doctype=%(doctype)s AND l.link_name=b.name
            AND l.parenttype='Contact' AND l.parentfield='links'
            LEFT JOIN `tabContact` p ON p.name=l.parent AND p.name IN ({people})"""
        metrics = 'COUNT(DISTINCT p.name) AS contact_count, 0 AS unread, 0 AS unread_records, NULL AS last_activity'
    else:
        joins, last_activity = activity(values, matching if totals and channels is None else None, channels)
        if channels is not None:
            # Match Inbox's channel filter: the channel of the newest readable activity.
            values['channels'] = tuple(channels) or ('',)
            conditions.append('activity.last_channel IN %(channels)s')
        metrics = f"""COALESCE(SUM(activity.unread_count), 0) AS unread,
            COUNT(DISTINCT CASE WHEN activity.unread_count>0 THEN b.name END) AS unread_records,
            {last_activity} AS last_activity"""
    rows = frappe.db.sql(f"""SELECT {selection}COUNT(DISTINCT b.name) AS record_count, {metrics}
        FROM {table} b {joins}
        WHERE {' AND '.join(conditions)}{grouping}{order}{limit}""", values, as_dict=True)
    for row in rows:
        for metric in ('unread', 'unread_records', 'record_count', 'contact_count'):
            if metric in row:
                row[metric] = int(row.get(metric) or 0)
        if field:
            row['label'] = row['value'] or 'Not set'
    return rows


def activity(values, matching=None, channels=None):
    """Join and newest-time expression for per-record unread counts and newest readable activity.

    With `matching` (a record query), the newest time is one lookup over those records instead of a per-record join.
    The newest channel is found only when a channel filter needs it.
    """
    from relay_core.relay_chats import query as chat_query
    if not chat_query():
        # Only an unrestricted viewer can use counters that include every contact.
        return ('LEFT JOIN `tabRelay Chat` activity ON activity.business_doctype=%(doctype)s AND activity.business_name=b.name',
                'MAX(activity.last_message_at)')
    from relay_core.inbox import _unread_query
    unread_names = bound_query(_unread_query(['name']), values, 'unread_')
    readable = f"COALESCE(m.legacy_triage, 0)=0 AND {message_scope(values)}"
    records = '%(page)s' if 'page' in values else None
    unread = f"""SELECT business_name, COUNT(*) AS unread_count
        FROM ({owned_messages(readable + f' AND m.name IN ({unread_names})', records)}) owned GROUP BY business_name"""
    if matching:
        newest = f'(SELECT MAX(message_at) FROM ({owned_messages(readable, f"({matching})")}) owned)'
        return f'LEFT JOIN ({unread}) activity ON activity.business_name=b.name', newest
    latest = f'SELECT business_name, MAX(message_at) AS last_message_at FROM ({owned_messages(readable, records)}) owned GROUP BY business_name'
    if channels is not None:
        latest = f"""SELECT newest.*, MAX(owned.channel) AS last_channel FROM ({latest}) newest
            JOIN ({owned_messages(readable, records)}) owned ON owned.business_name=newest.business_name AND owned.message_at=newest.last_message_at
            GROUP BY newest.business_name, newest.last_message_at"""
    return f"""LEFT JOIN (SELECT latest.*, unread.unread_count FROM ({latest}) latest
        LEFT JOIN ({unread}) unread ON unread.business_name=latest.business_name) activity ON activity.business_name=b.name""", 'MAX(activity.last_message_at)'


def owned_messages(condition, records=None):
    """Messages of %(doctype)s records that match `condition`, with their record: the named one, else the record that
    owns the contact's messages without one, as in the record's thread and Relay Chat. `records` (SQL) limits the records;
    each half applies it to its own column, as a filter over the union is not pushed down."""
    from relay_core.business_access import primary_sql
    from relay_core.timeline import timeline_sql
    only = f' AND {{}} IN {records}' if records else ''
    columns = f"{timeline_sql('m')} AS message_at, m.channel, m.name"
    return f"""SELECT m.business_name, {columns} FROM `tabRelay Message` m
            WHERE m.business_doctype=%(doctype)s AND COALESCE(m.business_name, '')<>'' AND {condition}{only.format('m.business_name')}
        UNION ALL
        SELECT linked.business_name, {columns} FROM `tabRelay Message` m
            JOIN ({primary_sql('%(doctype)s')}) linked ON linked.relay_contact=m.relay_contact
            WHERE (COALESCE(m.business_doctype, '')='' OR COALESCE(m.business_name, '')='') AND {condition}{only.format('linked.business_name')}"""


@frappe.whitelist(methods=['GET'])
def browse(doctype=None, path=None, query='', start=0, medium=None, channel=None, channels=None,
           business_type=None, business_name=None, contacts=0, path_fields=None):
    """Type tiles, then one configured level at a time, then paginated record tiles.

    The query searches the shown level: type labels, group values or record titles.
    """
    require_access()
    validate_text(query)
    offset = page_start(start)
    from relay_core.inbox_filters import channel_names, business_filter
    business_filter(business_type, business_name)  # Validate the same filters as Inbox counts.
    channels = channel_names(medium, channel, channels)
    if str(contacts) not in ('0', '1'):
        frappe.throw('Invalid contacts option')
    options = dict(channels=channels, business_name=business_name, contacts=str(contacts) == '1')
    if business_type == 'none' or (doctype and business_type and doctype != business_type):
        return {'items': [], 'next': None, 'kind': 'type', 'fields': []}
    if not doctype:
        from relay_core.business_types import list_types
        items = []
        for config in list_types():
            if not config.enabled:
                continue
            dt, label = config.business_doctype, config.label or config.business_doctype
            if (business_type and dt != business_type) or not matches(query, label, dt):
                continue
            counts = aggregate(dt, configuration(dt), [], totals=True, **options)[0]
            if (business_name or channels is not None) and not counts['record_count']:
                continue
            items.append(dict(counts, kind='type', doctype=dt, label=label))
        if options['contacts'] and matches(query, 'Not linked'):
            from relay_core.contacts import unlinked_people
            from relay_core.business_access import people_query
            count = people_query(fields=[{'COUNT': 'name', 'as': 'total'}], filters=[unlinked_people()]).run(as_dict=True)[0]['total']
            items.append({'kind': 'unlinked', 'label': 'Not linked', 'contact_count': int(count)})
        return {'items': items, 'next': None, 'kind': 'type', 'fields': []}
    check_type(doctype)
    fields = configuration(doctype)
    path = current_path(path, path_fields, fields)
    level = fields[len(path)] if len(path) < len(fields) else None
    kind = 'group' if level else 'record'
    rows = aggregate(doctype, fields, path, query, offset, group_search=bool(level), **options)
    return {'items': [dict(row, kind=kind, doctype=doctype, field=level) for row in rows[:PAGE]],
            'next': offset + PAGE if len(rows) > PAGE else None, 'kind': kind,
            'path': path, 'path_fields': fields[:len(path)],
            'fields': [{'fieldname': field, 'label': frappe.get_meta(doctype).get_field(field).label or field} for field in fields]}


def matches(query, *labels):
    return any(query.strip().lower() in label.lower() for label in labels)


def current_path(path, path_fields, fields):
    """A path saved under other grouping fields restarts at the type level instead of filtering the wrong field."""
    if path_fields is None:
        return path_values(path, fields)
    path_fields = frappe.parse_json(path_fields) if isinstance(path_fields, str) else path_fields
    if not isinstance(path_fields, list) or not all(isinstance(field, str) for field in path_fields):
        frappe.throw('Invalid grouping path')
    path = frappe.parse_json(path) if isinstance(path, str) else (path or [])
    if not isinstance(path, list) or len(path) != len(path_fields) or path_fields != fields[:len(path)]:
        return []
    return path_values(path, fields)


@frappe.whitelist(methods=['GET'])
def directory(doctype, query='', after=None, include_all=0, path=None, start=0):
    """Compatibility adapter for team pickers; counts use the same aggregation as tiles."""
    check_type(doctype)
    fields = configuration(doctype)
    selected = path_values(path, fields)
    validate_text(query)
    if str(include_all) not in ('0', '1'):
        frappe.throw('Invalid directory option')
    if len(selected) == len(fields):
        return {'field': '', 'items': [{'value': '', 'label': 'All records'}], 'next': None}
    rows = aggregate(doctype, fields, selected, query, start, after=after, group_search=True)
    page = rows[:PAGE]
    next_value = page[-1]['value'] if len(rows) > PAGE else None
    if str(include_all) == '1' and after is None and not query:
        page.insert(0, {'value': '__all__', 'label': 'All teams'})
    return {'field': fields[len(selected)], 'items': page, 'next': next_value}


@frappe.whitelist(methods=['GET'])
def records(doctype, group='', query='', start=0, path=None):
    """Legacy team records and record pickers, backed by the tile query."""
    check_type(doctype)
    fields = configuration(doctype)
    validate_text(group)
    selected = path_values(path, fields) if path is not None else ([group] if fields and group != '__all__' else [])
    rows = aggregate(doctype, fields, selected, query, start, records=True, contact_search=True)
    enrich_records(doctype, rows[:PAGE])
    field = fields[0] if fields else ''
    owner = frappe.db.get_value('Relay Business Group Claim', key(doctype, field, group), 'assigned_to') if rows else None
    return {'items': rows[:PAGE], 'next': int(start) + PAGE if len(rows) > PAGE else None,
            'assigned_to': owner, 'user': frappe.session.user}


def enrich_records(doctype, rows):
    """Restore Teams previews with page-wide queries, under the thread's permissions."""
    if not rows:
        return
    values = {'doctype': doctype, 'names': tuple(row['name'] for row in rows)}
    permitted = message_scope(values, 'preview_')
    latest = frappe.db.sql(f"""SELECT business_name, content FROM (
        SELECT m.business_name, m.content, ROW_NUMBER() OVER (PARTITION BY m.business_name
            ORDER BY COALESCE(m.sent_at, m.creation) DESC, m.name DESC) AS position
        FROM `tabRelay Message` m WHERE m.business_doctype=%(doctype)s AND m.business_name IN %(names)s
          AND COALESCE(m.legacy_triage, 0)=0 AND {permitted}) ranked WHERE position=1""", values, as_dict=True)
    people = record_scope('Contact', values, 'description_')
    linked = frappe.db.sql(f"""SELECT DISTINCT l.link_name, p.name, p.full_name FROM `tabDynamic Link` l
        JOIN `tabContact` p ON p.name=l.parent WHERE l.parenttype='Contact' AND l.parentfield='links'
          AND l.link_doctype=%(doctype)s AND l.link_name IN %(names)s AND p.name IN ({people})
        ORDER BY p.name""", values, as_dict=True)
    descriptions = {}
    for person in linked:
        descriptions.setdefault(person['link_name'], []).append(person['full_name'] or person['name'])
    from relay_core.summaries import business_previews
    summaries = business_previews(doctype, values['names'])
    messages = {row['business_name']: row['content'] for row in latest}
    for row in rows:
        names = descriptions.get(row['name'], [])[:3]
        row.update(last_message=(messages.get(row['name']) or '')[:240], summary=summaries.get(row['name'], '')[:500],
                   description='Contact: ' + ', '.join(names) if names else '')


def ticket_values(tickets, business_type=None):
    """One batched UNION query for a page, even when tickets span several business types."""
    grouped = {}
    for ticket in tickets:
        if ticket.get('business_doctype') and ticket.get('business_name'):
            grouped.setdefault(ticket['business_doctype'], set()).add(ticket['business_name'])
    columns = configuration(business_type) if business_type else []
    queries, values = [], {}
    from relay_core.business_access import allowed_types
    visible = allowed_types() if grouped else set()
    for index, (doctype, names) in enumerate(grouped.items()):
        if doctype not in visible:
            continue
        fields = columns if doctype == business_type else []
        pairs = ', '.join(f"{frappe.db.escape(field)}, COALESCE(b.{identifier(field)}, '')" for field in fields)
        title = 'b.' + identifier(title_field(doctype))
        queries.append(f"""SELECT %(type{index})s AS business_doctype, b.name AS business_name,
            COALESCE(NULLIF({title}, ''), b.name) AS business_title, JSON_OBJECT({pairs}) AS group_values
            FROM {identifier('tab' + doctype)} b
            WHERE b.name IN %(names{index})s AND b.name IN ({record_scope(doctype, values, f'ticket{index}_')})""")
        values.update({f'type{index}': doctype, f'names{index}': tuple(sorted(names))})
    found = frappe.db.sql(' UNION ALL '.join(queries), values, as_dict=True) if queries else []
    by_record = {(row['business_doctype'], row['business_name']): row for row in found}
    for ticket in tickets:
        row = by_record.get((ticket.get('business_doctype'), ticket.get('business_name')), {})
        ticket['business_title'] = row.get('business_title') or ''
        ticket['group_values'] = frappe.parse_json(row.get('group_values') or '{}')
    return [{'fieldname': field, 'label': frappe.get_meta(business_type).get_field(field).label or field} for field in columns]


@frappe.whitelist(methods=['POST'])
def claim(doctype, group='', release=False):
    require_access();check_type(doctype);field=next(iter(configuration(doctype)), '');validate_text(group)
    if group=='__all__':frappe.throw('Choose one business team')
    if not frappe.get_all(doctype,filters=group_filters(field,group),fields=['name'],page_length=1):
        frappe.throw('No accessible records in this group',frappe.PermissionError)
    name=key(doctype,field,group)
    # The unique claim identity makes concurrent creation safe; row lock serialises transitions.
    if not frappe.db.exists('Relay Business Group Claim',name):
        frappe.db.savepoint('relay_group_create')
        try:
            frappe.get_doc({'doctype':'Relay Business Group Claim','claim_key':name,'business_doctype':doctype,'grouping_field':field,'group_value':group}).insert(ignore_permissions=True)
        except frappe.DuplicateEntryError:
            frappe.db.rollback(save_point='relay_group_create')
    owner=frappe.db.get_value('Relay Business Group Claim',name,'assigned_to',for_update=True)
    if owner and owner!=frappe.session.user:
        frappe.throw('This group is already handled by another user')
    if release not in (False,True,0,1):frappe.throw('Invalid release action')
    frappe.db.set_value('Relay Business Group Claim',name,'assigned_to',None if release else frappe.session.user)
    return {'assigned_to':None if release else frappe.session.user}


def responsible(contact,user):
    from relay_core.business_access import candidates
    for dt,name in candidates(contact):
        field=next(iter(configuration(dt)), '')
        value=frappe.db.get_value(dt,name,field) if field else ''
        if frappe.db.get_value('Relay Business Group Claim',key(dt,field,value or ''),'assigned_to')==user:return True
    return False


def responsibility_condition(user,contact_expression):
    clauses=[]
    for config in frappe.get_all('Relay Contact Type',filters={'enabled':1},fields=['business_doctype'],limit_page_length=200):
        dt=config.business_doctype;field=next(iter(configuration(dt)), '')
        meta=frappe.get_meta(dt)
        if field and (not meta.get_field(field) or meta.get_field(field).fieldtype not in ('Link','Select','Data')):continue
        business=frappe.qb.DocType(dt);link=frappe.qb.DocType('Dynamic Link');relay=frappe.qb.DocType('Relay Contact');claim=frappe.qb.DocType('Relay Business Group Claim')
        from pypika.functions import Coalesce
        query=(frappe.qb.from_(relay).join(link).on((link.parent==relay.contact)&(link.parenttype=='Contact')&(link.parentfield=='links'))
            .join(business).on((business.name==link.link_name)&(link.link_doctype==dt))
            .join(claim).on((claim.business_doctype==dt)&(claim.grouping_field==field)&(claim.group_value==(Coalesce(business[field],'') if field else '')))
            .select(relay.name).where(claim.assigned_to==user))
        clauses.append(contact_expression+' IN ('+query.get_sql()+')')
    return '('+' OR '.join(clauses)+')' if clauses else '1=0'
