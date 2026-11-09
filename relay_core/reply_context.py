"""Everything an agent needs before it replies in one chat, read as the signed-in user.

It applies the same event and knowledge rules as the Relay AI, but gives only what the user can already read: a
section the user may not read is null. It works while AI features are off."""
import frappe

from relay_core.ai.event_memory import EVENT, MAX_EVENTS, available_events
from relay_core.ai.persona import DOCTYPE as PERSONA
from relay_core.ai.playbooks import DOCTYPE as PLAYBOOK

RECORD_FIELDS = 12
NO_SUMMARY_TYPES = frozenset({'Table', 'Table MultiSelect', 'Password', 'Code', 'HTML', 'Attach', 'Attach Image',
                              'Signature', 'Geolocation', 'JSON'})


def read(contact: str, limit: int = 20) -> dict:
    """The contact, its business record, persona, active events, knowledge, recent messages and the reply window."""
    from relay_core import api
    profile = api.contact_profile(contact)
    page = api.messages(contact, limit=limit)
    newest = page['items'][-1] if page['items'] else None
    company = frappe.db.get_value('Relay Channel', newest['channel'], 'company') if newest else None
    business = business_of(newest, profile)
    return {'contact': profile, 'company': company, 'business_record': record_summary(*business) if business else None,
            'persona': readable(PERSONA, lambda: persona_of(company)),
            'events': readable(EVENT, lambda: events_of(business, company)),
            'knowledge': readable(PLAYBOOK, lambda: knowledge_of(business, company)),
            'messages': page, 'reply_window': reply_window(page['items'])}


def readable(doctype, load):
    """`load()` when the user may read `doctype`, else None: the context never widens access."""
    return load() if frappe.has_permission(doctype, 'read') else None


def business_of(newest, profile) -> tuple[str, str] | None:
    """The record of the newest message, else the contact's primary record."""
    if newest and newest.get('business_doctype') and newest.get('business_name'):
        return newest['business_doctype'], newest['business_name']
    primary = profile.get('primary')
    return (primary['doctype'], primary['name']) if primary else None


def record_summary(doctype: str, name: str) -> dict | None:
    """The record title and its list-view fields the user may read, or None when the user cannot read the record."""
    from relay_core.business_access import allowed_types
    from relay_core.business_groups import title_field
    if doctype not in allowed_types() or not frappe.has_permission(doctype, 'read', doc=name):
        return None
    doc = frappe.get_doc(doctype, name)
    doc.apply_fieldlevel_read_permissions()
    fields = [field for field in frappe.get_meta(doctype).fields
              if field.in_list_view and field.fieldtype not in NO_SUMMARY_TYPES and doc.get(field.fieldname) not in (None, '')]
    return {'doctype': doctype, 'name': name, 'title': str(doc.get(title_field(doctype)) or name),
            'fields': [{'label': field.label or field.fieldname, 'value': doc.get(field.fieldname)}
                       for field in fields[:RECORD_FIELDS]]}


def persona_of(company) -> dict | None:
    from relay_core.ai.persona import find
    row = find(company, frappe.get_list)
    return {'persona_name': row.persona_name, 'instructions': row.instructions or ''} if row else None


def events_of(business, company) -> list:
    """The events the Relay AI may use for this business type and company today, with their own text."""
    if not business:
        return []
    rows = available_events(business[0], company, fields=('description',), reader=frappe.get_list)[:MAX_EVENTS]
    return [{key: row.get(key) for key in ('name', 'title', 'description', 'event_starts_on', 'event_ends_on',
                                           'available_to')} for row in rows]


def knowledge_of(business, company) -> list:
    """The standing rules the Relay AI follows for this business type and company."""
    from relay_core.ai.playbooks import global_rows
    return [{'title': row.title, 'instructions': row.instructions}
            for row in global_rows(business or (None, None), company, frappe.get_list)]


def reply_window(rows) -> dict:
    """The reply window of the newest incoming message; closed when the customer never wrote."""
    from relay_core.messaging import reply_window as window
    incoming = next((row for row in reversed(rows) if row.get('direction') == 'Incoming'), None)
    return window(incoming['name']) if incoming else {'open': False}
