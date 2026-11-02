"""The setup test message: Meta's hello_world template to the admin's phone. A new site has no business
records yet, so it starts an unlinked chat, as a first incoming message does."""
import hashlib
import time

import frappe
from relay_core.settings import value as connection_value

TEMPLATE = {'name': 'hello_world', 'language': 'en_US', 'components': []}
REPEAT_SECONDS = 600


def send(channel, to):
    from relay_core.contact_lifecycle import endpoint_key
    from relay_core.conversation_start import send as send_start
    from relay_core.messaging_api import destination_number
    from relay_core.onboarding.coexistence import contact_for
    number = destination_number(to)
    if not isinstance(channel, str) or not frappe.db.exists('Relay Channel', {
            'name': channel, 'channel': 'WhatsApp', 'enabled': 1, 'account': connection_value('relay_hub_account')}):
        frappe.throw('Choose a connected WhatsApp number')
    contact = contact_for(channel, number)
    endpoint = contact and frappe.db.get_value('Relay Contact Endpoint', {
        'endpoint_key': endpoint_key(channel, number), 'verified': 1, 'relay_contact': contact}, 'name')
    if not endpoint:
        frappe.throw('This number is saved on more than one contact. Send the test to another number.')
    # A double click stays one message; the same test later is a new one.
    bucket = int(time.time() // REPEAT_SECONDS)
    key = 'setup-test-' + hashlib.sha256(f'{channel}:{number}:{bucket}'.encode()).hexdigest()[:40]
    return send_start(contact, endpoint, 'template', dict(TEMPLATE), key)
