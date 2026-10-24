"""Typed message/reaction/media simulations on the dedicated Frappe test DB.

Run after integration_channels_site.py. Every provider call goes through the
real HubClient to a loopback fixture; no external provider credentials are used.
"""
from site_labels import run_label
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from unittest.mock import patch

sites = os.environ.get('RELAY_AUTOMATION_TEST_SITES')
assert sites and Path(sites).resolve() == (Path(__file__).resolve().parents[1] / '.runtime/automation-bench/sites').resolve()
os.chdir(sites)
import frappe
from relay_core import settings as connection_settings
# Fixture transports and signatures use process-local synthetic configuration.
# Never replace the installed review site's encrypted connection credentials.
fixture_connection = patch.object(connection_settings, 'value', side_effect=lambda key: frappe.conf.get(key))
fixture_connection.start()
from relay_core import api, mcp, messaging, whatsapp, attachments, conversation_start, service_window
from relay_core.automation import projection, service
from relay_core.automation.provenance import context_of
from relay_core.hub import HubClient, HubError
from relay_core.message_updates import provider_key

frappe.init(site='relay-ai-test.local')
assert frappe.conf.db_name == 'relay_ai_test_20260922' and frappe.conf.db_host in ('127.0.0.1', 'localhost')
frappe.connect(); frappe.clear_cache(); frappe.set_user('Administrator'); frappe.flags.mute_emails = True
for doctype in ('relay_message', 'relay_automation_run', 'relay_message_action', 'relay_canned_reply', 'relay_saved_reply_action'):
    frappe.reload_doc('relay_core', 'doctype', doctype, force=True)
frappe.conf.relay_automation_enabled = 1
run_id = run_label(); account = 'types-' + run_id
frappe.conf.relay_hub_account = account
actor = 'channels-executor@example.invalid'
if not frappe.db.exists('Relay Contact Type', {'business_doctype': 'Relay Channel Simulation Business'}):
    frappe.get_doc(dict(doctype='Relay Contact Type', business_doctype='Relay Channel Simulation Business', enabled=1)).insert()
business = frappe.get_doc(dict(doctype='Relay Channel Simulation Business', title='Types business ' + run_id)).insert()
person = frappe.get_doc(dict(doctype='Contact', first_name='Types ' + run_id,
    phone_nos=[dict(phone='919000000055', is_primary_mobile_no=1)],
    links=[dict(link_doctype=business.doctype, link_name=business.name)])).insert()
contact = frappe.get_doc(dict(doctype='Relay Contact', contact=person.name, display_name='Types ' + run_id)).insert()
channels, bindings = {}, {}
for medium, addresses in [('Telegram', ('900555', '-100555')), ('WhatsApp', ('919000000055', 'types-group'))]:
    channels[medium] = frappe.get_doc(dict(doctype='Relay Channel', channel=medium, account=account, enabled=1)).insert()
    for address in addresses:
        bindings[medium, address] = frappe.get_doc(dict(doctype='Relay Contact Endpoint', channel=channels[medium].name,
            endpoint=address, relay_contact=contact.name, verified=1)).insert()
frappe.db.commit()
counter = 0; checks = []
card = {'name': {'formatted_name': '<script>literal contact</script>', 'first_name': 'Literal'},
        'phones': [{'phone': '+919000000055'}], 'emails': [{'email': 'safe@example.invalid'}],
        'addresses': [{'street': '1 Test road', 'city': 'Chennai', 'country': 'India'}],
        'org': {'company': 'Synthetic company'}, 'birthday': '2000-01-01', 'urls': [{'url': 'https://example.invalid'}]}

def next_id():
    global counter
    counter += 1; return counter

def passed(label):
    checks.append(label); print('PASS ' + label, flush=True)

def telegram_payload(kind='text', chat=900555, detail=None, update=None, provider_message=None, event='message', date=1700000000):
    number = next_id() if update is None else update
    message = {'message_id': number if provider_message is None else provider_message, 'date': date,
        'chat': {'id': chat, 'type': 'supergroup' if chat < 0 else 'private'}, 'from': {'id': 900555, 'is_bot': False}}
    if chat < 0: message['message_thread_id'] = 7
    default = {'text': 'Typed help', 'sticker': {'file_id': 'tg-sticker-file', 'is_animated': False, 'is_video': False},
               'location': {'latitude': 0, 'longitude': 0}, 'contact': {'phone_number': '+919000000055', 'first_name': '<b>Literal</b>'}}
    message[kind] = default[kind] if detail is None else detail
    if event == 'edited_message': message['edit_date'] = date
    return {'channel': 'Telegram', 'direction': 'inbound', 'provider_id': str(number), 'sender': str(chat),
            'body': message.get('text', message.get('caption', '')), 'payload': {'update_id': number, event: message}}

def whatsapp_payload(kind='text', address='919000000055', detail=None):
    number = next_id(); message = {'id': 'wamid.types.' + str(number), 'from': '919000000055', 'type': kind, 'timestamp': str(int(time.time()))}
    if address == 'types-group': message['group_id'] = address
    defaults = {'text': {'body': 'Typed help'}, 'sticker': {'id': 'wa-sticker-file', 'mime_type': 'image/webp', 'animated': True},
                'location': {'latitude': 0, 'longitude': 0, 'name': 'Zero point'}, 'contacts': [card]}
    message[kind] = defaults[kind] if detail is None else detail
    return {'entry': [{'changes': [{'field': 'messages', 'value': {'messages': [message]}}]}]}

def project(value):
    medium = value.get('channel', 'WhatsApp')
    with patch.object(frappe, 'enqueue'):
        event = frappe.get_doc(dict(doctype='Relay Hub Event', event_key=account + '-' + str(next_id()), account=account,
            hub_event_id=str(counter), payload=json.dumps(value))).insert()
        projection.project(event.name)
    frappe.db.commit(); event.reload()
    try: messages = projection.extract_messages(value)
    except (ValueError, TypeError): messages = []
    name = None
    if messages:
        row = messages[0]; context = row.get('provider_context', {})
        name = frappe.db.get_value('Relay Message', {'provider_message_key': provider_key(channels[medium].name,
            row['from'], context.get('message_id') or row['id'])}, 'name')
    return event, frappe.get_doc('Relay Message', name) if name else None

