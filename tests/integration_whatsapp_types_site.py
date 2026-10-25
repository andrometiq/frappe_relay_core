"""Every WhatsApp inbound type, reaction, edit, failed receipt and voice transcript on yrp.site.

Needs Relay Message and Relay Settings reloaded first. Run with
PYTHONPATH=<worktree>:<worktree>/tests CI=1 ../env/bin/python -B tests/integration_whatsapp_types_site.py
from the bench sites folder. No Hub, Meta or speech provider is called; fixtures are deleted.
"""
import json
import secrets
import threading
import time
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler

import frappe
import frappe.app
import requests

frappe.init(site='yrp.site', sites_path='.')
frappe.connect(); frappe.set_user('Administrator'); frappe.flags.mute_emails = True
assert frappe.conf.developer_mode
columns = set(frappe.db.get_table_columns('Relay Message'))
assert {'transcript', 'transcript_status', 'transcript_details', 'delivery_error'} <= columns, 'Reload Relay Message first'

from relay_core import api, message_derivatives, voice_transcripts
from relay_core.automation import projection, multimodal
from relay_core.inbound import callback_write

label = 'WhatsApp types ' + secrets.token_hex(3)
account = 'wa-types-' + secrets.token_hex(4)
phone = '919999955501'
created = []


def insert(doctype, **values):
    doc = frappe.get_doc(dict(doctype=doctype, **values)).insert(ignore_permissions=True)
    created.append(doc); return doc


def deliver(*messages, statuses=()):
    value = {'messaging_product': 'whatsapp', 'metadata': {'phone_number_id': 'fixture'}, 'messages': list(messages)}
    if statuses:
        value = {'messaging_product': 'whatsapp', 'metadata': {'phone_number_id': 'fixture'}, 'statuses': list(statuses)}
    payload = {'object': 'whatsapp_business_account', 'entry': [{'id': 'fixture', 'changes': [{'field': 'messages', 'value': value}]}]}
    event = frappe.get_doc({'doctype': 'Relay Hub Event', 'event_key': secrets.token_hex(16), 'account': account,
        'hub_event_id': secrets.token_hex(4), 'payload': json.dumps(payload), 'projection_status': 'Pending'})
    event.flags.relay_inline_projection = True
    token = callback_write.set(True)  # The signed Hub callback is not under test here.
    try:
        event.insert(ignore_permissions=True); created.append(event)
    finally:
        callback_write.reset(token)
    return frappe.db.get_value('Relay Hub Event', event.name, 'projection_status')


def message(provider_id):
    return frappe.get_doc('Relay Message', {'provider_id': provider_id})


def wamid(name):
    return 'wamid.types.' + account + '.' + name


class Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def application(environ, start_response):
    environ['HTTP_X_FRAPPE_SITE_NAME'] = 'yrp.site'
    return frappe.app.application(environ, start_response)


