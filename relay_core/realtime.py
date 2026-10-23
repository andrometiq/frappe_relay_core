"""Payload-free invalidation; clients refetch through permission-checked APIs."""
import frappe

RESOURCES = {
    'Relay AI Skill': 'skills', 'Relay Business Event Rule': 'business_events',
    'Relay Business Event Delivery': 'business_events',
    'Relay Message': 'messages', 'Relay Contact': 'contacts',
    'Relay Hub Event': 'incoming', 'Relay Ticket': 'tickets',
    'Relay Campaign': 'campaigns', 'Relay Campaign Recipient': 'campaigns',
    'Relay Conversation Summary': 'reports', 'Relay Notification': 'notifications',
    'Relay Case': 'cases', 'Relay Flow': 'flows', 'Relay Flow Run': 'flows',
}

def changed(doc, method=None):
    if doc.doctype == 'Relay Hub Event':
        return incoming_changed()
    kind = RESOURCES.get(doc.doctype)
    if not kind:
        return
    # No document IDs, message text, addresses or identities in shared events.
    frappe.publish_realtime('relay_changed', {'kind': kind},
        room=frappe.realtime.get_doctype_room(doc.doctype), after_commit=True)
    contact = doc.get('relay_contact')
    if contact:
        contact_changed(contact, kind)
    if doc.get('business_doctype') and doc.get('business_name'):
        from relay_core.business_inbox import changed as business_changed
        business_changed(doc.business_doctype,doc.business_name,kind)


def contact_changed(contact, kind='messages'):
    frappe.publish_realtime('relay_changed', {'kind': kind},
        doctype='Relay Contact', docname=contact, after_commit=True)


def incoming_changed():
    # Triage access does not grant REST access to raw Hub event payloads.
    users = frappe.get_all('Has Role', filters={'parenttype':'User',
        'role':['in',['System Manager','Relay Communication Manager']]}, pluck='parent', distinct=True)
    for user in set(users) | {'Administrator'}:
        frappe.publish_realtime('relay_changed', {'kind':'incoming'}, user=user, after_commit=True)