token = 'synthetic-typed-mcp-' + run_id
webp = b'RIFF\x0c\x00\x00\x00WEBPVP8 synthetic'
class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *_): pass
    def do_POST(self):
        try:
            size = int(self.headers['Content-Length']); assert size < 65536
            value = json.loads(self.rfile.read(size)); assert self.headers.get('Authorization') == 'Bearer ' + token
            if value['method'] == 'initialize': result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'typed-fixture', 'version': 'test'}}
            elif value['method'] == 'notifications/initialized':
                self.send_response(202); self.send_header('Content-Length', '0'); self.end_headers(); return
            else:
                assert self.headers.get('MCP-Protocol-Version') == '2025-06-18'
                params = value['params']; self.server.calls.append(params); self.server.sent += 1
                if params['name'] in ('channels.deliveries','whatsapp.deliveries'):
                    result={'structuredContent':{'deliveries':[{'key':params['arguments']['request_key'],'operation':'telegram.message','state':'uncertain'}]}}
                elif self.server.fail:
                    result = {'isError': True, 'structuredContent': {'provider': 'Telegram', 'error': {'outcome_unknown': True}}}
                elif params['name'].endswith('.media'):
                    result = {'structuredContent': {'content_base64': base64.b64encode(webp).decode(), 'content_type': 'image/webp', 'filename': 'ignored-untrusted-name.webp'}}
                elif params['name'] == 'telegram.message':
                    args = params['arguments']; assert args['operation'] in ('text', 'sticker', 'reaction', 'location', 'contact', 'document')
                    if args['operation'] == 'reaction': assert 'reply_to' not in args and 'message_thread_id' not in args
                    result = {'structuredContent': {'message_id': args['message_id'] if args['operation']=='reaction' else 100000 + self.server.sent, 'chat_id': args['chat_id'], 'operation': args['operation']}}
                    if args['operation']=='reaction':result['structuredContent']['result']=True
                elif params['name'] == 'whatsapp.enqueue':
                    assert {item['message']['operation'] for item in params['arguments']['messages']} == {'messages.location', 'messages.contacts'}
                    result = {'structuredContent': {'accepted': 2}}
                elif params['name'] == 'whatsapp.execute' and params['arguments']['operation'] == 'capabilities':
                    result = {'structuredContent': {'site': self.server.site_url}}
                elif params['name'] == 'whatsapp.execute':
                    args = params['arguments']; assert args['operation'] in ('templates.send', 'messages.send', 'groups.send', 'messages.media', 'groups.media', 'messages.location', 'messages.contacts', 'messages.react')
                    result = {'structuredContent': {'messages': [{'id': 'wamid.outbound.' + str(self.server.sent)}]}}
                else: raise AssertionError('Unexpected tool ' + params['name'])
            raw = json.dumps({'jsonrpc': '2.0', 'id': value['id'], 'result': result}).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
        except Exception as exc:
            self.server.errors.append(str(exc)); self.send_response(500); self.send_header('Content-Length', '0'); self.end_headers()
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.daemon_threads = True
server.calls, server.errors, server.sent, server.fail = [], [], 0, False
server.site_url = frappe.utils.get_url().rstrip('/')
thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
client = HubClient(f'http://127.0.0.1:{server.server_port}/mcp', token)

def send(source, kind, data, key=None, quote=1):
    frappe.set_user(actor)
    try:
        with patch.object(whatsapp, 'client', return_value=client):
            return messaging.send(source.name, kind, data, run_id + '-' + (key or 'action-' + str(next_id())), quote=quote)
    finally: frappe.set_user('Administrator')

