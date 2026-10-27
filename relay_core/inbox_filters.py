"""Inbox filters that the conversation list and its counts share: channels and business record."""
import json

import frappe

MEDIUMS = (None, '', 'WhatsApp', 'Telegram', 'Email')
NO_RECORD = 'none'
MAX_CHANNELS = 50


def channel_names(medium=None, channel=None, channels=None):
    """The Relay Channels a list or count covers, or None for every channel.

    `channels` (a list, or a JSON list from a GET request) keeps only those channels; `channel` is the one-channel form."""
    if medium not in MEDIUMS:
        frappe.throw('Invalid medium')
    chosen = parse_channels(channels) + ([channel] if channel else [])
    if not medium and not chosen:
        return None
    filters = {'channel': medium} if medium else {'name': ['in', chosen]}
    # Literal names, not a subquery: nested semi-joins made MariaDB copy every unread row into a weedout table.
    available = frappe.get_list('Relay Channel', filters=filters, pluck='name', limit_page_length=0)
    if any(name not in available for name in chosen):
        frappe.throw('Invalid channel')
    return [name for name in available if name in chosen] if chosen else available


def parse_channels(value):
    if value in (None, '', '[]'):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            frappe.throw('Invalid channel filter')
    if not isinstance(value, list) or len(value) > MAX_CHANNELS or not all(map(valid_name, value)):
        frappe.throw('Invalid channel filter')
    return list(dict.fromkeys(value))


def valid_name(value):
    return isinstance(value, str) and 0 < len(value) <= 140 and not any(ord(c) < 32 for c in value)


def channel_contacts(names):
    endpoints = frappe.qb.DocType('Relay Contact Endpoint')
    return frappe.qb.from_(endpoints).select(endpoints.relay_contact).where(endpoints.channel.isin(names))


def business_filter(business_type=None, business_name=None):
    """A Relay Contact condition for one business type or record, or for chats with no record (`none`).

    A chat belongs to the records that its Frappe Contact links to, as in business_access.candidates."""
    if business_name and (not business_type or business_type == NO_RECORD):
        frappe.throw('Choose a business type for the record')
    if not business_type:
        return None
    if business_name and not valid_name(business_name):
        frappe.throw('Invalid business record')
    contact = frappe.qb.DocType('Relay Contact')
    links = frappe.qb.DocType('Dynamic Link')
    linked = frappe.qb.from_(links).select(links.parent).where(links.parenttype == 'Contact').where(links.parent.notnull())
    if business_type == NO_RECORD:
        enabled = frappe.get_all('Relay Contact Type', filters={'enabled': 1}, pluck='business_doctype', limit_page_length=0)
        if not enabled:
            return None
        return contact.contact.isnull() | contact.contact.notin(linked.where(links.link_doctype.isin(enabled)))
    from relay_core.api import business_types
    if business_type not in business_types():
        frappe.throw('Invalid business type')
    linked = linked.where(links.link_doctype == business_type)
    if business_name:
        linked = linked.where(links.link_name == business_name)
    return contact.contact.isin(linked)