base = frappe.get_doc('Relay Contact', {'display_name': ['like', 'Local simulation%'], 'automation_paused': 1})
links = [dict(link_doctype=row.link_doctype, link_name=row.link_name) for row in frappe.get_doc('Contact', base.contact).links]
assert len(links) == 1
server = thread = sid = None
# Hooks run inline below; the shared drain must not process fixture messages.
patch.object(__import__('relay_core.automation.queue', fromlist=['wake']), 'wake').start()
try:
    person = insert('Contact', first_name=label, links=links)
    contact = insert('Relay Contact', contact=person.name, display_name=label, automation_paused=1)
    channel = insert('Relay Channel', channel='WhatsApp', account=account, enabled=1)
    insert('Relay Contact Endpoint', channel=channel.name, endpoint=phone, relay_contact=contact.name, verified=1)
    with patch('frappe.enqueue'), patch.object(voice_transcripts, 'configured_provider', return_value=None):
        poll = {'from': phone, 'id': wamid('poll'), 'timestamp': str(int(time.time())), 'type': 'unsupported',
            'errors': [{'code': 131051, 'title': 'Message type unknown', 'message': 'Message type unknown',
                        'error_data': {'details': 'Message type is currently not supported.'}}],
            'unsupported': {'raw_type': 'poll_creation', 'type': 'poll_creation'}}
        card = {'from': phone, 'id': wamid('card'), 'timestamp': str(int(time.time())), 'type': 'contacts',
            'contacts': [{'origin': 'other', 'phones': [{'phone': '+91 99999 55502', 'type': 'MOBILE', 'wa_id': '919999955502'}]}]}
        order = {'from': phone, 'id': wamid('order'), 'timestamp': str(int(time.time())), 'type': 'order',
            'order': {'catalog_id': '1', 'text': 'Need these', 'product_items': [{'product_retailer_id': 'shirt', 'quantity': 2, 'item_price': 30, 'currency': 'INR'}]}}
        system = {'from': phone, 'id': wamid('system'), 'timestamp': str(int(time.time())), 'type': 'system',
            'system': {'body': 'User changed from ' + phone + ' to 919999955503', 'wa_id': '919999955503', 'type': 'user_changed_number'}}
        voice = {'from': phone, 'id': wamid('voice'), 'timestamp': str(int(time.time())), 'type': 'audio',
            'audio': {'id': '1680364653657585', 'mime_type': 'audio/ogg; codecs=opus', 'voice': True}}
        assert deliver(poll, card, order, system, voice) == 'Projected'
        assert message(wamid('poll')).content == 'Poll messages are not supported by WhatsApp Business'
        assert json.loads(message(wamid('poll')).message_data)['unsupported']['details'] == 'Message type is currently not supported.'
        assert json.loads(message(wamid('card')).message_data)['contacts'][0]['name']['formatted_name'] == '+91 99999 55502'
        assert message(wamid('order')).content == 'Order: 1 item · Need these'
        note = message(wamid('system'))
        assert (note.message_type, note.relay_contact) == ('system', contact.name)
        assert not frappe.db.exists('Relay Contact Endpoint', {'endpoint': '919999955503'}), 'Number change must not add a contact'
        print('PASS poll, unnamed contact card, order and number change land as readable messages', flush=True)

        reaction = lambda emoji, number: {'from': phone, 'id': wamid('reaction' + number), 'timestamp': str(int(time.time()) + int(number)),
            'type': 'reaction', 'reaction': {'message_id': wamid('order'), **({'emoji': emoji} if emoji else {})}}
        assert deliver(reaction('👍', '1')) == 'Projected'
        assert json.loads(message(wamid('order')).reactions) == {phone: [{'type': 'emoji', 'emoji': '👍'}]}
        assert deliver(reaction('', '2')) == 'Projected'
        assert json.loads(message(wamid('order')).reactions) == {phone: []}
        edit = {'from': phone, 'id': wamid('edit'), 'timestamp': str(int(time.time()) + 3), 'type': 'edit',
            'edit': {'original_message_id': wamid('order'), 'message': {'type': 'text', 'text': {'body': 'Need three'}}}}
        assert deliver(edit) == 'Projected'
        assert (message(wamid('order')).content, bool(message(wamid('order')).edited_at)) == ('Need three', True)
        print('PASS reaction attaches and removal clears; edit updates the original', flush=True)

        # The voice step runs in the message hook drain; no provider means an honest status.
        voice_transcripts.on_message(message(wamid('voice')))
        assert message(wamid('voice')).transcript_status == 'Unavailable'

    outgoing = insert('Relay Message', relay_contact=contact.name, channel=channel.name, direction='Outgoing', status='Sent',
        content='Your order is ready', provider_id=wamid('outgoing'), sender_endpoint=phone,
        provider_message_key=__import__('relay_core.message_updates', fromlist=['provider_key']).provider_key(channel.name, phone, wamid('outgoing')),
        business_doctype=links[0]['link_doctype'], business_name=links[0]['link_name'])
    failed = {'id': wamid('outgoing'), 'recipient_id': phone, 'status': 'failed', 'timestamp': str(int(time.time())),
        'errors': [{'code': 131049, 'title': 'This message was not delivered to maintain healthy ecosystem engagement.',
                    'error_data': {'details': 'In order to maintain a healthy ecosystem engagement, the message failed to be delivered.'}}]}
    assert deliver(statuses=[failed]) == 'Projected'
    outgoing.reload()
    assert outgoing.status == 'Failed' and outgoing.delivery_error.endswith('(code 131049)'), outgoing.delivery_error
    print('PASS failed receipt shows the Meta error on the message', flush=True)

    # Fixture hooks were exercised inline; mark them done before the first commit.
    frappe.db.set_value('Relay Message', {'channel': channel.name}, 'automation_status', 'Complete', update_modified=False)
    provider = frappe._dict(provider='OpenAI', model='fixture-transcribe', enabled=1, get_password=lambda field: 'local-fixture-only')
    source = message(wamid('voice'))
    frappe.db.set_value('Relay Message', source.name, 'transcript_status', '')
    with patch('frappe.enqueue') as enqueue, patch.object(voice_transcripts, 'configured_provider', return_value=provider), \
            patch('relay_core.attachments.read', return_value=frappe._dict(get_data=lambda: b'OggS', mimetype='audio/ogg')), \
            patch.object(multimodal, 'transcribe', return_value='Please send the blue shirts') as transcribe:
        voice_transcripts.on_message(source)
        assert enqueue.call_args.kwargs['job_id'] == 'relay-voice-transcript:' + source.name
        voice_transcripts.process(source.name); voice_transcripts.process(source.name)
        assert transcribe.call_count == 1
    source.reload()
    assert (source.transcript, source.transcript_status) == ('Please send the blue shirts', 'Completed')
    frappe.db.commit()
    print('PASS voice transcript is stored once on the message', flush=True)

    from frappe.auth import LoginManager
    from werkzeug.test import EnvironBuilder
    from werkzeug.wrappers import Request
    frappe.local.request = Request(EnvironBuilder(path='/').get_environ())
    from frappe.auth import CookieManager
    frappe.local.cookie_manager = CookieManager()
    frappe.local.login_manager = LoginManager(); frappe.local.login_manager.login_as('Administrator')
    sid = frappe.session.sid; frappe.db.commit()
    server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f'http://127.0.0.1:{server.server_port}/api/method/'
    auth = {'Cookie': 'sid=' + sid}
    response = requests.get(url + 'relay_core.api.messages', params={'contact': contact.name, 'query': 'blue shirts'}, headers=auth, timeout=20)
    assert response.status_code == 200, (response.status_code, response.text[:300])
    items = response.json()['message']['items']
    assert [row['name'] for row in items] == [source.name] and items[0]['transcript_status'] == 'Completed'
    response = requests.get(url + 'relay_core.api.message_snapshots', params={'contact': contact.name, 'names': json.dumps([outgoing.name])}, headers=auth, timeout=20)
    assert response.status_code == 200 and response.json()['message']['items'][0]['delivery_error'].endswith('(code 131049)')
    response = requests.get(url + 'relay_core.message_derivatives.transcript', params={'message': source.name}, headers=auth, timeout=20)
    assert response.status_code == 200 and response.json()['message']['text'] == 'Please send the blue shirts'
    for method in ('relay_core.api.messages', 'relay_core.message_derivatives.transcript'):
        denied = requests.get(url + method, params={'contact': contact.name, 'message': source.name}, timeout=20)
        assert denied.status_code == 403, (method, denied.status_code)
    print('PASS HTTP messages search transcript, snapshots carry delivery error, transcript API, Guest denied', flush=True)
finally:
    if server:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    frappe.db.rollback(); frappe.set_user('Administrator')
    if sid:
        from frappe.sessions import delete_session
        delete_session(sid, reason='Test finished')
    channels = [doc.name for doc in created if doc.doctype == 'Relay Channel']
    if channels:
        frappe.db.delete('Relay Message', {'channel': ['in', channels]})
    frappe.db.delete('Relay Hub Event', {'account': account})
    for doc in reversed(created):
        if doc.doctype not in ('Relay Message', 'Relay Hub Event') and frappe.db.exists(doc.doctype, doc.name):
            frappe.delete_doc(doc.doctype, doc.name, ignore_permissions=True, force=True)
    frappe.db.commit(); frappe.destroy()
