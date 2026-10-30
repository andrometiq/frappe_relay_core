"""Explicit consent and ranked endpoints, scoped to one business and person."""
import hashlib
import json

import frappe
from relay_core.permissions import require_access


def scope_key(contact, business_doctype, business_name):
    return hashlib.sha256(json.dumps([contact, business_doctype, business_name]).encode()).hexdigest()


def validate(doc):
    require_access(configure=True)
    from relay_core.conversation_start import business_contact
    business_contact(doc.contact, doc.business_doctype, doc.business_name)
    binding = frappe.get_doc('Relay Contact Endpoint', doc.endpoint)
    if frappe.db.get_value('Relay Contact', binding.relay_contact, 'contact') != doc.contact:
        raise ValueError('Endpoint does not belong to this person')
    if doc.consent not in ('Granted', 'Denied') or not 1 <= int(doc.priority or 0) <= 100:
        raise ValueError('Choose consent and a priority from 1 to 100')
    doc.scope_key = scope_key(doc.contact, doc.business_doctype, doc.business_name)
    doc.preference_key = hashlib.sha256((doc.scope_key + ':' + doc.endpoint).encode()).hexdigest()
    previous = doc.get_doc_before_save()
    if previous and previous.preference_key != doc.preference_key:
        raise ValueError('Preference ownership is immutable')


def resolve(contact, business_doctype, business_name, *, channels=None, providers=None, previous_status=None):
    """Fallback is only selection before admission, or after proven rejection."""
    if previous_status not in (None, 'Rejected', 'Failed'):
        raise ValueError('An admitted or uncertain delivery cannot change channels')
    from relay_core.conversation_start import business_channels
    available = {row['endpoint']: row for row in business_channels(contact, business_doctype, business_name)}
    rows = frappe.get_all('Relay Channel Preference', filters={
        'scope_key': scope_key(contact, business_doctype, business_name), 'consent': 'Granted'},
        fields=['name', 'endpoint', 'priority'], order_by='priority asc, name asc')
    choices = [(row, available[row.endpoint]) for row in rows if row.endpoint in available
               and (channels is None or available[row.endpoint]['value'] in channels)
               and (providers is None or available[row.endpoint]['provider'] in providers)]
    if not choices:
        raise ValueError('No consented, available endpoint for this business and person')
    if len(choices) > 1 and choices[0][0].priority == choices[1][0].priority:
        raise ValueError('Equal channel priorities require an explicit choice')
    preference, choice = choices[0]
    return dict(channel=choice['value'], endpoint=choice['endpoint'], provider=choice['provider'],
                preference=preference.name, account=frappe.db.get_value('Relay Channel', choice['value'], 'account'))


def recheck(contact, business_doctype, business_name, selection):
    from relay_core.conversation_start import ensure_business_binding
    ensure_business_binding(contact, selection['channel'], business_doctype, business_name, selection['endpoint'])
    channel = frappe.get_doc('Relay Channel', selection['channel'])
    if channel.channel != selection['provider'] or channel.account != selection['account']:
        raise ValueError('Channel provider or account changed')
    row = frappe.get_doc('Relay Channel Preference', selection['preference'])
    if (row.scope_key != scope_key(contact, business_doctype, business_name)
            or row.endpoint != selection['endpoint'] or row.consent != 'Granted'):
        raise ValueError('Channel consent changed')


def permission(doc, user=None, permission_type=None):
    from relay_core.business_access import allowed_types
    return doc.business_doctype in allowed_types(user) and bool(frappe.db.exists(doc.business_doctype, doc.business_name))


def query(user=None):
    from relay_core.business_access import explicit_condition
    return explicit_condition('Relay Channel Preference', user)
