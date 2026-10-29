"""WhatsApp campaign recipients picked from Relay contacts by filter, with template values from contact and
linked record fields. Each matched number becomes a row of the same shape a sheet gives."""
import json

import frappe

from relay_core import bulk_campaigns, bulk_sheet
from relay_core.automation.contracts import canonical
from relay_core.permissions import contact_query

PHONE = 'phone'
CONTACT_FIELDS = {'first_name': 'First name', 'last_name': 'Last name', 'full_name': 'Full name',
                  'company_name': 'Company name', 'email_id': 'Email', 'designation': 'Designation'}
SEGMENT_FIELDS = ('customer_group', 'supplier_group', 'territory')
RECORD_FIELD_TYPES = ('Data', 'Link', 'Select', 'Int', 'Float', 'Currency', 'Date', 'Phone')
AUDIENCE_KEYS = {'tag', 'doctype', 'segments', 'number', 'last_message_from', 'last_message_to', 'include', 'exclude'}
MANUAL_LIMIT = 500
OPTION_LIMIT = 500
SAMPLE = 8
FROM = '`tabRelay Contact Endpoint` e JOIN `tabRelay Contact` ON `tabRelay Contact`.name=e.relay_contact'
OPTED_OUT = ("(e.marketing_opt_out=1 OR EXISTS (SELECT 1 FROM `tabRelay Channel Preference` p "
             "WHERE p.endpoint=e.name AND p.consent='Denied'))")


def linked_types() -> list[str]:
    return frappe.get_all('Relay Contact Type', filters={'enabled': 1}, pluck='business_doctype', order_by='business_doctype')


def is_plain(field) -> bool:
    return bool(field and not field.hidden and not field.permlevel)


def segment_fields(doctype: str) -> list:
    """The type's grouping field, then the customer or supplier group and territory when the DocType has them."""
    meta = frappe.get_meta(doctype)
    from relay_core.business_groups import configuration
    names = dict.fromkeys((*configuration(doctype), *SEGMENT_FIELDS))
    return [field for field in map(meta.get_field, names)
            if is_plain(field) and field.fieldtype in ('Link', 'Select', 'Data')]


def segment_options(doctype: str, field) -> list[str]:
    if field.fieldtype == 'Select':
        return [value for value in (field.options or '').split('\n') if value]
    if field.fieldtype == 'Link':
        return frappe.get_all(field.options, pluck='name', order_by='name asc', limit_page_length=OPTION_LIMIT)
    return frappe.get_all(doctype, filters={field.fieldname: ['is', 'set']}, pluck=field.fieldname, distinct=True,
                          order_by=f'{field.fieldname} asc', limit_page_length=OPTION_LIMIT)


def sources() -> list[dict]:
    """Values a template field can take for each contact: the Relay name, Contact fields and linked record fields."""
    rows = [{'value': 'relay.display_name', 'label': 'Contact · Display name'}]
    rows += [{'value': 'contact.' + field, 'label': 'Contact · ' + label} for field, label in CONTACT_FIELDS.items()]
    for doctype in linked_types():
        meta = frappe.get_meta(doctype)
        rows.append({'value': doctype + '.name', 'label': f'{doctype} · ID'})
        rows += [{'value': f'{doctype}.{field.fieldname}', 'label': f'{doctype} · {field.label}'}
                 for field in meta.fields if is_plain(field) and field.fieldtype in RECORD_FIELD_TYPES and field.label]
    return rows


@frappe.whitelist(methods=['GET'])
def options(name):
    """Filter choices, template value sources and a suggested mapping for a Draft campaign."""
    doc = bulk_campaigns.bulk(name)
    types = [{'doctype': doctype, 'segments': [
        {'field': field.fieldname, 'label': field.label, 'options': segment_options(doctype, field)}
        for field in segment_fields(doctype)]} for doctype in linked_types()]
    tags = frappe.get_all('Tag Link', filters={'document_type': 'Relay Contact'}, pluck='tag', distinct=True,
                          order_by='tag asc', limit_page_length=OPTION_LIMIT)
    found = sources()
    fields = json.loads(doc.arguments)['fields']
    return {'tags': tags, 'types': types, 'sources': found, 'mapping': suggest(fields, found),
            'time_zone': frappe.utils.get_system_timezone()}


def suggest(fields: list, found: list) -> dict:
    """A named template value takes the first source whose field has its name, and {{name}} the contact's
    display name; other values wait for a choice."""
    by_field = {'name': 'relay.display_name'}
    for row in found:
        by_field.setdefault(row['value'].rsplit('.', 1)[1], row['value'])
    chosen = {field['key']: by_field[field['name']] for field in fields if field.get('name') in by_field}
    return {'fields': chosen, 'fixed': {}}


