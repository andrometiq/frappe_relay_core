"""Local relay.test HTTP acceptance for where a thread opens and for received media failures.

Only worktree code runs; the Hub is a local fake, so no provider is contacted.
Run from the bench sites folder: PYTHONPATH=<worktree>:<worktree>/tests CI=1 ../env/bin/python -B <this file>
"""
import base64
import json
import secrets
import threading
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from wsgiref.simple_server import make_server, WSGIRequestHandler
import requests
import frappe
import frappe.app
from relay_core import inbox, messaging, received_media, whatsapp
from relay_core.hub import HubClient, HubError

SITE = 'relay.test'
assert Path(inbox.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1]), 'Run with this checkout first on PYTHONPATH'


def connect():
    frappe.init(site=SITE)
    frappe.connect()
    frappe.set_user('Administrator')
    frappe.flags.mute_emails = True
    frappe.conf.relay_automation_enabled = 0


def fixture(doctype, filters, values):
    name = frappe.db.get_value(doctype, filters, 'name')
    return frappe.get_doc(doctype, name) if name else frappe.get_doc(dict(doctype=doctype, **values)).insert()


class Quiet(WSGIRequestHandler):
    def log_message(self, *args): pass


WEBP = b'RIFF\x10\x00\x00\x00WEBPVP8 local sticker'


def jpeg():
    """A real photo: Frappe re-encodes a kept JPEG to strip its EXIF data."""
    from io import BytesIO
    from PIL import Image
    buffer = BytesIO(); Image.new('RGB', (2, 2), 'white').save(buffer, 'JPEG')
    return buffer.getvalue()


class FakeHub:
    """Answers whatsapp.attachment and whatsapp.media by media ID: expired, busy, a small photo or a sticker."""
    calls = []
    media = HubClient.media

    def call_tool(self, name, arguments):
        self.calls.append(arguments['media_id'])
        if name == 'whatsapp.media':
            if arguments['media_id'] == '7101':
                raise HubError('rejected', {'provider': 'Hub', 'error': {'check': 'provider_metadata'}})
            return {'content_base64': base64.b64encode(WEBP).decode(), 'content_type': 'image/webp'}
        assert name == 'whatsapp.attachment'
        if arguments['media_id'] == '7001':
            raise HubError('rejected', {'provider': 'Hub', 'error': {'check': 'provider_metadata'}})
        if arguments['media_id'] == '7002':
            raise HubError('rejected', {'provider': 'Hub', 'error': {'check': 'capacity'}})
        if arguments['media_id'] == '7005':
            raise HubError('rejected', {'provider': 'Hub', 'error': {'check': 'ownership'}})
        raw = jpeg() if arguments['media_id'] == '7004' else b'local photo bytes'
        return {'content_base64': base64.b64encode(raw).decode(), 'content_type': 'image/jpeg'}


