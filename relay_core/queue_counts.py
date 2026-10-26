"""Exact inbox queue counts with the inbox list's permission scope, cached briefly per user."""
import frappe
from pypika.functions import Coalesce, Count
from relay_core.permissions import require_access

CACHE_SECONDS = 10
GENERATION_KEY = 'relay-queue-counts-generation'
MEDIUMS = (None, '', 'WhatsApp', 'Telegram', 'Email')


def invalidate():
    """Start a new cache generation after the change commits, so no count outlives it."""
    frappe.db.after_commit.add(lambda: frappe.cache.set_value(GENERATION_KEY, frappe.generate_hash(length=10)))


@frappe.whitelist(methods=['GET'])
def read(medium=None):
    """Conversation counts per inbox tab and the unread message total."""
    require_access()
    if medium not in MEDIUMS:
        frappe.throw('Invalid medium')
    generation = frappe.cache.get_value(GENERATION_KEY) or ''
    key = f'relay-queue-counts:{generation}:{frappe.session.user}:{medium or ""}'
    counts = frappe.cache.get_value(key)
    if counts is None:
        counts = get_counts(medium or None)
        frappe.cache.set_value(key, counts, expires_in_sec=CACHE_SECONDS)
    return counts


def get_counts(medium=None):
    contact = frappe.qb.DocType('Relay Contact')
    assignment = frappe.qb.DocType('Relay Conversation Assignment')
    message = frappe.qb.DocType('Relay Message')
    mine = frappe.qb.from_(assignment).select(assignment.relay_contact).where(
        assignment.assigned_to == frappe.session.user)
    assigned = frappe.qb.from_(assignment).select(assignment.relay_contact).where(
        (Coalesce(assignment.assigned_to, '') != '') | (Coalesce(assignment.team, '') != ''))
    unread_contacts = unread_messages(medium, ['relay_contact'])
    unread_total = unread_messages(medium, ['name']).where(message.relay_contact.isin(visible_contacts(medium)))

    return {
        'all': count(visible_contacts(medium)),
        'mine': count(visible_contacts(medium).where(contact.name.isin(mine))),
        'unassigned': count(visible_contacts(medium).where(contact.name.notin(assigned))),
        'unread': count(visible_contacts(medium).where(contact.name.isin(unread_contacts))),
        'unread_messages': count(unread_total),
    }


def visible_contacts(medium=None):
    """Relay Contacts under the same permission query and medium filter as inbox.directory."""
    query = frappe.qb.get_query('Relay Contact', fields=['name'], ignore_permissions=False, order_by='')
    if medium:
        contact = frappe.qb.DocType('Relay Contact')
        endpoints = frappe.qb.DocType('Relay Contact Endpoint')
        query = query.where(contact.name.isin(
            frappe.qb.from_(endpoints).select(endpoints.relay_contact).where(endpoints.channel.isin(medium_channels(medium)))))
    return query


def unread_messages(medium, fields):
    from relay_core.inbox import _unread_query
    query = _unread_query(fields)
    if medium:
        query = query.where(frappe.qb.DocType('Relay Message').channel.isin(medium_channels(medium)))
    return query


def medium_channels(medium):
    channels = frappe.qb.DocType('Relay Channel')
    return frappe.qb.from_(channels).select(channels.name).where(channels.channel == medium)


def count(query):
    return int(frappe.qb.from_(query.as_('scoped')).select(Count('*')).run()[0][0])