def checked(audience) -> dict:
    """The audience without empty values. Raises a ValidationError for a value outside the offered choices."""
    audience = bulk_campaigns.parsed(audience) or {}
    if not isinstance(audience, dict) or set(audience) - AUDIENCE_KEYS:
        frappe.throw('Invalid contact filters')
    result = {key: str(audience.get(key) or '').strip() for key in ('tag', 'doctype', 'number')}
    if len(result['tag']) > 140:
        frappe.throw('Tag is too long')
    if result['doctype'] and result['doctype'] not in linked_types():
        frappe.throw('Choose a linked record type that Relay contacts use')
    if result['number'] and (not result['number'].isdigit() or len(result['number']) > 20):
        frappe.throw('Number filter takes digits only')
    result['segments'] = checked_segments(result['doctype'], audience.get('segments') or {})
    for key in ('last_message_from', 'last_message_to'):
        result[key] = str(frappe.utils.getdate(audience[key])) if audience.get(key) else ''
    for key in ('include', 'exclude'):
        result[key] = checked_contacts(audience.get(key) or [])
    return {key: value for key, value in result.items() if value}


def checked_segments(doctype: str, segments) -> dict:
    allowed = {field.fieldname for field in segment_fields(doctype)} if doctype else set()
    if not isinstance(segments, dict) or set(segments) - allowed:
        frappe.throw('Choose segments of the linked record type')
    return {field: str(value).strip() for field, value in segments.items() if str(value or '').strip()}


def checked_contacts(names) -> list[str]:
    if not isinstance(names, list) or len(names) > MANUAL_LIMIT or not all(isinstance(name, str) for name in names):
        frappe.throw(f'Add or remove at most {MANUAL_LIMIT} contacts by hand')
    return list(dict.fromkeys(names))


def base(channel: str) -> tuple[str, dict]:
    """Verified numbers on the campaign channel of Relay contacts the user may read."""
    permission = contact_query()
    return 'e.channel=%(channel)s AND e.verified=1' + (f' AND ({permission})' if permission else ''), {'channel': channel}


def matching(audience: dict) -> tuple[list[str], dict]:
    clauses, values = [], {}
    if audience.get('tag'):
        clauses.append("CONCAT(IFNULL(`tabRelay Contact`._user_tags, ''), ',') LIKE %(tag)s")
        values['tag'] = '%,' + literal(audience['tag']) + ',%'
    if audience.get('doctype'):
        segments = ''.join(f' AND b.`{field}`=%(segment_{index})s' for index, field in enumerate(audience.get('segments', {})))
        clauses.append(f'''EXISTS (SELECT 1 FROM `tabDynamic Link` l JOIN `tab{audience['doctype']}` b ON b.name=l.link_name
            WHERE l.parent=`tabRelay Contact`.contact AND l.parenttype='Contact' AND l.parentfield='links'
            AND l.link_doctype=%(doctype)s{segments})''')
        values['doctype'] = audience['doctype']
        values.update({f'segment_{index}': value for index, value in enumerate(audience.get('segments', {}).values())})
    if audience.get('number'):
        clauses.append('e.endpoint LIKE %(number)s')
        values['number'] = f"%{audience['number']}%"
    if audience.get('last_message_from'):
        clauses.append('`tabRelay Contact`.last_message_at >= %(last_from)s')
        values['last_from'] = audience['last_message_from']
    if audience.get('last_message_to'):
        clauses.append('`tabRelay Contact`.last_message_at < %(last_to)s')
        values['last_to'] = frappe.utils.add_days(audience['last_message_to'], 1)
    return clauses, values


def where(channel: str, audience: dict) -> tuple[str, dict]:
    """Contacts that match every filter, plus the ones added and less the ones removed. No filter picks every contact,
    unless contacts were added by hand: then only those."""
    sql, values = base(channel)
    clauses, matched = matching(audience)
    match = ' AND '.join(clauses)
    if audience.get('include'):
        added = '`tabRelay Contact`.name IN %(include)s'
        match = f'({match}) OR {added}' if match else added
        matched['include'] = tuple(audience['include'])
    sql += f" AND ({match or '1=1'})"
    if audience.get('exclude'):
        sql += ' AND `tabRelay Contact`.name NOT IN %(exclude)s'
        matched['exclude'] = tuple(audience['exclude'])
    return sql, {**values, **matched}


def literal(value: str) -> str:
    """Text a LIKE pattern matches as typed."""
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def contacts(sql: str, values: dict) -> list:
    return frappe.db.sql(f'''SELECT `tabRelay Contact`.name AS contact, `tabRelay Contact`.display_name AS name,
        e.endpoint AS number, {OPTED_OUT} AS opted_out FROM {FROM} WHERE {sql}
        ORDER BY `tabRelay Contact`.display_name, e.name LIMIT {SAMPLE}''', values, as_dict=True)


