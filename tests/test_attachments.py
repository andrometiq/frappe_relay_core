"""Received WhatsApp media bounds and permission-checked response contract."""
import base64
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from relay_core import attachments
from relay_core.hub import MAX_WHATSAPP_DOWNLOAD_BYTES


class WhatsAppAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.source = SimpleNamespace(name='RELAY-MSG-0000000001', message_type='document',
            message_data=json.dumps({'kind': 'document', 'media': {'id': '123', 'filename': 'Local fixture.docx'}}))
        self.hub = Mock()
        def reject(message, *args): raise ValueError(message)
        boundary = SimpleNamespace(db=SimpleNamespace(get_value=lambda *args: None), throw=reject)
        for fixture in (patch.object(attachments, 'frappe', boundary),
                        patch.object(attachments.messaging, 'readable_source', return_value=(self.source, SimpleNamespace(channel='WhatsApp'), {})),
                        patch.object(attachments.whatsapp, 'client', return_value=self.hub)):
            fixture.start(); self.addCleanup(fixture.stop)

    def test_document_larger_than_upload_limit_downloads_with_filename(self):
        raw = b'fixture' * 1000000
        self.hub.call_tool.return_value = {'content_base64': base64.b64encode(raw).decode(),
            'content_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'filename': 'attachment.docx'}
        result = attachments.read(self.source.name)
        self.hub.call_tool.assert_called_once_with('whatsapp.attachment', {'media_id': '123'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data, raw)
        self.assertEqual(result.content_type, 'application/octet-stream')
        self.assertEqual(result.headers['Content-Disposition'], 'attachment; filename="Local_fixture.docx"')
        self.assertEqual(result.headers['Content-Length'], str(len(raw)))
        self.assertEqual(result.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(result.headers['Cache-Control'], 'private, no-store')

    def test_invalid_empty_and_oversized_media_are_rejected(self):
        for encoded in ('invalid!', '', base64.b64encode(b'x' * (MAX_WHATSAPP_DOWNLOAD_BYTES + 1)).decode()):
            self.hub.call_tool.return_value = {'content_base64': encoded}
            with self.assertRaises(ValueError): attachments.read(self.source.name)

    def test_permission_denial_does_not_contact_hub(self):
        with patch.object(attachments.messaging, 'readable_source', side_effect=PermissionError):
            with self.assertRaises(PermissionError): attachments.read(self.source.name)
        self.hub.call_tool.assert_not_called()
