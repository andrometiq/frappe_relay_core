"""Keep Relay endpoints in step with the Frappe Contact that owns them."""
import hashlib
from contextlib import nullcontext

import frappe
from relay_core.identity import bindings, contact_identities, normalize
from relay_core.permissions import can_manage


def relay_contact(person_name):
    return frappe.db.get_value('Relay Contact', {'contact': person_name}, 'name')


def on_update(person, method=None):
    """A number or email removed from the Contact stops routing at once, and a removed
    primary business link is cleared.

    A Relay manager's edit carries the verification to the replacement value."""
    previous = person.get_doc_before_save()
    relay = relay_contact(person.name)
    if relay:
        from relay_core.business_access import drop_stale_primary
        drop_stale_primary(relay)
        associate_unlinked_messages(relay)
        from relay_core.realtime import contact_changed
        contact_changed(relay, 'contacts')
    if not previous or not relay:
        return
    before, after = contact_identities(previous), contact_identities(person)
    removed = {provider: before[provider] - after[provider] for provider in before}
    if not any(removed.values()):
        return

    replaced = set()
    for row in frappe.get_all('Relay Contact Endpoint', filters={'relay_contact': relay, 'verified': 1},
                              fields=['name', 'channel', 'endpoint']):
        provider = frappe.db.get_value('Relay Channel', row.channel, 'channel')
        try:
            value = normalize(provider, row.endpoint)
        except ValueError:
            continue
        if value in removed.get(provider, ()):
            set_verified(frappe.get_doc('Relay Contact Endpoint', row.name), 0)
            replaced.add((row.channel, provider))

    if not can_manage():
        return
    for channel, provider in replaced:
        for value in after[provider] - before[provider]:
            enroll(relay, channel, provider, value)


def enroll(relay, channel, provider, value, *, locked=False):
    """Shared or revoked values stay with their existing binding; nothing is reassigned."""
    with nullcontext() if locked else frappe.cache.lock('relay-enroll:' + endpoint_key(channel, value), timeout=30):
        existing = list(bindings(channel, provider, value))
        if existing:
            if len(existing) == 1 and existing[0].relay_contact == relay and existing[0].verified:
                return existing[0]
            return None
        endpoint = frappe.get_doc({'doctype': 'Relay Contact Endpoint', 'channel': channel,
                                   'relay_contact': relay, 'endpoint': value})
        set_verified(endpoint, 1)
        return endpoint


def whatsapp_contact(channel, number, profile_name=None, *, locked=False):
    """Enroll an authenticated private number, without overriding revoked or ambiguous bindings."""
    from relay_core.identity import contacts_by_phone, phone_number
    from relay_core.contacts import ensure_relay, new_person
    if not number.isdigit() or phone_number('+' + number) != number:
        return None
    # Serialize first messages across channels before finding/creating the Frappe Contact.
    with nullcontext() if locked else frappe.cache.lock('relay-whatsapp-person:' + number, timeout=30):
        with frappe.cache.lock('relay-enroll:' + endpoint_key(channel, number), timeout=30):
            existing = list(bindings(channel, 'WhatsApp', number))
            if existing:
                return existing[0].relay_contact if len(existing) == 1 and existing[0].verified else None
            provider, account = frappe.db.get_value('Relay Channel', channel, ['channel', 'account'])
            siblings = frappe.get_all('Relay Channel', pluck='name', filters={'channel': provider, 'account': account})
            keys = [endpoint_key(name, number) for name in siblings]
            owners = set(frappe.get_all('Relay Contact Endpoint', pluck='relay_contact',
                filters={'endpoint_key': ['in', keys], 'verified': 1}))
            if owners:  # Siblings must resolve through sibling_contact; ambiguous identities stay in triage.
                return None
            matches = contacts_by_phone(number).get(number, [])
            if len(matches) == 1:
                person = frappe.get_doc('Contact', matches[0])
            else:
                label = ''.join(c for c in (profile_name or '') if ord(c) >= 32).strip()[:140] or number
                person = new_person(label, number, ignore_permissions=True)
            relay = ensure_relay(person)
            return relay if enroll(relay, channel, 'WhatsApp', number, locked=True) else None


def associate_unlinked_messages(relay):
    """A sole business link owns live history; imported and already owned history stays intact."""
    from relay_core.business_access import candidates
    frappe.db.get_value('Relay Contact', relay, 'name', for_update=True)
    links = candidates(relay)
    if len(links) != 1:
        return
    frappe.db.sql("""UPDATE `tabRelay Message` SET business_doctype=%s, business_name=%s
        WHERE relay_contact=%s AND COALESCE(business_doctype, '')='' AND COALESCE(business_name, '')=''
        AND COALESCE(legacy_source, '')='' AND COALESCE(legacy_triage, 0)=0""", (*links[0], relay))
    from relay_core.relay_chats import merge
    merge(relay, links[0])


def sibling_contact(channel: str, endpoint: str) -> str | None:
    """The Relay Contact of a first private message on another business number, bot or mailbox of this site.

    The same WhatsApp number, Telegram user or email address with a verified endpoint on another channel of
    the same type is the same person, so this channel gets a verified endpoint for that contact. Groups,
    revoked bindings and identities shared by two contacts stay in triage."""
    provider, account = frappe.db.get_value('Relay Channel', channel, ['channel', 'account'])
    try:
        value = normalize(provider, endpoint)
    except ValueError:
        return None
    if provider != 'Email' and not value.isdigit():
        return None
    siblings = frappe.get_all('Relay Channel', pluck='name',
                              filters={'channel': provider, 'account': account, 'name': ['!=', channel]})
    keys = [endpoint_key(name, value) for name in siblings]
    contacts = set(frappe.get_all('Relay Contact Endpoint', pluck='relay_contact',
                                  filters={'endpoint_key': ['in', keys], 'verified': 1})) if keys else set()
    if len(contacts) != 1:
        return None
    enroll(contacts.pop(), channel, provider, value)
    return frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': endpoint_key(channel, value), 'verified': 1},
                               'relay_contact')


def endpoint_key(channel, value):
    return hashlib.sha256((channel + ':' + value).encode()).hexdigest()


def set_verified(endpoint, verified):
    previous = getattr(frappe.flags, 'relay_contact_sync', False)
    frappe.flags.relay_contact_sync = True
    try:
        endpoint.verified = verified
        endpoint.save(ignore_permissions=True)
    finally:
        frappe.flags.relay_contact_sync = previous


def on_trash(person, method=None):
    if relay_contact(person.name):
        frappe.throw(f'Contact {frappe.bold(person.name)} has Relay conversations. '
                     'Remove its numbers or business links instead, or merge it into another Contact.',
                     frappe.LinkExistsError)


def before_rename(person, method=None, old=None, new=None, merge=False):
    if merge and relay_contact(old) and relay_contact(new):
        frappe.throw('Both Contacts have Relay conversations, so they cannot be merged.')


def after_rename(person, method=None, old=None, new=None, merge=False):
    """Channel preference keys include the Contact name."""
    from relay_core.channel_preferences import scope_key
    for row in frappe.get_all('Relay Channel Preference', filters={'contact': new},
                              fields=['name', 'business_doctype', 'business_name', 'endpoint']):
        scope = scope_key(new, row.business_doctype, row.business_name)
        frappe.db.set_value('Relay Channel Preference', row.name, {
            'scope_key': scope, 'preference_key': hashlib.sha256((scope + ':' + row.endpoint).encode()).hexdigest()},
            update_modified=False)
