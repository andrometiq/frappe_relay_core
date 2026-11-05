"""One-time Telegram deep links that let a person save their own verified Telegram chat.

A link is https://t.me/<bot>?start=<code>. Core keeps only the SHA-256 of the code, for CODE_SECONDS,
and the first `/start <code>` the bot receives in a private chat spends it."""
import hashlib
import re
import secrets
import time

import frappe
from relay_core.permissions import readable_contact, require_access
from relay_core.settings import value as connection_value

CODE_SECONDS = 15 * 60
CACHE = 'relay-telegram-link:'
START = re.compile(r'/start ([A-Za-z0-9_-]{32})')
USERNAME = re.compile(r'[A-Za-z0-9_]{5,64}')


@frappe.whitelist(methods=['POST'])
def link_me(channel=None):
    """A link that saves the signed-in user's Telegram chat for ticket notifications."""
    require_access()
    return new_link(own_contact(), channel)


@frappe.whitelist(methods=['POST'])
def link_contact(contact, channel=None):
    """A link a manager sends to a contact; it saves the contact's Telegram chat."""
    require_access(manage=True)
    readable_contact(contact)
    return new_link(contact, channel)


def own_contact():
    """The Relay Contact of the Frappe Contact that belongs to the session user, made on first use."""
    from relay_core.contacts import ensure_relay
    user = frappe.session.user
    with frappe.cache.lock('relay-own-contact:' + user, timeout=30):
        name = frappe.db.get_value('Contact', {'user': user}, 'name', order_by='creation asc')
        if name:
            return ensure_relay(frappe.get_doc('Contact', name))
        email = frappe.db.get_value('User', user, 'email')
        person = frappe.get_doc({'doctype': 'Contact', 'first_name': frappe.utils.get_fullname(user), 'user': user,
                                 'email_ids': [{'email_id': email, 'is_primary': 1}] if email else []})
        return ensure_relay(person.insert(ignore_permissions=True))


def new_link(contact, channel=None):
    from relay_core.channel_setup import fail, hub_call, relay_channel
    from relay_core.channel_setup.telegram import health_of
    from relay_core.hub_channels import choose
    bot = relay_channel(choose('Telegram', None, contact, channel), 'Telegram')
    username = health_of(hub_call('telegram.bot.health', {'channel': bot.hub_channel})).get('username')
    if not isinstance(username, str) or not USERNAME.fullmatch(username.lstrip('@')):
        fail('telegram_unavailable')
    code = secrets.token_urlsafe(24)
    frappe.cache.set_value(CACHE + digest(code), {
        'contact': contact, 'channel': bot.name, 'account': connection_value('relay_hub_account'),
        'user': frappe.session.user, 'expires': time.time() + CODE_SECONDS}, expires_in_sec=CODE_SECONDS)
    return {'url': f'https://t.me/{username.lstrip("@")}?start={code}', 'bot': bot.label or bot.title or bot.name,
            'expires_in': CODE_SECONDS}


def digest(code):
    return hashlib.sha256(code.encode()).hexdigest()


def start_code(row, context):
    """The code of a `/start <code>` text the participant sent in a private chat with the bot, or None."""
    found = START.fullmatch(((row.get('text') or {}).get('body') or '').strip()) if row.get('type') == 'text' else None
    private = (context.get('chat_type') == 'private' and not context.get('sender_chat_id')
               and str(context.get('participant_id')) == row['from'])
    return found.group(1) if found and private else None


def redeem(channel, row, context):
    """Spend a `/start <code>` and save the sender's chat as a verified endpoint of the link's contact.

    The code is spent on first use, also when it does not fit. An existing binding of the chat is never replaced.
    The chat display keeps only `/start`. Returns the linked Relay Contact, or None."""
    code = start_code(row, context)
    if not code:
        return None
    row['text'] = {'body': '/start'}
    row['message_data'] = {'kind': 'text', 'text': '/start'}
    key = CACHE + digest(code)
    with frappe.cache.lock('relay-telegram-link-redeem:' + digest(code), timeout=10):
        link = frappe.cache.get_value(key, expires=True)
        frappe.cache.delete_value(key)
    account = connection_value('relay_hub_account')
    if (not isinstance(link, dict) or link['expires'] < time.time() or link['channel'] != channel
            or link['account'] != account or frappe.db.get_value('Relay Channel', channel, 'account') != account):
        return None
    from relay_core.contact_lifecycle import enroll
    linked = enroll(link['contact'], channel, 'Telegram', row['from']) is not None
    frappe.publish_realtime('relay_changed', {'kind': 'telegram_link', 'linked': int(linked)}, user=link['user'], after_commit=True)
    if not linked:
        return None
    from relay_core.realtime import contact_changed
    contact_changed(link['contact'], 'contacts')
    return link['contact']
