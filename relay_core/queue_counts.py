"""Exact inbox queue counts with the inbox list's permission scope, cached briefly per user."""
import frappe
from pypika.functions import Count
from relay_core.permissions import require_access

CACHE_SECONDS = 10
GENERATION_KEY = 'relay-queue-counts-generation'
MEDIUMS = (None, '', 'WhatsApp', 'Telegram', 'Email')


def invalidate():
    """Start a new cache generation after the change commits, so no count outlives it."""
    frappe.db.after_commit.add(lambda: frappe.cache.set_value(GENERATION_KEY, frappe.generate_hash(length=10)))


@frappe.whitelist(methods=['GET'])
def read(medium=None, channel=None):
    """Conversation counts per inbox tab and the unread message total; `channel` narrows a medium to one number."""
    require_access()
    if medium not in MEDIUMS:
        frappe.throw('Invalid medium')
    if channel and (not medium or channel not in medium_channels(medium)):
        frappe.throw('Invalid channel')
    generation = frappe.cache.get_value(GENERATION_KEY) or ''
    key = f'relay-queue-counts:{generation}:{frappe.session.user}:{medium or ""}:{channel or ""}'
    counts = frappe.cache.get_value(key)
    if counts is None:
        counts = get_counts(medium or None, [channel] if channel else None)
        frappe.cache.set_value(key, counts, expires_in_sec=CACHE_SECONDS)
    return counts


@frappe.whitelist(methods=['GET'])
def numbers():
    """Conversations per WhatsApp number of the site and in all of them, for the inbox number filter."""
    require_access()
    from relay_core.hub_channels import site_numbers
    names = [row['name'] for row in site_numbers('WhatsApp')]
    generation = frappe.cache.get_value(GENERATION_KEY) or ''
    key = f'relay-number-counts:{generation}:{frappe.session.user}'
    counts = frappe.cache.get_value(key)
    if counts is None or set(counts['numbers']) != set(names):
        counts = {'all': count(visible_contacts(names)) if names else 0,
                  'numbers': {name: count(visible_contacts([name])) for name in names}}
        frappe.cache.set_value(key, counts, expires_in_sec=CACHE_SECONDS)
    return counts


def get_counts(medium=None, channels=None):
    """`channels` limits the medium to these Relay Channels, such as one WhatsApp number."""
    names = channels or (medium_channels(medium) if medium else None)
    if names is not None and not names:
        return dict.fromkeys(('all', 'mine', 'unassigned', 'unread', 'unread_messages'), 0)
    contact = frappe.qb.DocType('Relay Contact')
    assignment = frappe.qb.DocType('Relay Conversation Assignment')
    message = frappe.qb.DocType('Relay Message')
    mine = frappe.qb.from_(assignment).select(assignment.relay_contact).where(
        assignment.assigned_to == frappe.session.user)
    from relay_core.inbox import assigned_contacts
    assigned = assigned_contacts()
    # One pass over unread messages gives both the conversation and the message total.
    unseen = unread_messages(names, ['relay_contact']).where(message.relay_contact.isin(visible_contacts()))
    if names:
        # EXISTS, not a nested IN: MariaDB then materializes the channel's contacts once instead of
        # copying every unread row into a duplicate-weedout table.
        from pypika.terms import ExistsCriterion
        endpoints = frappe.qb.DocType('Relay Contact Endpoint')
        unseen = unseen.where(ExistsCriterion(channel_contacts(names).where(endpoints.relay_contact == message.relay_contact)))
    unseen = unseen.as_('unseen')
    conversations, messages = frappe.qb.from_(unseen).select(
        Count(unseen.relay_contact).distinct(), Count('*')).run()[0]

    return {
        'all': count(visible_contacts(names)),
        'mine': count(visible_contacts(names).where(contact.name.isin(mine))),
        'unassigned': count(visible_contacts(names).where(contact.name.notin(assigned))),
        'unread': int(conversations),
        'unread_messages': int(messages),
    }


def visible_contacts(channels=None):
    """Relay Contacts under the same permission query and channel filter as inbox.directory."""
    query = frappe.qb.get_query('Relay Contact', fields=['name'], ignore_permissions=False, order_by='')
    if channels:
        query = query.where(frappe.qb.DocType('Relay Contact').name.isin(channel_contacts(channels)))
    return query


def channel_contacts(names):
    endpoints = frappe.qb.DocType('Relay Contact Endpoint')
    return frappe.qb.from_(endpoints).select(endpoints.relay_contact).where(endpoints.channel.isin(names))


def unread_messages(names, fields):
    from relay_core.inbox import _unread_query
    query = _unread_query(fields)
    if names:
        query = query.where(frappe.qb.DocType('Relay Message').channel.isin(names))
    return query


def medium_channels(medium):
    # Literal names, not a subquery: nested semi-joins made MariaDB copy every unread row into a weedout table.
    return frappe.get_all('Relay Channel', filters={'channel': medium}, pluck='name', limit_page_length=0)


def count(query):
    return int(frappe.qb.from_(query.as_('scoped')).select(Count('*')).run()[0][0])
