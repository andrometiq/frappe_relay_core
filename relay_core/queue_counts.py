"""Exact inbox queue counts with the inbox list's permission scope, cached briefly per user."""
import hashlib
import json

import frappe
from pypika.functions import Count
from relay_core.inbox_filters import channel_contacts
from relay_core.permissions import require_access

CACHE_SECONDS = 10
GENERATION_KEY = 'relay-queue-counts-generation'


def invalidate():
    """Start a new cache generation after the change commits, so no count outlives it."""
    frappe.db.after_commit.add(lambda: frappe.cache.set_value(GENERATION_KEY, frappe.generate_hash(length=10)))


COUNT_KEYS = ('all', 'unread', 'read', 'unread_messages')


@frappe.whitelist(methods=['GET'])
def read(medium=None, channel=None, channels=None, business_type=None, business_name=None, rows='contact'):
    """Conversation counts per inbox tab and the unread message total, under the inbox list's filters.

    `rows='business'` counts the rows of inbox.directory with the same option: business records and uncovered chats."""
    require_access()
    if rows not in ('contact', 'business'):
        frappe.throw('Invalid conversation rows')
    from relay_core.inbox_filters import business_filter, channel_names
    names = channel_names(medium, channel, channels)
    business = business_filter(business_type, business_name)
    generation = frappe.cache.get_value(GENERATION_KEY) or ''
    scope = json.dumps([names, business_type or '', business_name or '', rows])
    key = f'relay-queue-counts:{generation}:{frappe.session.user}:{hashlib.sha256(scope.encode()).hexdigest()}'
    counts = frappe.cache.get_value(key)
    if counts is None:
        counts = get_counts(names, business)
        if rows == 'business':
            counts = dict(counts, **business_counts(names, business, business_type, business_name))
        frappe.cache.set_value(key, counts, expires_in_sec=CACHE_SECONDS)
    return counts


def get_counts(channels=None, business=None):
    """`channels` limits the counts to these Relay Channels (None counts every channel); `business` is a Relay Contact condition."""
    if channels is not None and not channels:
        return dict.fromkeys(COUNT_KEYS, 0)
    message = frappe.qb.DocType('Relay Message')
    # One pass over unread messages gives both the conversation and the message total.
    unseen = unread_messages(channels, ['relay_contact']).where(message.relay_contact.isin(visible_contacts(business=business)))
    if channels:
        # EXISTS, not a nested IN: MariaDB then materializes the channel's contacts once instead of
        # copying every unread row into a duplicate-weedout table.
        from pypika.terms import ExistsCriterion
        endpoints = frappe.qb.DocType('Relay Contact Endpoint')
        unseen = unseen.where(ExistsCriterion(channel_contacts(channels).where(endpoints.relay_contact == message.relay_contact)))
    unseen = unseen.as_('unseen')
    conversations, messages = frappe.qb.from_(unseen).select(
        Count(unseen.relay_contact).distinct(), Count('*')).run()[0]
    total = count(visible_contacts(channels, business))
    # Every unread conversation is in the list, so Read is the rest of it.
    return {'all': total, 'unread': int(conversations), 'read': total - int(conversations), 'unread_messages': int(messages)}


def business_counts(channels=None, business=None, business_type=None, business_name=None):
    """All, Unread, Read and Unlinked rows when each readable business record is one row."""
    if channels is not None and not channels:
        return {'all': 0, 'unread': 0, 'read': 0, 'unlinked': 0}
    from relay_core import inbox_records
    from relay_core.inbox import filtered_contacts
    query = frappe.qb.get_query('Relay Contact', fields=['name', 'contact', 'display_name', 'last_message_at', 'creation'],
                                ignore_permissions=False, order_by='')
    return inbox_records.counts(filtered_contacts(query, channels, business), channels, business_type, business_name)


def visible_contacts(channels=None, business=None):
    """Relay Contacts under the same permission query and filters as inbox.directory."""
    from relay_core.inbox import filtered_contacts
    query = frappe.qb.get_query('Relay Contact', fields=['name'], ignore_permissions=False, order_by='')
    return filtered_contacts(query, channels, business)


def unread_messages(names, fields):
    from relay_core.inbox import _unread_query
    query = _unread_query(fields)
    if names:
        query = query.where(frappe.qb.DocType('Relay Message').channel.isin(names))
    return query


def count(query):
    return int(frappe.qb.from_(query.as_('scoped')).select(Count('*')).run()[0][0])
