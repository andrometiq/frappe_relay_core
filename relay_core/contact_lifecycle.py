"""Keep Relay endpoints in step with the Frappe Contact that owns them."""
import hashlib

import frappe
from relay_core.identity import bindings, contact_identities, normalize
from relay_core.permissions import MANAGER


def relay_contact(person_name):
    return frappe.db.get_value('Relay Contact', {'contact': person_name}, 'name')


def on_update(person, method=None):
    """A number or email removed from the Contact stops routing at once.

    A Relay manager's edit carries the verification to the replacement value."""
    previous = person.get_doc_before_save()
    relay = relay_contact(person.name)
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

    if not set(frappe.get_roles()).intersection({'System Manager', MANAGER}):
        return
    for channel, provider in replaced:
        for value in after[provider] - before[provider]:
            enroll(relay, channel, provider, value)


def enroll(relay, channel, provider, value):
    """Shared values stay with their existing binding; nothing is reassigned."""
    key = hashlib.sha256((channel + ':' + value).encode()).hexdigest()
    with frappe.cache.lock('relay-enroll:' + key, timeout=30):
        if any(bindings(channel, provider, value)):
            return
        set_verified(frappe.get_doc({'doctype': 'Relay Contact Endpoint', 'channel': channel,
                                     'relay_contact': relay, 'endpoint': value}), 1)


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
