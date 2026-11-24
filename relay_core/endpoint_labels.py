"""What a person sees for a Telegram chat. A Telegram chat id means nothing to them, so a Telegram chat shows the mobile
number linked to its contact, else its @username, else the person's name, else "Telegram". Callers check access first."""
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
    return {pair: mobiles.get(owners.get(pair)) or handles.get(pair) or person_name(people.get(owners.get(pair)), pair[1]) or 'Telegram'
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
            number = ''.join(character for character in row.endpoint or '' if character.isdigit())
            if number and row.relay_contact not in mobiles:
                mobiles[row.relay_contact] = '+' + number
    linked = {person.contact: name for name, person in people.items() if person.contact and name not in mobiles}
    if linked:
        for row in frappe.get_all('Contact', filters={'name': ['in', list(linked)]}, fields=['name', 'mobile_no', 'phone']):
            if row.mobile_no or row.phone:
                mobiles[linked[row.name]] = row.mobile_no or row.phone
    return mobiles


def person_name(person, chat_id):
    """The person's saved name, unless it is only the chat id or another number."""
    name = (person or {}).get('display_name') or ''
    return '' if not name or name == chat_id or name.lstrip('+').replace(' ', '').isdigit() else name
