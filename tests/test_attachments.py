"""Received WhatsApp media bounds and permission-checked response contract."""
import base64
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from relay_core import attachments
from relay_core.hub import MAX_WHATSAPP_DOWNLOAD_BYTES, HubError


class WhatsAppAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.source = SimpleNamespace(name='RELAY-MSG-0000000001', message_type='document', sent_at='2026-10-20 10:00:00', creation='2026-10-20 10:00:01',
            message_data=json.dumps({'kind': 'document', 'media': {'id': '123', 'filename': 'Local fixture.docx'}}))
        self.hub = Mock()
        def reject(message, *args): raise ValueError(message, *args)
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

    def test_template_header_media_sent_by_id_downloads(self):
        self.source.message_type = 'text'
        self.source.message_data = json.dumps({'kind': 'text', 'text': 'Offer', 'template': {'name': 'offer', 'components': [
            {'type': 'header', 'parameters': [{'type': 'image', 'image': {'id': '456'}}]}]}})
        self.hub.call_tool.return_value = {'content_base64': base64.b64encode(b'png').decode(), 'content_type': 'image/png'}
        result = attachments.read(self.source.name, download=1)
        self.hub.call_tool.assert_called_once_with('whatsapp.attachment', {'media_id': '456'})
        self.assertEqual((result.status_code, result.data), (200, b'png'))
        self.source.message_data = json.dumps({'kind': 'text', 'text': 'Offer', 'template': {'name': 'offer', 'components': [
            {'type': 'body', 'parameters': [{'type': 'text', 'text': 'Ravi'}]}]}})
        with self.assertRaises(ValueError): attachments.read(self.source.name)

    def test_invalid_empty_and_oversized_media_are_rejected(self):
        for encoded in ('invalid!', '', base64.b64encode(b'x' * (MAX_WHATSAPP_DOWNLOAD_BYTES + 1)).decode()):
            self.hub.call_tool.return_value = {'content_base64': encoded}
            with self.assertRaises(ValueError): attachments.read(self.source.name)

    def test_permission_denial_does_not_contact_hub(self):
        with patch.object(attachments.messaging, 'readable_source', side_effect=PermissionError):
            with self.assertRaises(PermissionError): attachments.read(self.source.name)
        self.hub.call_tool.assert_not_called()

    def rejected(self, check, now):
        self.hub.call_tool.side_effect = HubError('rejected', {'provider': 'Hub', 'error': {'check': check}})
        with patch.object(attachments, 'now_datetime', return_value=attachments.get_datetime(now)):
            with self.assertRaises(ValueError) as failure: attachments.read(self.source.name)
        return failure.exception.args

    def test_hub_rejections_become_readable_reasons_with_retry_status(self):
        self.assertEqual(self.rejected('provider_metadata', '2026-11-25 10:00:00'), ('Media no longer available from WhatsApp', attachments.MediaGone))
        self.assertEqual(self.rejected('ownership', '2026-10-21 10:00:00'), ('Media no longer available from WhatsApp', attachments.MediaGone))
        self.assertEqual(self.rejected('provider_metadata', '2026-10-21 10:00:00'), ('WhatsApp did not return this media. Try again.', attachments.MediaRetry))
        self.assertEqual(self.rejected('capacity', '2026-10-21 10:00:00'), ('Media downloads are busy. Try again shortly.', attachments.MediaRetry))
        self.assertEqual(attachments.MediaGone.http_status_code, 410)
        self.assertEqual(attachments.MediaRetry.http_status_code, 503)


class KeptFileTests(unittest.TestCase):
    """A kept copy is read through its permission-checked source message, not through File sharing rules."""
    def setUp(self):
        self.source = SimpleNamespace(name='RELAY-MSG-0000000002')
        self.file = SimpleNamespace(is_private=1, attached_to_doctype='Relay Message', attached_to_name=self.source.name,
            file_name='Order.pdf', get_content=lambda: b'pdf', check_permission=Mock(side_effect=PermissionError('Only the uploader')))
        def reject(message, *args): raise ValueError(message, *args)
        fixture = patch.object(attachments, 'frappe', SimpleNamespace(get_doc=lambda doctype, name: self.file, throw=reject, PermissionError=PermissionError))
        fixture.start(); self.addCleanup(fixture.stop)

    def test_file_bound_to_the_readable_source_is_served_to_any_reader(self):
        self.assertEqual(attachments.file_content('FILE-1', self.source), (self.file, b'pdf'))

    def test_file_of_another_message_is_denied(self):
        self.file.attached_to_name = 'RELAY-MSG-0000000003'
        with self.assertRaises(ValueError): attachments.file_content('FILE-1', self.source)
        self.file.attached_to_name, self.file.is_private = self.source.name, 0
        with self.assertRaises(ValueError): attachments.file_content('FILE-1', self.source)

