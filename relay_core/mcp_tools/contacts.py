"""Contact search, profile and business links."""
from relay_core.mcp_tools.inbox import CONTACT
from relay_core.mcp_tools.registry import CURSOR, NAME_FIELD, READ, WRITE, obj, tool
from relay_core.mcp_tools.send import CHANNEL, NUMBER

LINKS = {'type': 'array', 'maxItems': 50, 'items': obj({'doctype': NAME_FIELD, 'name': NAME_FIELD}, ('doctype', 'name'))}


@tool('contacts_search', READ, obj({'query': {'type': 'string', 'maxLength': 80}, 'business_type': NAME_FIELD,
                                    'business_name': NAME_FIELD, 'after': CURSOR}), {
    'summary': 'Find Frappe Contacts by name, mobile or email, 30 per page; optionally only those linked to a business record.',
    'use_when': 'you need a person to start a chat with, or their Frappe Contact name.',
    'avoid_when': 'you look for an existing chat; use inbox_list with query.',
    'returns': '{items: [{name (Frappe Contact), full_name, mobile_no}], next: cursor for after or null}.',
    'errors': '"Business type is not accessible"; "Choose a business type first" when only business_name is given.'})
def contacts_search(query='', business_type=None, business_name=None, after=None):
    from relay_core.api import contact_directory
    return contact_directory(query, after=after, business_type=business_type, business_name=business_name)


@tool('contacts_read', READ, obj({'contact': CONTACT}, ('contact',)), {
    'summary': 'Read the profile of one chat contact: name, phone, email, primary business record and link count.',
    'use_when': 'you need who a chat belongs to before answering.',
    'avoid_when': 'you only have a Frappe Contact name; use contacts_search.',
    'returns': '{name, display_name, contact (Frappe Contact), primary, link_count, phone, email}.',
    'errors': '"Not found" or "Not permitted" for a contact outside the user\'s scope.'})
def contacts_read(contact):
    from relay_core.api import contact_profile
    return contact_profile(contact)


@tool('contacts_create', WRITE, obj({'name': {'type': 'string', 'minLength': 1, 'maxLength': 140}, 'phone': NUMBER,
                                     'channel': CHANNEL, 'links': LINKS}, ('name', 'phone', 'channel')), {
    'summary': 'Create a contact with a WhatsApp number on one channel. Communication managers only. Sends nothing.',
    'use_when': 'the user wants to add a new person before sending a template.',
    'avoid_when': 'the number may already exist; check contacts_search first.',
    'returns': '{contact (Frappe Contact), relay_contact (RELAY-CON-...), endpoint}.',
    'errors': '"Already exists: This number already belongs to a contact"; "Enter a valid phone number"; "Not permitted" for non-managers.'})
def contacts_create(name, phone, channel, links=None):
    from relay_core.contacts import create
    return create(name, phone, channel, links=links)


@tool('contacts_set_links', WRITE, obj({'contact': NAME_FIELD, 'links': LINKS}, ('contact', 'links')), {
    'summary': 'Replace the business records a Frappe Contact is linked to. Links the user cannot read stay as they are.',
    'use_when': 'the user says a person belongs to a customer or another record.',
    'avoid_when': 'you only want to mark which link is primary; use contacts_set_primary.',
    'returns': 'the contact summary with its links.',
    'errors': '"Choose a configured business type"; "Not permitted" without write access to the Contact.'})
def contacts_set_links(contact, links):
    from relay_core.contacts import set_links
    return set_links(contact, links)


@tool('contacts_set_primary', WRITE, obj({'contact': NAME_FIELD, 'doctype': NAME_FIELD, 'name': NAME_FIELD}, ('contact',)), {
    'summary': 'Mark one linked business record of a Frappe Contact as primary; no record clears the mark.',
    'use_when': 'a person is linked to several records and their chat should route to one.',
    'avoid_when': 'the record is not linked yet; use contacts_set_links first.',
    'returns': 'the contact summary.',
    'errors': '"This contact has no Relay conversation"; "Not permitted".'})
def contacts_set_primary(contact, doctype=None, name=None):
    from relay_core.contacts import set_primary
    return set_primary(contact, doctype, name)
