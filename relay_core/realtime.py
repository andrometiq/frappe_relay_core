"""Payload-free invalidation; clients refetch through permission-checked APIs."""
import secrets
from contextlib import contextmanager
from contextvars import ContextVar
import frappe

incoming_batch = ContextVar('relay_incoming_batch', default=None)

RESOURCES = {
    'Relay Channel': 'channel_automation',
    'Relay AI Skill': 'skills', 'Relay Business Event Rule': 'business_events',
    'Relay Business Event Delivery': 'business_events',
    'Relay Message': 'messages', 'Relay Contact': 'contacts',
    'Relay Hub Event': 'incoming', 'Relay Ticket': 'tickets',
    'Relay Campaign': 'campaigns', 'Relay Campaign Recipient': 'campaigns',
    'Relay Conversation Summary': 'reports', 'Relay Notification': 'notifications',
    'Relay Case': 'cases', 'Relay Flow': 'flows', 'Relay Flow Run': 'flows',
    'Relay Automation Run': 'automation_runs', 'Relay Flow Action': 'flow_actions',
    'Relay Message Action': 'message_actions',
    'Relay Ticket Status': 'tickets', 'Relay Ticket Type': 'tickets',
}
# Sends and automation steps are frequent; only a ticket screen that shows the record re-reads.
TICKET_RECORDS = frozenset({'Relay Automation Run', 'Relay Flow Action', 'Relay Message Action'})


def changed(doc, method=None, messages=None, receipt=False):
    """`receipt` marks a delivery status change only, so lists and counts can skip it."""
    if doc.doctype == 'Relay Hub Event':
        return incoming_changed()
    kind = RESOURCES.get(doc.doctype)
    if not kind:
        return
    if doc.doctype in TICKET_RECORDS:
        if has_ticket(doc):
            frappe.publish_realtime('relay_changed', {'kind': 'tickets'},
                room=frappe.realtime.get_doctype_room('Relay Ticket'), after_commit=True)
        return
    if doc.doctype == 'Relay Message':
        messages = messages or [doc.name]
    change = new_change() if messages else None
    # No document IDs, message text, addresses or identities in shared events.
    # Conversation rooms are permission checked, so they name the changed messages for a re-read of only those.
    frappe.publish_realtime('relay_changed', conversation_event(kind, receipt=receipt, change=change),
        room=frappe.realtime.get_doctype_room('Relay Ticket' if kind == 'tickets' else doc.doctype), after_commit=True)
    if doc.doctype == 'Relay Business Event Delivery' or doc.doctype == 'Relay Message' and doc.get('ticket'):
        frappe.publish_realtime('relay_changed', {'kind': 'tickets'},
            room=frappe.realtime.get_doctype_room('Relay Ticket'), after_commit=True)
    contact = doc.get('relay_contact')
    if contact:
        contact_changed(contact, kind, messages, receipt, change)
    if doc.get('business_doctype') and doc.get('business_name'):
        from relay_core.business_inbox import changed as business_changed
        business_changed(doc.business_doctype,doc.business_name,kind,messages,receipt,change)


def has_ticket(doc):
    """A ticket shows its automation runs, flow actions and the sends of its messages or notices."""
    if doc.doctype != 'Relay Message Action':
        return bool(doc.get('ticket'))
    try:
        payload = frappe.parse_json(doc.get('payload') or '{}')
    except ValueError:
        payload = None
    if isinstance(payload, dict) and (payload.get('ticket') or payload.get('delivery_episodes')):
        return True
    return bool(doc.get('source_message') and frappe.db.get_value('Relay Message', doc.source_message, 'ticket'))


COUNTED_KINDS = frozenset({'messages', 'reads', 'contacts', 'permissions'})


def new_change():
    """A random key that one message change carries in each room it is sent to. A chat list that gets it also from
    the open conversation's room knows the change is in that conversation; it is no document ID."""
    return secrets.token_hex(8)


def conversation_event(kind, messages=None, receipt=False, change=None):
    event = {'kind': kind, 'messages': sorted(set(messages))} if messages else {'kind': kind}
    if messages or change:
        event['change'] = change or new_change()
    return dict(event, receipt=1) if receipt else event


def contact_changed(contact, kind='messages', messages=None, receipt=False, change=None):
    if kind in COUNTED_KINDS and not receipt:
        from relay_core.queue_counts import invalidate
        invalidate()
    frappe.publish_realtime('relay_changed', conversation_event(kind, messages, receipt, change),
        doctype='Relay Contact', docname=contact, after_commit=True)


@contextmanager
def one_incoming_change():
    """Send the triage-list invalidation once for a projection batch, after its last event."""
    token = incoming_batch.set(False)
    try:
        yield
    finally:
        changed = incoming_batch.get()
        incoming_batch.reset(token)
    if changed:
        incoming_changed()


def incoming_changed():
    if incoming_batch.get() is not None:
        incoming_batch.set(True)
        return
    # Triage access does not grant REST access to raw Hub event payloads.
    from frappe.permissions import get_doctype_roles
    users = frappe.get_all('Has Role', filters={'parenttype':'User',
        'role':['in',get_doctype_roles('Relay Team', 'write')]}, pluck='parent', distinct=True)
    for user in set(users) | {'Administrator'}:
        frappe.publish_realtime('relay_changed', {'kind':'incoming'}, user=user, after_commit=True)