with ExitStack() as stack:
    for target in ('enqueue', 'publish_realtime', 'sendmail'):
        stack.enter_context(patch.object(frappe, target))
    stack.enter_context(patch.object(whatsapp, 'client', return_value=FakeHub()))
    stack.enter_context(patch.object(messaging, 'connection_value', side_effect=lambda key: 'local-media-view' if key == 'relay_hub_account' else None))
    connect()
    assert frappe.db.exists('Relay Contact Type', {'business_doctype': 'Customer', 'enabled': 1})
    user = fixture('User', {'email': 'relay-media-view@example.invalid'}, {'email': 'relay-media-view@example.invalid',
        'first_name': 'Local media view verifier', 'send_welcome_email': 0, 'roles': [{'role': 'System Manager'}]})
    api_key, api_secret = secrets.token_hex(12), secrets.token_hex(24)
    user.api_key = api_key; user.api_secret = api_secret; user.enabled = 1; user.save()
    # A Relay user with no business type assigned: it may read the Relay Message DocType but not this conversation.
    outsider = fixture('User', {'email': 'relay-media-outsider@example.invalid'}, {'email': 'relay-media-outsider@example.invalid',
        'first_name': 'Local media outsider', 'send_welcome_email': 0, 'roles': [{'role': 'Relay Communication User'}]})
    outsider_key, outsider_secret = secrets.token_hex(12), secrets.token_hex(24)
    outsider.api_key = outsider_key; outsider.api_secret = outsider_secret; outsider.enabled = 1; outsider.save()
    business = fixture('Customer', {'customer_name': 'Local media view verification'}, {
        'customer_name': 'Local media view verification', 'customer_type': 'Company',
        'customer_group': frappe.db.get_value('Customer Group', {'is_group': 0}, 'name'),
        'territory': frappe.db.get_value('Territory', {'is_group': 0}, 'name')})
    person = fixture('Contact', {'first_name': 'Local Media Ravi'}, {'first_name': 'Local Media Ravi',
        'links': [{'link_doctype': 'Customer', 'link_name': business.name}]})
    contact = fixture('Relay Contact', {'contact': person.name}, {'contact': person.name, 'display_name': 'Local Media Ravi'})
    channel = fixture('Relay Channel', {'title': 'Local media view'}, {'title': 'Local media view', 'channel': 'WhatsApp',
        'account': 'local-media-view', 'enabled': 0})
    fixture('Relay Contact Endpoint', {'channel': channel.name, 'endpoint': 'local-media-ravi'}, {'channel': channel.name,
        'relay_contact': contact.name, 'endpoint': 'local-media-ravi', 'verified': 1})

    def message(content, kind, media_id=None):
        mime = 'image/webp' if kind == 'sticker' else 'image/jpeg'
        data = {'kind': kind, 'text': content} if kind == 'text' else {'kind': kind, 'media': {'id': media_id, 'mime_type': mime}}
        return fixture('Relay Message', {'channel': channel.name, 'content': content}, {
            'relay_contact': contact.name, 'channel': channel.name, 'direction': 'Incoming', 'status': 'Sent',
            'content': content, 'message_type': kind, 'message_data': json.dumps(data), 'sender_endpoint': 'local-media-ravi'})
    expired, busy, recent = message('Local media expired photo', 'image', '7001'), message('Local media busy photo', 'image', '7002'), message('Local media recent photo', 'image', '7003')
    kept, kept_sticker = message('Local media kept photo', 'image', '7004'), message('Local media kept sticker', 'sticker', '7102')
    week_old, old_sticker = message('Local media week-old photo', 'image', '7001'), message('Local media expired sticker', 'sticker', '7101')
    refused = message('Local media refused photo', 'image', '7005')
    # Created last but sent first: the conversation opens at it because thread order is by sent time.
    earliest = message('Local media earliest question', 'text')
    now = frappe.utils.now_datetime()
    for row, sent in ((expired, now - timedelta(days=40)), (busy, now - timedelta(hours=1)), (recent, now - timedelta(minutes=5)), (earliest, now - timedelta(days=41)),
                      (kept, now - timedelta(minutes=4)), (kept_sticker, now - timedelta(minutes=3)), (week_old, now - timedelta(days=8)), (old_sticker, now - timedelta(days=8))):
        frappe.db.set_value('Relay Message', row.name, 'sent_at', sent, update_modified=False)
    for row in (busy, recent, refused):  # Rows from an earlier run must stay inside the backfill window.
        frappe.db.set_value('Relay Message', row.name, 'creation', now, update_modified=False)
    state = frappe.db.get_value('Relay Conversation State', {'state_key': inbox.state_key(contact.name, user.name)}, 'name')
    if state: frappe.delete_doc('Relay Conversation State', state, ignore_permissions=True, force=True)
    frappe.db.delete('Relay Message Read', {'user': user.name, 'message': ['in', [expired.name, busy.name, recent.name, earliest.name]]})
    for row in (kept, kept_sticker, refused):
        stale = frappe.get_all('File', filters={'attached_to_doctype': 'Relay Message', 'attached_to_name': row.name}, pluck='name')
        for file in stale: frappe.delete_doc('File', file, ignore_permissions=True, force=True)
        data = json.loads(frappe.db.get_value('Relay Message', row.name, 'message_data'))
        for key in ('attachment', 'attachment_source', received_media.SKIPPED): data.pop(key, None)
        frappe.db.set_value('Relay Message', row.name, 'message_data', json.dumps(data), update_modified=False)
    frappe.db.set_value('Relay Channel', channel.name, 'enabled', 1)
    frappe.db.commit()
    for row in (kept, kept_sticker):
        assert received_media.store(row.name) == 'stored', row.name
        assert received_media.store(row.name) == 'skipped', 'a kept copy is never downloaded again'
        assert len(frappe.get_all('File', filters={'attached_to_doctype': 'Relay Message', 'attached_to_name': row.name, 'is_private': 1})) == 1
    assert FakeHub.calls == ['7004', '7102'], FakeHub.calls
    assert frappe.db.get_value('File', json.loads(frappe.db.get_value('Relay Message', kept_sticker.name, 'message_data'))['attachment'], 'file_name') == 'sticker.webp'
    assert received_media.store(week_old.name) == 'expired' and FakeHub.calls == ['7004', '7102'], 'media Meta no longer keeps is not fetched'
    print('PASS site store keeps one private File per received photo and sticker, never twice, and skips media older than 7 days')
    assert received_media.store(refused.name) == 'failed' and FakeHub.calls[-1] == '7005'
    assert received_media.SKIPPED in json.loads(frappe.db.get_value('Relay Message', refused.name, 'message_data'))
    assert received_media.store(refused.name) == 'skipped' and FakeHub.calls.count('7005') == 1, 'refused media is not downloaded again'
    missing = received_media.get_missing(7)
    assert recent.name in missing and busy.name in missing, missing
    assert not {kept.name, kept_sticker.name, refused.name, week_old.name} & set(missing), missing
    print('PASS site store marks media WhatsApp refuses and the backfill lists only media without a copy or a mark')
    names = {'expired': expired.name, 'busy': busy.name, 'recent': recent.name, 'earliest': earliest.name, 'newest': max(row.name for row in (expired, busy, recent, earliest, kept, kept_sticker, week_old, old_sticker, refused)),
             'kept': kept.name, 'kept_sticker': kept_sticker.name, 'week_old': week_old.name, 'old_sticker': old_sticker.name,
             'kept_url': frappe.db.get_value('File', {'attached_to_doctype': 'Relay Message', 'attached_to_name': kept.name}, 'file_url')}
    contact_name, user_name, channel_name, outsider_name = contact.name, user.name, channel.name, outsider.name
    frappe.destroy()

    original_init = frappe.app.init_request
    def init_request(request):
        original_init(request)
        frappe.flags.mute_emails = True
        frappe.conf.relay_automation_enabled = 0
    stack.enter_context(patch.object(frappe.app, 'init_request', init_request))
    def application(environ, start_response):
        environ['HTTP_X_FRAPPE_SITE_NAME'] = SITE
        return frappe.app.application(environ, start_response)
    server = make_server('127.0.0.1', 0, application, handler_class=Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f'http://127.0.0.1:{server.server_port}/api/method/relay_core.'
    headers = {'Authorization': 'token ' + api_key + ':' + api_secret}
    get = lambda method, params, auth=True: requests.get(url + method, params=params, headers=headers if auth else {}, timeout=20)
    try:
        response = get('inbox.view_state', {'contact': contact_name})
        assert response.status_code == 200, response.text[:300]
        state = response.json()['message']
        assert state['first_unread'] == names['earliest'] and state['channel'] == '', state
        assert get('inbox.view_state', {'contact': contact_name, 'channel': channel.name}).json()['message']['first_unread'] == names['earliest']
        assert get('inbox.view_state', {'contact': contact_name}, auth=False).status_code in (401, 403)
        update = requests.post(url + 'inbox.update', json={'contact': contact_name, 'last_read': names['newest']}, headers=headers, timeout=20)
        assert update.status_code == 200, update.text[:300]
        assert get('inbox.view_state', {'contact': contact_name}).json()['message']['first_unread'] is None
        print('PASS HTTP view_state names the first unread message in thread order, none once read, and denies guests')

        expired_response = get('attachments.read', {'message': names['expired']})
        assert expired_response.status_code == 410, expired_response.status_code
        assert 'Media no longer available from WhatsApp' in expired_response.json()['_server_messages']
        busy_response = get('attachments.read', {'message': names['busy']})
        assert busy_response.status_code == 503 and 'Try again' in busy_response.json()['_server_messages']
        photo = get('attachments.read', {'message': names['recent']})
        assert photo.status_code == 200 and photo.headers['Content-Type'] == 'image/jpeg' and photo.content == b'local photo bytes'
        assert get('attachments.read', {'message': names['recent']}, auth=False).status_code in (401, 403)
        print('PASS HTTP media read: 410 with a readable reason for expired media, 503 retry for a busy Hub, bytes, guest denial')

        FakeHub.calls.clear()
        photo = get('attachments.read', {'message': names['kept']})
        assert photo.status_code == 200 and photo.content[:2] == b'\xff\xd8' and photo.headers['Content-Type'] == 'image/jpeg', photo.status_code
        sticker = get('messaging.sticker', {'message': names['kept_sticker']})
        assert sticker.status_code == 200 and sticker.content == WEBP and sticker.headers['Content-Type'] == 'image/webp', sticker.status_code
        assert FakeHub.calls == [], FakeHub.calls
        assert get('messaging.sticker', {'message': names['kept_sticker']}, auth=False).status_code in (401, 403)
        week = get('attachments.read', {'message': names['week_old']})
        assert week.status_code == 410 and 'no longer available' in week.json()['_server_messages'], week.status_code
        gone = get('messaging.sticker', {'message': names['old_sticker']})
        assert gone.status_code == 410 and 'no longer available' in gone.json()['_server_messages'], gone.status_code
        print('PASS HTTP kept photo and sticker are served without the Hub; 8-day-old photo and sticker are 410; guests are denied')

        site = url.split('/api/')[0]
        outsider_headers = {'Authorization': 'token ' + outsider_key + ':' + outsider_secret}
        def listed(auth):
            response = requests.get(site + '/api/resource/File', headers=auth, timeout=20, params={'fields': '["file_url"]',
                'filters': json.dumps([['attached_to_doctype', '=', 'Relay Message'], ['attached_to_name', '=', names['kept']]])})
            assert response.status_code == 200, response.text[:300]
            return response.json()['data']
        assert listed(headers) == [{'file_url': names['kept_url']}]
        assert listed(outsider_headers) == [], 'a Relay user who cannot open the conversation does not see its files'
        download = lambda auth: requests.get(site + names['kept_url'], headers=auth, timeout=20).status_code
        assert download(headers) == 200 and download(outsider_headers) == 403 and download({}) in (401, 403)
        print('PASS HTTP kept File is listed and downloaded only by a user who can read the conversation')
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        connect()
        for name in (user_name, outsider_name):
            user = frappe.get_doc('User', name)
            user.api_key = None; user.api_secret = None; user.enabled = 0; user.save()
        frappe.db.set_value('Relay Channel', channel_name, 'enabled', 0)
        frappe.db.commit(); frappe.destroy()
