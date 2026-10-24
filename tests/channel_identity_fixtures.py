"""Representative local people, businesses and authenticated channel callbacks."""
from site_labels import run_label
import hashlib
import hmac
import json
import time
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from channel_site_fixtures import business, user
from relay_core import inbound
from relay_core.automation import projection
from relay_core.permissions import sequential_name


def scenario():
    stamp = run_label()
    customer = business('Customer ' + stamp)
    supplier = frappe.get_doc({'doctype': 'Supplier', 'supplier_name': 'Sim Supplier ' + stamp,
        'supplier_group': frappe.db.get_value('Supplier Group', {'is_group': 0}, 'name'),
        'supplier_type': 'Company'}).insert()
    for doc in (customer, supplier):
        if not frappe.db.exists('Relay Contact Type', {'business_doctype': doc.doctype, 'enabled': 1}):
            raise AssertionError('Enable the existing business type for local channel validation: ' + doc.doctype)
    person = frappe.get_doc({'doctype': 'Contact', 'first_name': 'Sim Shared Contact ' + stamp,
        'links': [{'link_doctype': doc.doctype, 'link_name': doc.name} for doc in (customer, supplier)]}).insert()
    contact = frappe.get_doc({'doctype': 'Relay Contact', 'contact': person.name,
        'display_name': 'Sim Shared Contact ' + stamp}).insert()
    account = 'c2-' + stamp
    channels = {provider: frappe.get_doc({'doctype': 'Relay Channel', 'channel': provider,
        'account': account, 'enabled': 1}).insert(set_name=sequential_name('channel'))
        for provider in ('WhatsApp', 'Telegram', 'Email')}
    actor = user('relay-c2-reader-' + stamp + '@example.invalid', manager=True)
    frappe.get_doc({'doctype': 'User Permission', 'user': actor, 'allow': 'Customer',
                   'for_value': customer.name, 'apply_to_all_doctypes': 1}).insert()
    allowed_supplier = frappe.copy_doc(supplier)
    allowed_supplier.supplier_name = 'Sim Unrelated Supplier ' + stamp
    allowed_supplier.insert()
    frappe.get_doc({'doctype': 'User Permission', 'user': actor, 'allow': 'Supplier',
                   'for_value': allowed_supplier.name, 'apply_to_all_doctypes': 1}).insert()
    frappe.db.commit()
    return SimpleNamespace(stamp=stamp, customer=customer, supplier=supplier, person=person,
                           contact=contact, account=account, channels=channels, actor=actor)


def configured(fixture):
    from relay_core import email, enrollment, messaging, conversation_start, business_routing_prompt, telegram_delivery, telegram, channel_statuses, whatsapp
    stack = ExitStack()
    for module in (email, enrollment, messaging, conversation_start, business_routing_prompt, telegram_delivery, telegram, channel_statuses, whatsapp):
        stack.enter_context(patch.object(module, 'connection_value', return_value=fixture.account))
    return stack


def endpoint(fixture, provider, value, contact=None):
    return frappe.get_doc({'doctype': 'Relay Contact Endpoint', 'channel': fixture.channels[provider].name,
        'relay_contact': contact or fixture.contact.name, 'endpoint': value, 'verified': 1}).insert()


def incoming(fixture, provider, sender, body, *, raw=None, identifier=None):
    event_id = time.time_ns()
    identifier = identifier or str(event_id)
    if provider == 'WhatsApp':
        payload = {'entry': [{'changes': [{'value': {'messages': [{'id': identifier, 'from': sender,
            'type': 'text', 'timestamp': str(int(time.time())), 'text': {'body': body}}]}}]}]}
    else:
        payload = {'channel': provider, 'direction': 'inbound', 'provider_id': identifier,
                   'sender': sender, 'body': body, 'subject': 'Sim Shared Contact quantity 25', 'payload': raw or {}}
    secret = 'local-c2-callback-fixture-secret-only'
    data = json.dumps({'account': fixture.account, 'events': [{'id': event_id, 'payload': payload}]}).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode() + b'.' + data, hashlib.sha256).hexdigest()
    request = SimpleNamespace(get_data=lambda: data, headers={'X-Relay-Timestamp': timestamp, 'X-Relay-Signature': signature})
    settings = lambda key: {'relay_hub_account': fixture.account, 'relay_callback_secret': secret}.get(key)
    with patch.object(inbound, 'connection_value', side_effect=settings), patch.object(frappe, 'request', request):
        assert inbound.receive()['accepted'] == 1
        assert inbound.receive()['accepted'] == 1
    frappe.db.commit()
    event = frappe.get_doc('Relay Hub Event', {'account': fixture.account, 'hub_event_id': str(event_id)})
    projection.project(event.name)
    frappe.db.commit()
    event.reload()
    return event, identifier


def telegram_raw(chat, message_id, body, *, topic=None, reply=None, participant=None):
    message = {'chat': {'id': chat, 'type': 'private' if chat > 0 else 'supergroup'},
               'from': {'id': participant or abs(chat), 'is_bot': False},
               'message_id': message_id, 'text': body, 'date': int(time.time())}
    if topic: message['message_thread_id'] = topic
    if reply: message['reply_to_message'] = {'message_id': reply}
    return {'update_id': message_id, 'message': message}


def email_raw(message_id, *, parent=None, refs=None, to=None, cc=None, authenticated=True):
    return {'message_id': message_id, 'in_reply_to': parent, 'references': refs or [],
            'to': to or ['local-inbox@example.invalid'], 'cc': cc or [],
            'authentication': {'status': 'pass' if authenticated else 'unverified'}, 'auto_submitted': False}


def fails(call, exceptions=(frappe.PermissionError, frappe.ValidationError, ValueError)):
    try:
        call()
    except exceptions:
        frappe.db.rollback()
    else:
        raise AssertionError('Unauthorized or invalid operation succeeded')


def cleanup(fixture):
    """Disable only this scenario's local configuration; retain its evidence."""
    frappe.db.rollback()
    frappe.set_user('Administrator')
    channels = [channel.name for channel in fixture.channels.values()]
    for doctype in ('Relay AI Skill', 'Relay Flow', 'Relay Email Rule', 'Relay Business Event Rule'):
        for name in frappe.get_all(doctype, filters={'channel': ['in', channels]}, pluck='name'):
            values = {'enabled': 0}
            if doctype == 'Relay AI Skill':
                values['active_key'] = None
            frappe.db.set_value(doctype, name, values)
    for name in frappe.get_all('Relay Message', filters={'channel':['in',channels], 'automation_status':'Pending'}, pluck='name'):
        frappe.db.set_value('Relay Message', name, 'automation_status', 'Complete', update_modified=False)
    for channel in channels:
        frappe.db.set_value('Relay Channel', channel, 'enabled', 0)
    frappe.db.commit()
