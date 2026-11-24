"""Conversation threads: one per contact endpoint on one business channel, such as one WhatsApp number of a person
on one of our WhatsApp numbers. A record or a chat shows each thread on its own, and a reply stays on its thread."""
import frappe

from relay_core import relay_chats
from relay_core.api import validate_reference
from relay_core.permissions import readable_contact, require_access

MAX_THREADS = 100
PROVIDERS = ('WhatsApp', 'Telegram', 'Email')
LAST_FIELDS = ['name', 'direction', 'sent_at', 'creation', 'content', 'message_data', 'transcript', 'business_doctype',
               'business_name', 'channel', 'relay_contact']


@frappe.whitelist(methods=['GET'])
def threads(contact=None, doctype=None, name=None):
    """The threads of one chat (`contact`) or one business record (`doctype`, `name`), each with its last message,
    its unread count and its first unread message. Threads on channels the user cannot read are left out."""
    require_access()
    if bool(contact) == bool(doctype or name):
        frappe.throw('Choose one chat or one business record')
    message = frappe.qb.DocType('Relay Message')
    if contact:
        validate_reference(contact, 'CON')
        readable_contact(contact)
        scope = message.relay_contact == contact
        unread = relay_chats.unread_by_thread('m.relay_contact=%(contact)s AND COALESCE(m.legacy_triage, 0)=0', {'contact': contact})
    else:
        from relay_core.business_access import business_document
        from relay_core.business_inbox import check_type, timeline_scope
        check_type(doctype)
        business_document(doctype, name)
        linked, scope = timeline_scope(doctype, name)
        scope = scope & message.relay_contact.isin(linked)
        unread = relay_chats.thread_unread((doctype, name))
    return {'items': thread_items(newest_by_thread(scope), unread)}


def newest_by_thread(scope):
    """{(relay_contact, channel, endpoint): newest message name} under the Relay Message permission query."""
    from pypika.functions import Max
    readable = frappe.qb.get_query('Relay Message', fields=['name', 'relay_contact', 'channel', 'sender_endpoint'], filters={},
                                   ignore_permissions=False, order_by='').where(scope).as_('readable')
    rows = (frappe.qb.from_(readable).select(readable.relay_contact, readable.channel, readable.sender_endpoint, Max(readable.name))
            .groupby(readable.relay_contact, readable.channel, readable.sender_endpoint).limit(MAX_THREADS).run())
    return {(contact, channel, endpoint or ''): newest for contact, channel, endpoint, newest in rows}


def thread_items(newest, unread):
    """Thread rows sorted WhatsApp, Telegram, Email, then by our channel and the contact endpoint.

    `unread` maps a thread to (unread count, first unread, newest unread), as relay_chats.unread_threads counts them."""
    channels = {row.name: row for row in frappe.get_list('Relay Channel', fields=['name', 'channel', 'label', 'title', 'address'],
                                                          limit_page_length=0)}
    last = {row.name: row for row in frappe.get_all('Relay Message', filters={'name': ['in', list(newest.values())]},
                                                     fields=LAST_FIELDS)} if newest else {}
    people, items = {}, []
    for thread, name in newest.items():
        person, channel, endpoint = thread
        if channel not in channels:
            continue
        if person not in people:
            people[person] = readable_person(person)
        if people[person] is None:
            continue
        items.append(thread_item(thread, last[name], channels[channel], people[person], unread.get(thread, (0, None, None))))
    from relay_core.endpoint_labels import contact_titles, telegram_labels
    renamed = contact_titles({item['relay_contact']: item['contact_label'] for item in items})
    for item in items:
        item['contact_label'] = renamed.get(item['relay_contact']) or item['contact_label']
    telegram = [item for item in items if item['provider'] == 'Telegram']
    labels = telegram_labels([(item['channel'], item['endpoint']) for item in telegram],
                             {(item['channel'], item['endpoint']): item['handle'] for item in telegram if item['handle']})
    for item in telegram:
        item['endpoint_label'] = labels.get((item['channel'], item['endpoint'])) or 'Telegram'
    return sorted(items, key=lambda item: (provider_rank(item['provider']), item['channel_label'], item['endpoint'], item['contact_label']))


def readable_person(contact):
    try:
        relay, person = readable_contact(contact)
    except frappe.PermissionError:
        return None
    return {'label': relay.display_name or person.full_name or relay.name, 'frappe_contact': relay.contact or ''}


def thread_item(thread, last, channel, person, unread):
    from relay_core.inbox import directory_preview
    contact, channel_name, endpoint = thread
    return {'key': '|'.join(thread), 'relay_contact': contact, 'contact_label': person['label'], 'frappe_contact': person['frappe_contact'],
            'channel': channel_name, 'provider': channel.channel, 'channel_label': channel.label or channel.title or channel_name,
            'channel_address': channel.address or '', 'endpoint': endpoint, 'last_message': last.name,
            'last_at': last.sent_at or last.creation, 'last_direction': last.direction, 'preview': directory_preview(last),
            'unread': unread[0], 'first_unread': unread[1], 'handle': telegram_handle(thread) if channel.channel == 'Telegram' else ''}


def telegram_handle(thread):
    """The person's public Telegram handle from their newest message on the thread, when Telegram sent one."""
    from relay_core.automation.provenance import context_of
    contact, channel, endpoint = thread
    context = frappe.db.get_value('Relay Message', {'relay_contact': contact, 'channel': channel, 'sender_endpoint': endpoint,
                                                    'direction': 'Incoming'}, 'provider_context', order_by='name desc')
    username = context_of({'provider_context': context}).get('username') if context else None
    return '@' + username if isinstance(username, str) and username else ''


def provider_rank(provider):
    return PROVIDERS.index(provider) if provider in PROVIDERS else len(PROVIDERS)