try:
    sources, stickers = {}, {}
    for medium, address in [('Telegram', '900555'), ('Telegram', '-100555'), ('WhatsApp', '919000000055'), ('WhatsApp', 'types-group')]:
        for kind in ('text', 'sticker', 'location', 'contact'):
            value = telegram_payload(kind, int(address)) if medium == 'Telegram' else whatsapp_payload('contacts' if kind == 'contact' else kind, address)
            event, doc = project(value)
            assert event.projection_status == 'Projected' and doc, (medium, kind, event.projection_status)
            data = messaging.object_value(doc.message_data)
            assert data['kind'] in (kind, 'contacts')
            if kind == 'location': assert data['location']['latitude'] == 0 and data['location']['longitude'] == 0
            if kind == 'contact':
                assert '<' in data['contacts'][0]['name']['formatted_name']
                if medium == 'WhatsApp':
                    assert data['contacts'][0]['addresses'][0]['city'] == 'Chennai'
                    assert data['contacts'][0]['org']['company'] == 'Synthetic company'
            if kind == 'text': sources[medium, address] = doc
            if kind == 'sticker': stickers[medium, address] = doc
        passed(medium + ' ' + address + ': typed text/sticker/location/contact inbound data retained without HTML rendering')

    published=frappe.get_doc(dict(doctype='Relay Canned Reply',title='Saved '+run_id,channel='Telegram',language='English',body='Published fixture reply',published=1)).insert()
    unpublished=frappe.get_doc(dict(doctype='Relay Canned Reply',title='Saved '+run_id+' hidden',channel='Telegram',language='English',body='Private draft',published=0)).insert()
    frappe.set_user(actor)
    choices=messaging.canned_replies(sources['Telegram','900555'].name,query=run_id)['items']
    assert len(choices)==1 and choices[0].body=='Published fixture reply'
    assert not messaging.canned_replies(sources['WhatsApp','919000000055'].name,query=run_id)['items']
    frappe.set_user('Administrator')
    frappe.delete_doc('Relay Canned Reply',published.name,ignore_permissions=True)
    frappe.delete_doc('Relay Canned Reply',unpublished.name,ignore_permissions=True)
    passed('saved reply picker exposes only published replies for the authorized source channel')
    frappe.db.savepoint('saved_reply_paging')
    stamp=frappe.utils.now_datetime()
    frappe.db.bulk_insert('Relay Canned Reply',fields=['name','title','channel','language','body','reply_type','published','creation','modified'],values=[['paging-'+run_id+'-'+str(i).zfill(3),'Paged '+run_id,'Telegram','Tamil','Saved answer '+str(i),'Text',1,stamp,stamp] for i in range(45)])
    frappe.set_user(actor)
    pages=[];cursor=None
    for expected in (20,20,5):
        page=messaging.canned_replies(sources['Telegram','900555'].name,query='Paged '+run_id,after=cursor)
        assert len(page['items'])==expected
        pages.extend(row.name for row in page['items']);cursor=page['next']
    assert cursor is None and len(set(pages))==45 and pages==sorted(pages)
    assert not messaging.canned_replies(sources['Telegram','900555'].name,query='%')['items']
    try:messaging.canned_replies(sources['Telegram','900555'].name,after='[42]')
    except frappe.ValidationError:pass
    else:raise AssertionError('Malformed saved reply cursor accepted')
    frappe.db.rollback(save_point='saved_reply_paging');frappe.set_user('Administrator')
    passed('saved replies keyset-page duplicate titles 20/20/5 without omissions and reject invalid cursors')

    from relay_core import saved_reply_actions
    hook={'fixture.saved':{'label':'Fixture business action','method':'fixture.saved_action','replay_safe':True,'parameters':{'type':'object','properties':{'note':{'type':'string'}},'required':['note']}}}
    original_hooks=frappe.get_hooks;original_attr=frappe.get_attr;calls=[]
    def handler(**kwargs):
        calls.append(kwargs)
        assert frappe.session.user==actor
        return {'updated':True}
    with patch.object(frappe,'get_hooks',side_effect=lambda name=None,*args,**kwargs:hook if name=='relay_saved_reply_actions' else original_hooks(name,*args,**kwargs)), patch.object(frappe,'get_attr',side_effect=lambda name:handler if name=='fixture.saved_action' else original_attr(name)):
        configured=frappe.get_doc(dict(doctype='Relay Canned Reply',title='Action '+run_id,channel='Telegram',language='English',body='Action reply',published=1,action_key='fixture.saved',action_arguments='{"note":"Approved note"}')).insert()
        frappe.db.commit();frappe.set_user(actor)
        source=sources['Telegram','900555'].name
        choices=messaging.canned_replies(source,query='Action '+run_id)['items']
        assert choices[0].action_label=='Fixture business action' and 'action_arguments' not in choices[0]
        receipt=saved_reply_actions.execute(source,configured.name,'saved-action-'+run_id)
        replay=saved_reply_actions.execute(source,configured.name,'saved-action-'+run_id)
        assert receipt['receipt']==replay['receipt'] and replay['replayed'] and len(calls)==1
        assert calls[0]['source_message']==source and calls[0]['relay_contact']==contact.name
        try:saved_reply_actions.execute(sources['WhatsApp','919000000055'].name,configured.name,'saved-action-'+run_id)
        except frappe.PermissionError:pass
        else:raise AssertionError('Cross-channel action allowed')
        frappe.set_user('Administrator');configured.action_arguments='{"note":"Changed"}';configured.save();frappe.db.commit();frappe.set_user(actor)
        try:saved_reply_actions.execute(source,configured.name,'saved-action-'+run_id)
        except frappe.ValidationError:pass
        else:raise AssertionError('Changed action replay allowed')
        assert len(calls)==1
        frappe.set_user('Administrator');configured.published=0;configured.save();frappe.db.commit();frappe.set_user(actor)
        try:saved_reply_actions.execute(source,configured.name,'fresh-action-'+run_id)
        except frappe.PermissionError:pass
        else:raise AssertionError('Unpublished action allowed')
        frappe.set_user('Administrator');frappe.delete_doc('Relay Saved Reply Action',receipt['receipt'],ignore_permissions=True);frappe.delete_doc('Relay Canned Reply',configured.name,ignore_permissions=True)
    passed('saved reply actions use server-configured inputs, actor permissions and durable replay receipts; reject cross-channel, changed and unpublished actions')
    builtin=frappe.get_doc(dict(doctype='Relay Canned Reply',title='Note action '+run_id,channel='Telegram',language='English',body='We have recorded your request.',published=1,action_key='relay.add_internal_note',action_arguments='{"note":"Saved action note"}')).insert()
    frappe.db.commit();frappe.set_user(actor)
    with patch('relay_core.automation.service.internal_save',side_effect=RuntimeError('Lost receipt after handler commit')):
        try:saved_reply_actions.execute(sources['Telegram','900555'].name,builtin.name,'crash-action-'+run_id)
        except RuntimeError:pass
        else:raise AssertionError('Crash fixture did not run')
    first=saved_reply_actions.execute(sources['Telegram','900555'].name,builtin.name,'crash-action-'+run_id)
    again=saved_reply_actions.execute(sources['Telegram','900555'].name,builtin.name,'crash-action-'+run_id)
    assert first['receipt']==again['receipt']
    assert frappe.db.count('Relay Internal Comment',{'relay_contact':contact.name,'body':'Saved action note'})==1
    frappe.set_user('Administrator');frappe.delete_doc('Relay Saved Reply Action',first['receipt'],ignore_permissions=True);frappe.delete_doc('Relay Canned Reply',builtin.name,ignore_permissions=True)
    passed('built-in saved reply note action survives crash after side effect with one comment and one receipt')
    structured=[]
    for values in ({'reply_type':'Location','latitude':13.0827,'longitude':80.2707},
                   {'reply_type':'Contact','contact_name':'Support desk','phone':'+919000000055'}):
        doc=frappe.get_doc(dict(doctype='Relay Canned Reply',title='Structured '+run_id,channel='Telegram',language='English',published=1,**values)).insert()
        structured.append(doc.name)
    frappe.set_user(actor)
    choices=messaging.canned_replies(sources['Telegram','900555'].name,query=run_id)['items']
    assert {row.reply_type for row in choices}=={'Location','Contact'}
    assert next(row for row in choices if row.reply_type=='Location').latitude==13.0827
    frappe.set_user('Administrator')
    for values in ({'reply_type':'Location','latitude':91,'longitude':0},
                   {'reply_type':'Contact','contact_name':'Support','phone':'not a phone'},
                   {'reply_type':'Contact','contact_name':'Support','phone':'+919000000055','ai_enabled':1}):
        try:frappe.get_doc(dict(doctype='Relay Canned Reply',title='Invalid structured',channel='Telegram',language='English',**values)).insert()
        except frappe.ValidationError:pass
        else:raise AssertionError('Invalid structured reply accepted')
    for name in structured:frappe.delete_doc('Relay Canned Reply',name,ignore_permissions=True)
    passed('structured saved replies expose location/contact drafts and reject invalid or AI-text-only usage')


    # Private file upload is bound to the exact authorized source, and replay
    # never produces a second provider side effect.
    original=sources['Telegram','-100555']
    frappe.set_user(actor)
    uploaded=attachments.upload(original.name,'evidence.txt',base64.b64encode(b'Synthetic evidence').decode())
    frappe.db.commit();frappe.set_user('Administrator')
    result=send(original,'document',{'attachment':uploaded['name'],'caption':'Evidence'},'document')
    assert result['status']=='Submitted',result
    submitted=len(server.calls)
    assert send(original,'document',{'attachment':uploaded['name'],'caption':'Evidence'},'document')['message']==result['message']
    assert len(server.calls)==submitted
    args=server.calls[-1]['arguments'];assert args['operation']=='document' and base64.b64decode(args['content_base64'])==b'Synthetic evidence'
    frappe.set_user(actor)
    response=attachments.read(result['message'])
    assert response.get_data()==b'Synthetic evidence' and response.headers['Content-Disposition'].startswith('attachment')
    try:attachments.file_content(uploaded['name'],sources['Telegram','900555'])
    except frappe.PermissionError:pass
    else:raise AssertionError('Cross-conversation attachment accepted')
    try:attachments.upload(original.name,'../escape.txt',base64.b64encode(b'x').decode())
    except frappe.ValidationError:pass
    else:raise AssertionError('Unsafe filename accepted')
    frappe.set_user('Administrator')
    passed('private attachment upload/send/download preserves routing, denies cross-conversation reuse and deduplicates retries')
    for address in ('919000000055','types-group'):
        original=sources['WhatsApp',address]
        frappe.set_user(actor)
        uploaded=attachments.upload(original.name,'evidence.txt',base64.b64encode(b'WhatsApp evidence').decode())
        frappe.db.commit();frappe.set_user('Administrator')
        result=send(original,'document',{'attachment':uploaded['name'],'caption':'Evidence'},'wa-document-'+address)
        assert result['status']=='Submitted',result
        args=server.calls[-1]['arguments']
        assert args['operation']==('groups.media' if address=='types-group' else 'messages.media')
        assert args['to']==address and args['mime_type']=='text/plain'
        assert base64.b64decode(args['content_base64'])==b'WhatsApp evidence'
        frappe.set_user(actor);assert attachments.read(result['message']).get_data()==b'WhatsApp evidence'
        frappe.set_user('Administrator')
    passed('WhatsApp private file uploads preserve private/group routing and authorized local downloads')

    for (medium, address), source in sources.items():
        for kind, data in [('text', {'text': 'Contextual reply'}), ('sticker', {'sticker_message': stickers[medium, address].name}),
                           ('location', {'latitude': 0, 'longitude': 0}), ('contact', {'contacts': [card]}),
                           ('reaction', {'emoji': '👍'}), ('reaction', {'emoji': ''})]:
            before = len(server.calls)
            if medium == 'WhatsApp' and address == 'types-group' and kind not in ('text', 'sticker'):
                try: send(source, kind, data)
                except ValueError: pass
                else: raise AssertionError('Unsupported Meta group type was sent')
                assert len(server.calls) == before; continue
            request_key = 'stable-' + str(next_id())
            result = send(source, kind, data, request_key); assert result['status'] == 'Submitted', result
            repeated = send(source, kind, data, request_key)
            assert repeated == result and len(server.calls) == before + 1
            args = server.calls[-1]['arguments']
            if medium == 'Telegram':
                assert args['chat_id'] == int(address)
                if kind == 'reaction':
                    assert args['message_id'] == context_of(source)['message_id']
                    assert args['reaction'] == ([{'type': 'emoji', 'emoji': data['emoji']}] if data['emoji'] else [])
                else:
                    assert args['reply_to'] == context_of(source)['message_id']
                    if kind == 'contact':
                        assert 'EMAIL:safe@example.invalid' in args['vcard'] and 'Chennai' in args['vcard'] and 'ORG:Synthetic company' in args['vcard']
                    assert args.get('message_thread_id') == (7 if int(address) < 0 else None)
            else: assert args['to'] == address and args['reply_to'] == source.provider_id
            if result['message']:
                outgoing = frappe.get_doc('Relay Message', result['message'])
                assert outgoing.direction == 'Outgoing' and outgoing.provider_id and outgoing.sender_endpoint == address
        passed(medium + ' ' + address + ': allowed typed replies/reactions round-trip over HTTP, with stable-key replay and destination/topic isolation')

    for (medium, address), source in sources.items():
        result=send(source,'text',{'text':'Ordinary message'},'unquoted-'+address,quote=0)
        assert result['status']=='Submitted',result
        args=server.calls[-1]['arguments']
        assert 'reply_to' not in args
        assert 'reply_to_message_id' not in context_of(frappe.get_doc('Relay Message',result['message']))
        if medium=='Telegram':
            assert args['chat_id']==int(address)
            assert args.get('message_thread_id')==(7 if int(address)<0 else None)
        else: assert args['to']==address
        before=len(server.calls)
        try:send(source,'text',{'text':'Ordinary message'},'unquoted-'+address,quote=1)
        except ValueError:pass
        else:raise AssertionError('Changed quote accepted with same key')
        assert len(server.calls)==before
    passed('ordinary sends omit quote while retaining verified destination/topic and reject changed-intent retries')

    frappe.set_user(actor)
    batch = [dict(key=run_id + '-bulk-' + operation.replace('.', '-'), operation=operation, arguments=arguments,
                  contact=person.name, business_doctype=business.doctype, business_name=business.name)
             for operation, arguments in [('messages.location', {'location': {'latitude': 0, 'longitude': 0}}),
                                          ('messages.contacts', {'contacts': [card]})]]
    with patch.object(whatsapp, 'client', return_value=client):
        result = mcp.dispatch('tools/call', {'name': 'relay.messages.bulk', 'arguments': {'messages': batch}})
    assert result['structuredContent'] == {'accepted': 2} and not result['isError'], result
    assert all(item['message']['to'] == '919000000055' for item in server.calls[-1]['arguments']['messages'])
    frappe.set_user('Administrator')
    passed('Core MCP durable bulk location/contact sends resolve business Contact recipients over real HTTP')

    original = sources['Telegram', '-100555']; target = context_of(original)['message_id']
    before_messages = frappe.db.count('Relay Message', {'relay_contact': contact.name})
    before_runs = frappe.db.count('Relay Automation Run')
    def reaction(update, items, actor_id=900555):
        return {'channel': 'Telegram', 'direction': 'inbound', 'provider_id': str(update), 'sender': '-100555', 'body': '',
            'payload': {'update_id': update, 'message_reaction': {'chat': {'id': -100555, 'type': 'supergroup'},
                'message_id': target, 'user': {'id': actor_id}, 'date': 1700000100, 'new_reaction': items}}}
    project(reaction(5002, [])); project(reaction(5001, [{'type': 'emoji', 'emoji': '👍'}])); project(reaction(5002, []))
    original.reload(); assert messaging.object_value(original.reactions)['900555'] == []
    assert frappe.db.count('Relay Message', {'relay_contact': contact.name}) == before_messages
    assert frappe.db.count('Relay Automation Run') == before_runs
    passed('Telegram same-second out-of-order reaction and duplicate clear update only original message, with no new turn or AI run')

    edit = telegram_payload('text', -100555, 'Newest edit', update=6002, provider_message=target, event='edited_message', date=1700000200)
    project(edit); project(telegram_payload('text', -100555, 'Stale edit', update=6001, provider_message=target, event='edited_message', date=1700000200))
    original.reload(); assert original.content == 'Newest edit' and original.edited_at
    assert frappe.db.count('Relay Message', {'relay_contact': contact.name}) == before_messages
    passed('Telegram edit replaces original content and rejects an older update from the same second')

    missing = reaction(6100, [{'type': 'emoji', 'emoji': '👍'}]); missing['payload']['message_reaction']['message_id'] = 9900
    deferred, _ = project(missing); assert deferred.projection_status == 'Uncategorized'
    _, later = project(telegram_payload('text', -100555, 'Late original', update=6101, provider_message=9900))
    with patch.object(frappe, 'enqueue'): projection.project(deferred.name)
    deferred.reload(); later.reload()
    assert deferred.projection_status == 'Projected' and messaging.object_value(later.reactions)['900555'][0]['emoji'] == '👍'
    before_messages += 1
    passed('reaction received before its message remains recoverable and is applied once the original arrives')

    wa = sources['WhatsApp', '919000000055']
    for identifier, emoji in [('wamid.react.1', '👍'), ('wamid.react.2', ''), ('wamid.react.2', '')]:
        reaction_value = {'entry': [{'changes': [{'value': {'messages': [{'id': identifier, 'from': wa.sender_endpoint,
            'type': 'reaction', 'timestamp': '1700000002', 'reaction': {'message_id': wa.provider_id, 'emoji': emoji}}]}}]}]}
        project(reaction_value)
    wa.reload(); assert messaging.object_value(wa.reactions)[wa.sender_endpoint] == []
    assert frappe.db.count('Relay Message', {'relay_contact': contact.name}) == before_messages
    passed('WhatsApp reaction set/clear/replay updates original message and does not create an unread turn')

    for (medium, address), source in stickers.items():
        frappe.set_user(actor)
        with patch.object(whatsapp, 'client', return_value=client): response = messaging.sticker(source.name)
        frappe.set_user('Administrator')
        assert response.get_data() == webp and response.headers['X-Content-Type-Options'] == 'nosniff'
        args = server.calls[-1]['arguments']; assert set(args) == {'file_id' if medium == 'Telegram' else 'media_id'}
    passed('private/group sticker proxy derives provider file IDs from readable messages and returns credential-free bounded media')

    for value in [telegram_payload('location', detail={'latitude': True, 'longitude': 0}),
                  whatsapp_payload('location', detail={'latitude': 91, 'longitude': 0})]:
        event, _ = project(value); assert event.projection_status == 'Failed'
    for kind, data in [('location', {'latitude': float('nan'), 'longitude': 0}),
                       ('text', {'text': 'Hello', 'chat_id': 999}), ('contact', {'contacts': []})]:
        before = len(server.calls)
        try: send(original, kind, data)
        except ValueError: pass
        else: raise AssertionError('Invalid typed data was accepted')
        assert len(server.calls) == before
    passed('malformed locations/contact cards and caller-supplied destination overrides are rejected before provider HTTP')

    endpoint = bindings['Telegram', '-100555']; endpoint.verified = 0; endpoint.save(); frappe.db.commit()
    before = len(server.calls)
    try: send(original, 'text', {'text': 'must not send'})
    except frappe.PermissionError: frappe.db.rollback()
    else: raise AssertionError('Revoked group binding was used')
    assert len(server.calls) == before
    endpoint.reload(); endpoint.verified = 1; endpoint.save(); frappe.db.commit()
    channel = channels['Telegram']; channel.enabled = 0; channel.save(); frappe.db.commit()
    try: send(original, 'location', {'latitude': 0, 'longitude': 0})
    except frappe.PermissionError: frappe.db.rollback()
    else: raise AssertionError('Disabled channel sent a message')
    assert len(server.calls) == before
    channel.reload(); channel.enabled = 1; channel.save(); frappe.db.commit()
    passed('revoked group binding and disabled channel deny typed sends without provider calls')

    # Only known incoming stickers can be reused; caller-supplied IDs never grant file access.
    before = len(server.calls)
    for data in ({'file_id': 'unknown-provider-file'}, {'sticker_message': stickers['WhatsApp', '919000000055'].name}):
        try: send(original, 'sticker', data)
        except ValueError: pass
        else: raise AssertionError('An unknown or cross-channel sticker was sent')
    assert len(server.calls) == before
    copied = send(original, 'sticker', {'sticker_message': stickers['Telegram', '-100555'].name})
    copied_doc = frappe.get_doc('Relay Message', copied['message'])
    copied_twice = send(copied_doc, 'sticker', {'file_id': 'tg-sticker-file'})
    assert copied_twice['status'] == 'Submitted'
    frappe.set_user(actor)
    with patch.object(whatsapp, 'client', return_value=client):
        assert messaging.sticker(copied_doc.name).get_data() == webp
    frappe.set_user('Administrator')
    passed('known incoming sticker reuse and outgoing copy proxy work; unknown IDs and cross-channel media are denied')

    for target_doctype in (business.doctype, 'Contact', 'Relay Channel'):
        permission_table = 'Custom DocPerm' if frappe.db.exists('Custom DocPerm', {'parent': target_doctype}) else 'DocPerm'
        permissions = frappe.get_all(permission_table, filters={'parent': target_doctype, 'role': ['in', frappe.get_roles(actor)]}, fields=['name', 'read'])
        assert permissions
        for permission in permissions: frappe.db.set_value(permission_table, permission.name, 'read', 0)
        frappe.clear_cache(doctype=target_doctype); frappe.db.commit()
        before = len(server.calls)
        try:
            frappe.set_user(actor)
            for operation in (lambda: api.messages(contact.name), lambda: messaging.send(original.name, 'text', {'text': 'forbidden'}, run_id + '-denied-' + target_doctype.replace(' ', '-')),
                              lambda: messaging.sticker(stickers['Telegram', '-100555'].name)):
                try:
                    with patch.object(whatsapp, 'client', return_value=client): operation()
                except frappe.PermissionError: frappe.db.rollback()
                else: raise AssertionError('Revoked ' + target_doctype + ' permission allowed conversation access')
            assert len(server.calls) == before
        finally:
            frappe.set_user('Administrator')
            for permission in permissions: frappe.db.set_value(permission_table, permission.name, 'read', permission.read)
            frappe.clear_cache(doctype=target_doctype); frappe.db.commit()
        passed('revoked ' + target_doctype + ' read permission denies history, typed send and sticker access')
    type_name = frappe.db.get_value('Relay Contact Type', {'business_doctype': business.doctype}, 'name')
    frappe.db.set_value('Relay Contact Type', type_name, 'enabled', 0); frappe.db.commit()
    try:
        frappe.set_user(actor)
        try: api.messages(contact.name)
        except frappe.PermissionError: frappe.db.rollback()
        else: raise AssertionError('Disabled contact type still exposed history')
        try: send(original, 'text', {'text': 'forbidden'})
        except frappe.PermissionError: frappe.db.rollback()
        else: raise AssertionError('Disabled contact type still sent a reply')
    finally:
        frappe.set_user('Administrator'); frappe.db.set_value('Relay Contact Type', type_name, 'enabled', 1); frappe.db.commit()
    passed('disabled configured business DocType denies both history and typed sends')

    server.fail = True; before = len(server.calls)
    result = send(original, 'text', {'text': 'uncertain'}, 'uncertain-request')
    assert result['status'] == 'Uncertain'
    assert send(original, 'text', {'text': 'uncertain'}, 'uncertain-request')['status'] == 'Uncertain'
    assert len(server.calls) == before + 2
    assert server.calls[-1]['name'] in ('channels.deliveries','whatsapp.deliveries'); server.fail = False
    passed('ambiguous typed send remains durable Uncertain and the same request key does not send twice')

    provider = frappe.get_doc(dict(doctype='Relay AI Provider', provider='OpenRouter', model='synthetic-model', api_key='unused-key', enabled=1)).insert()
    reply = frappe.get_doc(dict(doctype='Relay Canned Reply', title='Typed edit fence', channel='Telegram', language='English', body='Old answer', ai_enabled=1, published=1)).insert()
    frappe.get_doc(dict(doctype='Relay Automation Policy', channel=channels['Telegram'].name, provider=provider.name,
        execution_user=actor, enabled=1, mode='Automatic', allow_ticket=0, allow_reply=1, daily_limit=100,
        business_doctype=business.doctype, reply_ids=reply.name)).insert(); frappe.db.commit()
    value = telegram_payload('text', 900555); _, source = project(value)
    run_name = frappe.db.get_value('Relay Automation Run', {'message': source.name}, 'name')
    with patch.object(service, 'complete', return_value={'category': 'Query', 'brief': 'Original question', 'create_ticket': False, 'reply': reply.name, 'handoff': False}), patch.object(frappe, 'enqueue'):
        service.process(run_name)
    outbox = frappe.db.get_value('Relay Automation Outbox', {'run': run_name}, 'name'); assert outbox
    project(telegram_payload('text', 900555, 'Changed question', update=7000, provider_message=context_of(source)['message_id'], event='edited_message', date=1700000300))
    before = len(server.calls)
    with patch.object(whatsapp, 'client', return_value=client): service.dispatch(outbox)
    assert frappe.db.get_value('Relay Automation Outbox', outbox, 'status') == 'Cancelled' and len(server.calls) == before
    passed('editing a source question cancels an already-authorized stale AI reply')
    frappe.conf.relay_automation_enabled = 0
    disabled_before = frappe.db.count('Relay Automation Run')
    value = telegram_payload('text', -100555, 'Messaging without AI', update=8000)
    event, plain = project(value)
    assert event.projection_status == 'Projected' and plain and not frappe.db.exists('Relay Automation Run', {'message': plain.name})
    change = reaction(8001, [{'type': 'emoji', 'emoji': '👍'}]); change['payload']['message_reaction']['message_id'] = context_of(plain)['message_id']
    event, _ = project(change); plain.reload()
    assert event.projection_status == 'Projected' and messaging.object_value(plain.reactions)['900555'][0]['emoji'] == '👍'
    assert frappe.db.count('Relay Automation Run') == disabled_before
    frappe.conf.relay_automation_enabled = 1
    passed('AI-disabled site still projects inbound text and reactions without creating automation runs')
    # Slow receipts must be queried, never submitted twice; completion is idempotent.
    _, recovery_source = project(whatsapp_payload())
    queued_key = 'queued-' + str(next_id())
    with patch.object(client, 'call_tool', return_value={'delivery': {'state':'queued'}}) as submit:
        queued = send(recovery_source, 'text', {'text':'Queued reply'}, queued_key)
        assert queued['status'] == 'Queued' and submit.call_count == 1
        assert len(submit.call_args.args[1]['request_key']) == 64
    action_doc = frappe.get_doc('Relay Message Action', queued['action'])
    receipt = {'deliveries':[{'key':action_doc.request_key,'state':'submitted','result':{'messages':[{'id':'wamid.recovered.'+run_id}]}}]}
    with patch.object(client, 'call_tool', return_value=receipt) as lookup:
        completed = send(recovery_source, 'text', {'text':'Queued reply'}, queued_key)
        assert completed['status'] == 'Submitted' and completed['message']
        assert lookup.call_args.args[0] == 'whatsapp.deliveries'
        repeated = send(recovery_source, 'text', {'text':'Queued reply'}, queued_key)
        assert repeated == completed and lookup.call_count == 1
    assert frappe.db.count('Relay Message', {'source_key': action_doc.request_key}) == 1
    passed('queued WhatsApp receipt recovery queries without resending and creates one outgoing message')
    outgoing_receipt = frappe.get_doc('Relay Message', completed['message'])
    original_modified = outgoing_receipt.modified
    delivery_payload = {'entry': [{'changes': [{'value': {'statuses': [{
        'id': 'wamid.recovered.' + run_id, 'recipient_id': outgoing_receipt.sender_endpoint,
        'status': 'delivered', 'timestamp': str(int(time.time()))}]}}]}]}
    delivery_event, _ = project(delivery_payload)
    outgoing_receipt.reload()
    assert outgoing_receipt.status == 'Delivered'
    assert outgoing_receipt.modified == original_modified
    from relay_core import inbound
    import hashlib, hmac, types
    stamp=str(int(time.time()));secret='compact-fixture-secret-'+'x'*40
    compact={'account':account,'statuses':[{'event_id':777,'position':i,'message_id':outgoing_receipt.provider_id,
        'recipient':outgoing_receipt.sender_endpoint,'status':'read','timestamp':int(stamp)+i} for i in range(500)]}
    raw=json.dumps(compact).encode()
    signature=hmac.new(secret.encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    request=types.SimpleNamespace(get_data=lambda:raw,headers={'X-Relay-Timestamp':stamp,'X-Relay-Signature':signature})
    before_events=frappe.db.count('Relay Hub Event')
    with patch.object(frappe,'request',request), patch.object(inbound,'connection_value',side_effect=lambda key:secret if key=='relay_callback_secret' else account), patch.object(frappe,'enqueue'):
        assert inbound.receive_statuses()=={'accepted':500}
        assert inbound.receive_statuses()=={'accepted':500}
    assert frappe.db.count('Relay Hub Event')==before_events+1
    batch_key='statuses:'+hashlib.sha256(json.dumps(compact,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    batch_event=frappe.db.get_value('Relay Hub Event',{'event_key':batch_key},'name')
    with patch('relay_core.realtime.changed') as notified:
        projection.project(batch_event)
        assert notified.call_count==1
    outgoing_receipt.reload()
    assert outgoing_receipt.status=='Read' and outgoing_receipt.modified==original_modified
    passed('500 compact receipts authenticate, persist once on replay, coalesce realtime and preserve modified')

    assert delivery_event.projection_status == 'Projected'
    passed('provider delivery updates status without changing the message modified token')
    with patch.object(whatsapp,'client',return_value=client):
        endpoint=bindings['Telegram','900555']
        before=server.sent
        started=conversation_start.send(contact.name,endpoint.name,'text',{'text':'New conversation fixture'},'start-'+run_id)
        repeated=conversation_start.send(contact.name,endpoint.name,'text',{'text':'New conversation fixture'},'start-'+run_id)
        assert started==repeated and started['status']=='Submitted' and server.sent==before+1
        outgoing=frappe.get_doc('Relay Message',started['message'])
        assert outgoing.relay_contact==contact.name and outgoing.sender_endpoint=='900555' and not context_of(outgoing).get('reply_to_message_id')
        try:conversation_start.send(contact.name,endpoint.name,'text',{'text':'Changed intent'},'start-'+run_id)
        except ValueError:pass
        else:raise AssertionError('Changed request intent was accepted')
        endpoint.verified=0;endpoint.save();frappe.db.commit()
        try:conversation_start.send(contact.name,endpoint.name,'text',{'text':'New conversation fixture'},'start-'+run_id)
        except frappe.PermissionError:frappe.db.rollback()
        else:raise AssertionError('Revoked start endpoint was accepted')
        endpoint.reload();endpoint.verified=1;endpoint.save();frappe.db.commit()
        wa_endpoint=bindings['WhatsApp','919000000055']
        with patch.object(service_window,'status',return_value={'open':False,'expires_at':None}):
            try:conversation_start.send(contact.name,wa_endpoint.name,'text',{'text':'Closed window'},'closed-'+run_id)
            except frappe.ValidationError:frappe.db.rollback()
            else:raise AssertionError('Closed reply window admitted text')
            with patch.object(client,'call_tool',return_value={'delivery':{'state':'queued'}}) as submit:
                pending=conversation_start.send(contact.name,wa_endpoint.name,'template',{'name':'fixture_update','language':'en_US','components':[]},'start-template-'+run_id)
                assert pending['status']=='Queued' and submit.call_count==1
            action_doc=frappe.get_doc('Relay Message Action',pending['action'])
            receipt={'deliveries':[{'key':action_doc.request_key,'state':'submitted','result':{'messages':[{'id':'wamid.start.'+run_id}]}}]}
            with patch.object(client,'call_tool',return_value=receipt) as lookup:
                completed=conversation_start.send(contact.name,wa_endpoint.name,'template',{'name':'fixture_update','language':'en_US','components':[]},'start-template-'+run_id)
                assert completed['status']=='Submitted' and lookup.call_args.args[0]=='whatsapp.deliveries'
                assert frappe.db.count('Relay Message',{'source_key':action_doc.request_key})==1
    passed('conversation start has stable intent, verified destination, window gate and queued template recovery')
    with patch.object(client,'call_tool',side_effect=HubError('fixture rejection',{'provider':'Telegram','error':{'outcome_unknown':False}})):
        rejected=send(sources['Telegram','900555'],'text',{'text':'Retry fixture'},'retry-fixture')
    assert rejected['status']=='Rejected'
    frappe.set_user(actor)
    with patch.object(whatsapp,'client',return_value=client):
        listed=messaging.actions(contact.name)['items']
        assert any(row['name']==rejected['action'] and row['can_retry'] for row in listed)
        before=server.sent
        retried=messaging.retry(rejected['action']);again=messaging.retry(rejected['action'])
        assert retried==again and retried['status']=='Submitted' and server.sent==before+1
        try:messaging.retry(retried['action'])
        except frappe.PermissionError:frappe.db.rollback()
        else:raise AssertionError('Confirmed submission could be retried')
    frappe.set_user('Administrator')
    passed('confirmed rejection offers one idempotent retry; submitted and ambiguous actions cannot be blindly retried')
    from relay_core.flows import service as flows
    button_flow=flows.save({'title':'Button flow '+run_id,'command':'/button','template_button':'fixture_start','channel':channels['WhatsApp'].name,'execution_user':actor,'business_doctype':business.doctype,'enabled':0,'nodes':[{'id':'answer','kind':'input','variable':'answer','input_type':'text','text':'What do you need?'}]})
    flows.publish(button_flow['name']);flows.save({'enabled':1},button_flow['name']);frappe.db.set_value('Relay Contact',contact.name,'automation_paused',0);frappe.db.commit()
    button_event,button_message=project(whatsapp_payload('button',detail={'text':'Start support','payload':'fixture_start'}))
    assert button_event.projection_status=='Projected' and button_message.message_type=='text'
    assert messaging.object_value(button_message.provider_context)['original_message_type']=='button'
    queued=frappe.db.get_value('Relay Flow Event',{'message':button_message.name},'name');assert queued
    with patch.object(flows,'send') as prompt:
        flows.process(queued);flows.process(queued)
        assert prompt.call_count==1 and prompt.call_args.args[4]=='What do you need?'
    button_run=frappe.db.get_value('Relay Flow Event',queued,'run');assert frappe.db.get_value('Relay Flow Run',button_run,'status')=='Waiting'
    flows.cancel(button_run);flows.save({'enabled':0},button_flow['name']);frappe.db.commit()
    passed('projected WhatsApp template button queues exactly one flow prompt with retained payload provenance')
    form_event,form_message=project(whatsapp_payload('interactive',detail={'nfm_reply':{'body':'Feedback received','response_json':json.dumps({'flow_token':'private-fixture-token','rating':5,'comment':'Helpful'})}}))
    assert form_message.message_type=='text' and 'Helpful' in form_message.content and 'private-fixture-token' not in form_message.content
    form_data=json.loads(form_message.message_data) if isinstance(form_message.message_data,str) else form_message.message_data
    assert form_data['form_response']=={'rating':5,'comment':'Helpful'}
    passed('form submissions retain bounded readable answers and do not expose correlation tokens in conversation content')
    form={'id':'333','body':'Please share feedback','cta':'Open form','screen':'START','token':'fixture-form-'+run_id}
    with patch.object(client,'call_tool',return_value={'delivery':{'state':'queued'}}) as submit:
        pending=send(recovery_source,'flow',form,'form-'+run_id)
        assert pending['status']=='Queued' and submit.call_count==1
        args=submit.call_args.args[1];assert args['operation']=='messages.flow' and args['to']=='919000000055' and args['flow_screen']=='START'
    frappe.set_user(actor)
    restored=messaging.pending_messages(contact.name)
    restored_row=next(row for row in restored['items'] if row['action']==pending['action'])
    assert restored_row['status']=='Queued' and restored_row['content']==form['body']
    assert set(restored_row)=={'name','action','contact','scope','channel','provider_context','direction','content','creation','status','_pending','error'}
    assert restored_row['provider_context']=={'provider':'WhatsApp'}
    original_owner=frappe.db.get_value('Relay Message Action',pending['action'],'owner')
    frappe.db.set_value('Relay Message Action',pending['action'],'owner','unrelated@example.invalid')
    assert all(row['action']!=pending['action'] for row in messaging.pending_messages(contact.name)['items'])
    frappe.db.set_value('Relay Message Action',pending['action'],'owner',original_owner)
    frappe.set_user('Administrator')
    passed('durable pending replies restore safe preview and status only for their sender')
    action_doc=frappe.get_doc('Relay Message Action',pending['action'])
    receipt={'deliveries':[{'key':action_doc.request_key,'state':'submitted','result':{'messages':[{'id':'wamid.form.'+run_id}]}}]}
    with patch.object(client,'call_tool',return_value=receipt) as lookup:
        done=send(recovery_source,'flow',form,'form-'+run_id)
        assert done['status']=='Submitted' and lookup.call_args.args[0]=='whatsapp.deliveries'
    assert all(row['action']!=pending['action'] for row in messaging.pending_messages(contact.name)['items'])
    assert frappe.db.count('Relay Message',{'source_key':action_doc.request_key})==1
    assert frappe.get_doc('Relay Message',done['message']).content==form['body']
    try:send(sources['Telegram','900555'],'flow',form,'wrong-form-'+run_id)
    except ValueError:pass
    else:raise AssertionError('WhatsApp form was sent to Telegram')
    passed('form delivery keeps verified target, durable receipt recovery and one history record')
    for row in frappe.get_all('Relay Message',filters={'relay_contact':contact.name,'channel':channels['WhatsApp'].name,'direction':'Incoming'},pluck='name'):
        frappe.db.set_value('Relay Message',row,'sent_at',frappe.utils.add_to_date(frappe.utils.now_datetime(),hours=-25))
    frappe.db.commit()
    before=server.sent
    try:send(recovery_source,'text',{'text':'Expired reply'},'expired-reply')
    except frappe.ValidationError:frappe.db.rollback()
    else:raise AssertionError('Expired ordinary reply reached provider')
    assert server.sent==before
    assert send(recovery_source,'text',{'text':'Queued reply'},queued_key)['status']=='Submitted'
    passed('expired regular reply rejected before transport while confirmed request replay remains readable')
    from relay_core import delivery_receipts
    frappe.set_user('Administrator')
    frappe.reload_doc('relay_core','doctype','relay_delivery_receipt',force=True)
    frappe.db.add_index('Relay Delivery Receipt',['message','name'],'relay_participant_receipts')
    group_message=frappe.get_doc('Relay Message',frappe.db.get_value('Relay Message',{'channel':channels['WhatsApp'].name,'sender_endpoint':'types-group','direction':'Outgoing'},'name'))
    modified=group_message.modified
    def group_receipts(values):
        return {'entry':[{'changes':[{'value':{'statuses':[{'id':group_message.provider_id,'recipient_id':'types-group',
            'recipient_type':'group','recipient_participant_id':participant,'status':status,'timestamp':str(stamp)} for participant,status,stamp in values]}}]}]}
    project(group_receipts([('919000000001','read',200),('919000000002','delivered',200)]))
    result=delivery_receipts.directory(group_message.name)
    assert {row.participant:row.status for row in result['items']}=={'919000000001':'Read','919000000002':'Delivered'}
    project(group_receipts([('919000000001','delivered',100),('919000000002','delivered',200)]))
    assert len(delivery_receipts.directory(group_message.name)['items'])==2
    assert frappe.db.count('Relay Delivery Receipt',{'message':group_message.name})==2
    group_message.reload();assert group_message.status=='Read' and group_message.modified==modified
    project(group_receipts([(str(920000000000+i),'delivered',300) for i in range(52)]))
    first=delivery_receipts.directory(group_message.name);second=delivery_receipts.directory(group_message.name,after=first['next'])
    assert len(first['items'])==50 and len(second['items'])==4 and second['next'] is None
    assert len({row.name for row in first['items']+second['items']})==54
    compact_group={'account':account,'statuses':[{'event_id':888,'position':0,'message_id':group_message.provider_id,
        'recipient':'types-group','recipient_type':'group','participant':'919000000002','status':'read','timestamp':100}]}
    raw=json.dumps(compact_group).encode();stamp=str(int(time.time()))
    signature=hmac.new(secret.encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    request=types.SimpleNamespace(get_data=lambda:raw,headers={'X-Relay-Timestamp':stamp,'X-Relay-Signature':signature})
    with patch.object(frappe,'request',request),patch.object(inbound,'connection_value',side_effect=lambda key:secret if key=='relay_callback_secret' else account),patch.object(frappe,'enqueue'):
        assert inbound.receive_statuses()=={'accepted':1}
        assert inbound.receive_statuses()=={'accepted':1}
    key='statuses:'+hashlib.sha256(json.dumps(compact_group,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    name=frappe.db.get_value('Relay Hub Event',{'event_key':key},'name')
    assert json.loads(frappe.db.get_value('Relay Hub Event',name,'payload'))['entry'][0]['changes'][0]['value']['statuses'][0]['recipient_participant_id']=='919000000002'
    projection.project(name)
    assert frappe.db.get_value('Relay Hub Event',name,'projection_status')=='Projected'
    assert frappe.db.get_value('Relay Delivery Receipt',{'message':group_message.name,'participant':'919000000002'},'status')=='Read'
    assert frappe.db.count('Relay Delivery Receipt',{'message':group_message.name})==54
    endpoint_name=frappe.db.get_value('Relay Contact Endpoint',{'channel':channels['WhatsApp'].name,'endpoint':'types-group'},'name')
    frappe.db.set_value('Relay Contact Endpoint',endpoint_name,'verified',0)
    try:delivery_receipts.directory(group_message.name)
    except frappe.PermissionError:pass
    else:raise AssertionError('Revoked group binding exposed participant receipts')
    finally:frappe.db.set_value('Relay Contact Endpoint',endpoint_name,'verified',1)
    passed('group participant receipts are independent, deduplicated, non-regressing, bounded and permission checked')
    assert not server.errors, server.errors
    print(json.dumps({'result': 'passed', 'scenarios': len(checks), 'http_submissions': len(server.calls), 'account': account}), flush=True)
finally:
    server.shutdown(); server.server_close(); thread.join(timeout=3); frappe.destroy()
