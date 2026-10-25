import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from relay_core.config import load_env
from relay_core.hub import HubClient, HubError

class ConfigTests(unittest.TestCase):
    def test_whatsapp_rejection_text_is_safe_and_one_line(self):
        hub = HubClient('http://127.0.0.1:1234/mcp', 'x' * 64)
        hub.protocol = '2025-06-18'
        content = {'provider': 'WhatsApp', 'error': {'http_status': 400, 'code': 132001, 'title': 'Template name does not exist',
                   'message': 'Template winter_offer\nis not in en', 'access_token': 'never-expose'}}
        with patch.object(hub, '_request', return_value={'isError': True, 'structuredContent': content}):
            with self.assertRaises(HubError) as caught:
                hub.execute({'operation': 'templates.send'})
        self.assertEqual(str(caught.exception), 'WhatsApp rejected this request (code 132001): '
                         'Template name does not exist: Template winter_offer is not in en')
        self.assertEqual(caught.exception.metadata['error']['code'], 132001)
        self.assertNotIn('never-expose', json.dumps(caught.exception.metadata))
        with patch.object(hub, '_request', return_value={'isError': True, 'structuredContent': {'provider': 'WhatsApp', 'error': {}}}):
            with self.assertRaises(HubError) as caught:
                hub.execute({'operation': 'templates.send'})
        self.assertIn('Hub operation was rejected', str(caught.exception))

    def test_group_send_preserves_queue_receipt(self):
        hub=HubClient('http://127.0.0.1:1234/mcp','x'*64)
        receipt={'delivery':{'state':'queued','key':'group-test'}}
        with patch.object(hub,'call_tool',return_value=receipt) as call:
            self.assertEqual(hub.telegram_send(-100123,'hello',reply_to=4,message_thread_id=7,request_key='group-test'),receipt)
        call.assert_called_once_with('telegram.message',{'operation':'text','chat_id':-100123,'text':'hello','reply_to':4,'message_thread_id':7,'request_key':'group-test'})

    def test_provider_error_metadata_is_strictly_allowlisted(self):
        hub = HubClient('http://127.0.0.1:1234/mcp', 'x'*64); hub.protocol = '2025-06-18'
        metadata = {'provider': 'Telegram', 'secret': 'never-expose', 'error': {'http_status': 429,
            'code': 429, 'retry_after': 17, 'migrate_to_chat_id': -100123, 'outcome_unknown': False,
            'description': 'never-expose', 'token': 'never-expose'}}
        with patch.object(hub, '_request', return_value={'isError': True, 'structuredContent': metadata}):
            with self.assertRaises(HubError) as caught: hub.telegram_groups('info', chat_id=-1001)
        self.assertEqual(caught.exception.metadata, {'provider': 'Telegram', 'error': {
            'http_status': 429, 'code': 429, 'retry_after': 17, 'migrate_to_chat_id': -100123,
            'outcome_unknown': False}})
        self.assertNotIn('never-expose', str(caught.exception))

    def test_auth_denial_is_known_not_submitted(self):
        from urllib.error import HTTPError
        for code in (401,403):
            hub=HubClient('http://127.0.0.1:1234/mcp','x'*64)
            with patch.object(hub.opener,'open',side_effect=HTTPError(hub.url,code,'Denied',{},None)):
                with self.assertRaises(HubError) as caught:hub.initialize()
            self.assertEqual(caught.exception.metadata,{'provider':'Hub','error':{'http_status':code,'outcome_unknown':False}})
            self.assertIn('saved Hub API credential',str(caught.exception))

    def test_literal_values_and_environment_precedence(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/'.env'
            path.write_text("RELAY_HUB_URL='http://127.0.0.1:18081/mcp'\nRELAY_HUB_TOKEN=$(not-executed)\n")
            with patch.dict(os.environ, {'RELAY_HUB_URL':'https://hub.example/mcp'}):
                config = load_env(path)
            self.assertEqual(config['RELAY_HUB_TOKEN'], '$(not-executed)')
            self.assertEqual(config['RELAY_HUB_URL'], 'https://hub.example/mcp')
    def test_unknown_key_rejected(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'.env';path.write_text('PATH=bad')
            with self.assertRaises(ValueError):load_env(path)
    def test_insecure_and_credential_urls_rejected(self):
        for url in ['http://example.com/mcp','https://u:p@example.com/mcp','file:///mcp','https://example.com/mcp?token=x']:
            with self.assertRaises(ValueError):HubClient(url,'x'*64)
    def test_https_mount_prefix_supported(self):
        self.assertEqual(HubClient("https://hub.example/hub/mcp","x"*64).url,"https://hub.example/hub/mcp")
        with self.assertRaises(ValueError):HubClient("https://hub.example/../mcp","x"*64)
    def test_short_token_rejected(self):
        with self.assertRaises(ValueError):HubClient('http://127.0.0.1:18081/mcp','short')

@unittest.skipUnless(os.environ.get('RELAY_LIVE_TEST') == '1', 'opt-in local Hub integration')
class LiveHubTests(unittest.TestCase):
    def test_core_handshake_and_health(self):
        self.assertEqual(HubClient.from_env().health(), {'status':'ready','service':'relay_hub'})
    def test_wrong_token_rejected(self):
        from relay_core.hub import HubError
        good = HubClient.from_env()
        with self.assertRaisesRegex(HubError, r'\(401\)'):
            HubClient(good.url, 'invalid-'*8).health()

class MediaContractTests(unittest.TestCase):
    def test_general_media_and_stickers_use_distinct_tools(self):
        hub = HubClient('http://127.0.0.1:1234/mcp', 'x'*64)
        with patch.object(hub, 'call_tool', return_value={}) as call:
            hub.media('WhatsApp', '123')
            call.assert_called_with('whatsapp.attachment', {'media_id': '123'})
            hub.media('WhatsApp', '123', sticker=True)
            call.assert_called_with('whatsapp.media', {'media_id': '123'})
            hub.media('Telegram', 'received', sticker=True)
            call.assert_called_with('telegram.media', {'file_id': 'received'})

    def test_media_rejection_identifies_only_allowlisted_check(self):
        hub = HubClient('http://127.0.0.1:1234/mcp', 'x'*64)
        hub.protocol = '2025-06-18'
        for check in ('scope', 'ownership', 'content_type', 'size', 'provider_metadata', 'private-token'):
            result = {'isError': True, 'content': [{'type': 'text', 'text': 'private-token'}],
                      'structuredContent': {'provider': 'Hub', 'error': {'check': check, 'description': 'private-token'}}}
            with patch.object(hub, '_request', return_value=result):
                with self.assertRaises(HubError) as error: hub.media('WhatsApp', '123')
            if check != 'private-token':
                self.assertIn('rejected at ' + check, str(error.exception))
            self.assertNotIn('private-token', str(error.exception))
            self.assertNotIn('private-token', str(error.exception.metadata))

class RejectionDetailTests(unittest.TestCase):
    def test_tool_text_and_meta_user_fields_are_returned_redacted(self):
        hub = HubClient('http://127.0.0.1:1234/mcp', 'x'*64); hub.protocol = '2025-06-18'
        result = {'isError': True, 'content': [{'type': 'text', 'text': 'provider rejected operation\nBearer abc.def token=' + 'k'*12}],
                  'structuredContent': {'provider': 'WhatsApp', 'error': {'http_status': 400, 'error_user_title': 'Invalid parameter',
                  'error_user_msg': "Variables can't be at the start or end of the template. " + 'A'*40}}}
        with patch.object(hub, '_request', return_value=result):
            with self.assertRaises(HubError) as caught: hub.execute({'operation': 'templates.create'})
        self.assertEqual(caught.exception.detail, 'provider rejected operation [hidden] [hidden] · Invalid parameter · '
                         "Variables can't be at the start or end of the template. [hidden]")
        self.assertNotIn('abc.def', caught.exception.detail)
        self.assertNotIn('error_user_msg', str(caught.exception.metadata))


class MediaHTTPTests(unittest.TestCase):
    def test_media_http_transport_accepts_attachment_envelope_and_safe_denial(self):
        import base64
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        raw = b'fixture' * 1000000
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append(body)
                if body['method'] == 'initialize':
                    result = {'protocolVersion': '2025-06-18'}
                elif body['method'] == 'notifications/initialized':
                    self.send_response(202); self.end_headers(); return
                elif body['params']['arguments']['media_id'] == '999':
                    result = {'isError': True, 'structuredContent': {'provider': 'Hub', 'error': {'check': 'ownership'}},
                              'content': [{'type': 'text', 'text': 'private-provider-error'}]}
                else:
                    result = {'structuredContent': {'content_type': 'image/jpeg', 'filename': 'attachment.jpg',
                                                     'content_base64': base64.b64encode(raw).decode()}}
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps({'jsonrpc': '2.0', 'id': body['id'], 'result': result}).encode())
            def log_message(self, *_): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            hub = HubClient(f'http://127.0.0.1:{server.server_port}/mcp', 'x'*64)
            result = hub.media('WhatsApp', '123')
            self.assertEqual(base64.b64decode(result['content_base64']), raw)
            self.assertEqual(result['content_type'], 'image/jpeg')
            self.assertEqual(seen[-1]['params']['name'], 'whatsapp.attachment')
            with self.assertRaisesRegex(HubError, 'rejected at ownership') as caught:
                hub.media('WhatsApp', '999')
            self.assertNotIn('private-provider-error', str(caught.exception))
        finally:
            server.shutdown(); server.server_close(); thread.join()
