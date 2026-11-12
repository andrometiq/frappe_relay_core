"""WhatsApp stickers: the kept copy first, readable expiry states, and forwards that upload the kept copy."""
import base64
from functools import partial
import json
from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from relay_core import attachments, messaging
from relay_core.hub import HubClient, HubError

WEBP = b'RIFF\x10\x00\x00\x00WEBPVP8 fixture'
NOW = datetime(2026, 11, 12, 10, 0, 0)


def sticker_message(name='RELAY-MSG-0000000301', direction='Incoming', sent_at='2026-11-11 10:00:00', **data):
    return SimpleNamespace(name=name, direction=direction, message_type='sticker', relay_contact='RELAY-CON-1',
        sent_at=sent_at, creation=sent_at, sender_endpoint='910000000001', provider_id='wamid.fixture',
        message_data=json.dumps({'kind': 'sticker', 'media': {'id': '777', 'mime_type': 'image/webp'}, **data}))


class StickerTests(unittest.TestCase):
    def setUp(self):
        self.incoming = sticker_message()
        self.channel = SimpleNamespace(channel='WhatsApp', name='RELAY-CH-1', hub_channel=None)
        self.messages = {self.incoming.name: self.incoming}
        self.hub = Mock()
        self.hub.media = partial(HubClient.media, self.hub)
        self.hub.call_tool.return_value = {'content_base64': base64.b64encode(WEBP).decode(), 'content_type': 'image/webp'}
        self.kept = SimpleNamespace(file_name='sticker.webp')
        def reject(text, *args): raise ValueError(text, *args)
        for fixture in (patch.object(messaging, 'frappe', SimpleNamespace(db=SimpleNamespace(get_value=lambda *args: None))),
                        patch.object(messaging, 'readable_source', side_effect=lambda name: (self.messages[name], self.channel, {})),
                        patch.object(attachments, 'frappe', SimpleNamespace(throw=reject)),
                        patch.object(attachments, 'now_datetime', return_value=NOW),
                        patch.object(attachments, 'file_content', side_effect=lambda name, source: (self.kept, WEBP)),
                        patch.object(attachments.whatsapp, 'client', return_value=self.hub)):
            fixture.start(); self.addCleanup(fixture.stop)

    def outgoing(self):
        copy = sticker_message('RELAY-MSG-0000000302', 'Outgoing', sticker_source=self.incoming.name)
        self.messages[copy.name] = copy
        return copy

    def test_kept_copy_serves_the_sticker_and_its_forwards_without_hub(self):
        self.incoming.message_data = json.dumps({'kind': 'sticker', 'media': {'id': '777'}, 'attachment': 'FILE-1', 'attachment_source': self.incoming.name})
        for name in (self.incoming.name, self.outgoing().name):
            response = messaging.sticker(name)
            self.assertEqual((response.status_code, response.data, response.content_type), (200, WEBP, 'image/webp'))
        self.hub.call_tool.assert_not_called()

    def test_live_download_uses_the_sticker_tool_of_the_source(self):
        response = messaging.sticker(self.outgoing().name)
        self.assertEqual(response.data, WEBP)
        self.hub.call_tool.assert_called_once_with('whatsapp.media', {'media_id': '777'})

    def test_hub_rejections_become_gone_or_retry_and_bad_media_stays_an_error(self):
        self.hub.call_tool.side_effect = HubError('rejected', {'provider': 'Hub', 'error': {'check': 'provider_metadata'}})
        self.incoming.sent_at = self.incoming.creation = '2026-11-04 10:00:00'
        with self.assertRaises(ValueError) as gone: messaging.sticker(self.incoming.name)
        self.assertEqual(gone.exception.args, ('Media no longer available from WhatsApp', attachments.MediaGone))
        self.hub.call_tool.side_effect = HubError('rejected', {'provider': 'Hub', 'error': {'check': 'capacity'}})
        with self.assertRaises(ValueError) as busy: messaging.sticker(self.incoming.name)
        self.assertEqual(busy.exception.args[1], attachments.MediaRetry)
        self.hub.call_tool.side_effect = None
        self.hub.call_tool.return_value = {'content_base64': base64.b64encode(b'not a sticker').decode(), 'content_type': 'image/webp'}
        with self.assertRaises(ValueError) as invalid: messaging.sticker(self.incoming.name)
        self.assertEqual(invalid.exception.args, ('Sticker media does not match its declared type',))

    def prepared(self, source):
        _, arguments, content = messaging._prepare(source, self.channel, {'provider': 'WhatsApp', 'message_id': 'wamid.fixture'},
                                                    'sticker', {'sticker_message': self.incoming.name})
        return arguments, content

    def test_forward_uploads_the_kept_copy_instead_of_meta_media_id(self):
        self.incoming.message_data = json.dumps({'kind': 'sticker', 'media': {'id': '777'}, 'attachment': 'FILE-1', 'attachment_source': self.incoming.name})
        arguments, content = self.prepared(self.outgoing())
        self.assertEqual((arguments['content_base64'], arguments['mime_type'], arguments['media_type']), (base64.b64encode(WEBP).decode(), 'image/webp', 'sticker'))
        self.assertNotIn('media_id', arguments)
        self.assertEqual(content['sticker_source'], self.incoming.name)

    def test_forward_reuses_meta_media_id_only_while_meta_keeps_it(self):
        self.assertEqual(self.prepared(self.incoming)[0]['media_id'], '777')
        self.incoming.sent_at = self.incoming.creation = '2026-11-04 10:00:00'
        with self.assertRaisesRegex(ValueError, 'no longer keeps this sticker'):
            self.prepared(self.incoming)


if __name__ == '__main__':
    unittest.main()