@frappe.whitelist(methods=['POST'])
def preview(name, audience):
    """Live count of the numbers the filters pick, how many of them opted out, and the first few."""
    doc = bulk_campaigns.bulk(name)
    sql, values = where(doc.channel, checked(audience))
    total, opted_out = frappe.db.sql(f'SELECT COUNT(*), CAST(IFNULL(SUM({OPTED_OUT}), 0) AS SIGNED) FROM {FROM} WHERE {sql}',
                                     values)[0]
    return {'count': int(total), 'opted_out': int(opted_out), 'sample': contacts(sql, values)}


@frappe.whitelist(methods=['GET'])
def search(name, query):
    """Contacts with a number on the campaign channel, by name or number, to add by hand."""
    doc = bulk_campaigns.bulk(name)
    query = str(query or '').strip()
    if not 2 <= len(query) <= 140:
        return []
    sql, values = base(doc.channel)
    sql += ' AND (`tabRelay Contact`.display_name LIKE %(query)s OR e.endpoint LIKE %(query)s)'
    return contacts(sql, {**values, 'query': '%' + literal(query) + '%'})


@frappe.whitelist(methods=['POST'])
def import_contacts(name, audience, mapping):
    """Replace the Draft's unsent rows with the matched contacts; template values come from the mapping."""
    doc = bulk_campaigns.bulk(name, ('Draft',))
    audience = checked(audience)
    mapping = bulk_campaigns.parsed(mapping)
    if not isinstance(mapping, dict):
        frappe.throw('Invalid value mapping')
    header = [PHONE, *(row['value'] for row in sources())]
    try:
        mapping = bulk_sheet.check_mapping({**mapping, 'phone': PHONE}, header, json.loads(doc.arguments)['fields'])
    except ValueError as exc:
        frappe.throw(str(exc))
    doc.recipient_filters, doc.column_map, doc.source_file = canonical(audience), canonical(mapping), None
    bulk_campaigns.start_import(doc)
    return bulk_campaigns.read(name)


def contact_rows(doc):
    """(row number, column -> text) for each matched number, in pages that each read their values at once."""
    sql, values = where(doc.channel, json.loads(doc.recipient_filters))
    mapping = json.loads(doc.column_map)
    used = set(mapping['fields'].values())
    number, after = 0, ''
    while True:
        rows = frappe.db.sql(f'''SELECT e.name AS endpoint, e.endpoint AS number, `tabRelay Contact`.contact,
            `tabRelay Contact`.display_name FROM {FROM} WHERE {sql} AND e.name > %(after)s ORDER BY e.name
            LIMIT {bulk_campaigns.CHUNK}''', {**values, 'after': after}, as_dict=True)
        if not rows:
            return
        filled = source_values(rows, used)
        for row in rows:
            number += 1
            if number > bulk_sheet.MAX_ROWS:
                raise ValueError(f'A campaign supports at most {bulk_sheet.MAX_ROWS} rows')
            yield number, {PHONE: row.number, **filled(row)}
        after = rows[-1].endpoint


def source_values(rows: list, used: set):
    """A function from a matched row to its source values; Contact and linked record fields are read per page."""
    people = [row.contact for row in rows]
    contact_fields = [source.split('.', 1)[1] for source in used if source.startswith('contact.')]
    persons = {row.name: row for row in frappe.get_all('Contact', filters={'name': ['in', people]},
               fields=['name', *contact_fields], limit_page_length=0)} if contact_fields else {}
    records = {}
    from relay_core.business_access import require_type
    for doctype, fields in record_fields(used).items():
        require_type(doctype)
        links = frappe.get_all('Dynamic Link', filters={'parenttype': 'Contact', 'parentfield': 'links',
                               'parent': ['in', people], 'link_doctype': doctype},
                               fields=['parent', 'link_name'], order_by='idx asc', limit_page_length=0)
        first = {}
        for link in links:
            first.setdefault(link.parent, link.link_name)
        readable = {row.name: row for row in frappe.get_all(doctype, filters={'name': ['in', list(set(first.values()))]},
                    fields=['name', *fields], limit_page_length=0)} if first else {}
        records[doctype] = {person: readable.get(record) for person, record in first.items()}

    def values(row) -> dict:
        result = {}
        for source in used:
            prefix, field = source.rsplit('.', 1)
            if prefix == 'relay':
                value = row.display_name
            elif prefix == 'contact':
                value = (persons.get(row.contact) or {}).get(field)
            else:
                value = (records[prefix].get(row.contact) or {}).get(field)
            result[source] = bulk_sheet.text(value)
        return result
    return values


def record_fields(used: set) -> dict[str, list[str]]:
    """Linked record fields the mapping reads, by DocType."""
    fields = {}
    for source in used:
        prefix, field = source.rsplit('.', 1)
        if prefix not in ('relay', 'contact'):
            fields.setdefault(prefix, [])
            if field != 'name':
                fields[prefix].append(field)
    return fields
