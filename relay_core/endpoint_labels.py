"""What a person sees for a Telegram chat. A Telegram chat id means nothing to them, so a Telegram chat shows the mobile
number linked to its contact, else its @username, else the person's name; with none of these the caller shows only the
word Telegram. Callers check access first."""
import frappe


def telegram_labels(pairs, handles=None):
    """{(channel, chat id): label} for Telegram chats, in the same few batched reads whatever the number of chats."""
    pairs = {(channel, endpoint) for channel, endpoint in pairs if channel and endpoint}
    if not pairs:
        return {}
    from relay_core.contact_lifecycle import endpoint_key
    # endpoint_key is the endpoint's unique index, so the lookup stays an index read on a large table.
    rows = frappe.get_all('Relay Contact Endpoint', fields=['channel', 'endpoint', 'relay_contact'], limit_page_length=0,
                          filters={'endpoint_key': ['in', sorted(endpoint_key(channel, endpoint) for channel, endpoint in pairs)]})
    owners = {(row.channel, row.endpoint): row.relay_contact for row in rows if (row.channel, row.endpoint) in pairs}
    contacts = sorted(set(owners.values()))
    people = {row.name: row for row in frappe.get_all('Relay Contact', filters={'name': ['in', contacts]},
                                                      fields=['name', 'contact', 'display_name'])} if contacts else {}
    mobiles = linked_mobiles(people)
    handles = handles or {}
    return {pair: mobiles.get(owners.get(pair)) or handles.get(pair) or person_name(people.get(owners.get(pair)), pair[1]) or ''
            for pair in pairs}


def linked_mobiles(people):
    """{relay contact: mobile}: the person's WhatsApp number, else the mobile or phone of their Frappe Contact."""
    if not people:
        return {}
    mobiles = {}
    whatsapp = frappe.get_all('Relay Channel', filters={'channel': 'WhatsApp'}, pluck='name')
    if whatsapp:
        for row in frappe.get_all('Relay Contact Endpoint', fields=['relay_contact', 'endpoint'], order_by='verified desc, modified desc',
                                  filters={'relay_contact': ['in', list(people)], 'channel': ['in', whatsapp]}, limit_page_length=0):
            number = display_phone('+' + (row.endpoint or '').lstrip('+'))
            if number and row.relay_contact not in mobiles:
                mobiles[row.relay_contact] = number
    linked = {person.contact: name for name, person in people.items() if person.contact and name not in mobiles}
    if linked:
        for row in frappe.get_all('Contact', filters={'name': ['in', list(linked)]}, fields=['name', 'mobile_no', 'phone']):
            if row.mobile_no or row.phone:
                mobiles[linked[row.name]] = display_phone(row.mobile_no or row.phone)
    return mobiles


def display_phone(value):
    """A phone number as the app shows it everywhere (phoneNumber.js phoneCaption): +91 98765 43210; other text unchanged."""
    text = str(value or '').strip()
    digits = ''.join(character for character in text if character.isdigit())
    if not digits or len(digits) < 7 or len(digits) > 15 or any(character not in '+0123456789 ()-' for character in text):
        return text
    if len(digits) == 12 and digits.startswith('91'):
        return f'+91 {digits[2:7]} {digits[7:]}'
    if len(digits) == 10 and not text.startswith('+'):
        return f'{digits[:5]} {digits[5:]}'
    return '+' + digits


def contact_titles(names):
    """{relay contact: title} for contacts saved under no name or only their numeric Telegram chat id, as unlinked Telegram
    senders are: their linked mobile, else their @username, else "Telegram user". `names` maps a relay contact to its saved
    name; other contacts keep theirs. A few batched reads whatever the number of contacts."""
    candidates = [contact for contact, name in names.items() if contact and (not name or is_number(name))]
    if not candidates:
        return {}
    telegram = frappe.get_all('Relay Channel', filters={'channel': 'Telegram'}, pluck='name')
    if not telegram:
        return {}
    chats = {}
    for row in frappe.get_all('Relay Contact Endpoint', filters={'relay_contact': ['in', candidates], 'channel': ['in', telegram]},
                              fields=['relay_contact', 'channel', 'endpoint'], limit_page_length=0):
        chats.setdefault(row.relay_contact, []).append((row.channel, row.endpoint))
    chat_named = [contact for contact, pairs in chats.items() if not names[contact] or names[contact] in {endpoint for _, endpoint in pairs}]
    if not chat_named:
        return {}
    people = {row.name: row for row in frappe.get_all('Relay Contact', filters={'name': ['in', chat_named]}, fields=['name', 'contact', 'display_name'])}
    mobiles = linked_mobiles(people)
    newest = telegram_usernames([contact for contact in chat_named if contact not in mobiles], telegram)
    usernames = {}
    for (contact, _, _), (name, username) in sorted(newest.items(), key=lambda item: item[1][0]):
        if username:
            usernames[contact] = username
    return {contact: mobiles.get(contact) or usernames.get(contact) or 'Telegram user' for contact in chat_named}


def telegram_usernames(contacts, channels):
    """{(relay contact, channel, chat id): (newest incoming message, '@username' or '')} in two reads: the newest incoming
    message of each Telegram chat, and the username Telegram sent with it."""
    if not contacts or not channels:
        return {}
    from pypika.functions import Max
    from relay_core.automation.provenance import context_of
    message = frappe.qb.DocType('Relay Message')
    rows = (frappe.qb.from_(message).select(message.relay_contact, message.channel, message.sender_endpoint, Max(message.name))
            .where(message.relay_contact.isin(list(contacts))).where(message.channel.isin(list(channels)))
            .where(message.direction == 'Incoming').groupby(message.relay_contact, message.channel, message.sender_endpoint).run())
    contexts = dict(frappe.get_all('Relay Message', filters={'name': ['in', [row[3] for row in rows]]}, fields=['name', 'provider_context'],
                                   as_list=True)) if rows else {}
    result = {}
    for contact, channel, endpoint, newest in rows:
        username = context_of({'provider_context': contexts.get(newest)}).get('username') if contexts.get(newest) else None
        result[(contact, channel, endpoint or '')] = (newest, '@' + username if isinstance(username, str) and username else '')
    return result


def is_number(value):
    return str(value).strip().lstrip('+-').replace(' ', '').isdigit()


def person_name(person, chat_id):
    """The person's saved name, unless it is only the chat id or another number."""
    name = (person or {}).get('display_name') or ''
    return '' if not name or name == chat_id or is_number(name) else name
