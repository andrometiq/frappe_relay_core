"""Template header media that Relay sent from a local file is served from the site, not from Hub."""
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import frappe
from relay_core import attachments, campaign_media, conversation_start, document_sends, template_media
from site_file_limit import use_relay_file_limit

CAMPAIGN = 'Offer week'
VIDEO = {'file_url': '/private/files/offer.mp4', 'filename': 'offer.mp4'}
FIELDS = [{'key': 'header_media', 'component': 'header', 'media': 'video'}]


def setUpModule():
    use_relay_file_limit()


def video_message(**data):
    header = {'type': 'header', 'parameters': [{'type': 'video', 'video': {'id': '4465695997003884'}}]}
    return SimpleNamespace(name='RELAY-MSG-0000200013', message_type='text', channel='wa-1', sender_endpoint='918190986951',
        relay_contact='RC-1', source_key='bulk-db2d635f49efad7a-2', sent_at=None, creation='2026-10-30 10:30:00',
        message_data=json.dumps({'kind': 'text', 'text': 'Offer', 'template': {'name': 'offer', 'components': [header]}, **data}))


class CampaignHeaderTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix='.mp4')
        os.write(handle, b'\x00\x00\x00\x18ftypmp42 video')
        os.close(handle)
        self.addCleanup(os.remove, self.path)
        self.files = [VIDEO]
        self.row = {'destination': '918190986951', 'values': {'header_media': VIDEO}}
        self.hub = Mock()

        def get_value(doctype, filters, fields=None, as_dict=False):
            if doctype == 'Relay Campaign':
                mapping = {'header_attachment': {'mode': 'static' if len(self.files) == 1 else 'dynamic', 'files': self.files}}
                return SimpleNamespace(channel='wa-1', column_map=json.dumps(mapping), arguments=json.dumps({'fields': FIELDS}))
            if doctype == 'Relay Campaign Recipient':
                if filters != {'name': 'bulk-db2d635f49efad7a-2', 'campaign': CAMPAIGN}:
                    return None
                return SimpleNamespace(destination=self.row['destination'], arguments=json.dumps({'values': self.row['values']}))
            return 'FILE-1' if filters['file_url'].startswith('/private/files/') else None

        def content():
            with open(self.path, 'rb') as handle:
                return handle.read()

        file = SimpleNamespace(get_full_path=lambda: self.path, get_content=content)
        boundary = SimpleNamespace(db=SimpleNamespace(get_value=get_value), get_doc=lambda doctype, name: file)
        for fixture in (patch.object(campaign_media, 'frappe', boundary),
                        patch.object(attachments.whatsapp, 'client', return_value=self.hub)):
            fixture.start()
            self.addCleanup(fixture.stop)

    def read(self, source):
        with patch.object(attachments.frappe, 'db', SimpleNamespace(get_value=lambda *args: None)), \
                patch.object(attachments.messaging, 'readable_source', return_value=(source, SimpleNamespace(channel='WhatsApp'), {})):
            return attachments.read(source.name)

    def test_campaign_video_header_is_served_from_the_site(self):
        self.assertEqual(campaign_media.sent_header(video_message(), CAMPAIGN), ('offer.mp4', b'\x00\x00\x00\x18ftypmp42 video'))

    def test_campaign_file_missing_on_disk_is_unavailable(self):
        os.remove(self.path)
        self.addCleanup(lambda: open(self.path, 'wb').close())
        with self.assertRaises(campaign_media.DoesNotExistError):
            campaign_media.sent_header(video_message(), CAMPAIGN)

    def test_per_row_zip_file_is_served_from_the_site(self):
        own = {'file_url': '/private/files/918190986951.mp4', 'filename': '918190986951.mp4'}
        self.files = [{'file_url': '/private/files/919000000001.mp4', 'filename': '919000000001.mp4'}, own]
        self.row['values'] = {'header_media': own}
        self.assertEqual(campaign_media.sent_header(video_message(), CAMPAIGN)[0], '918190986951.mp4')

    def test_old_message_with_only_a_campaign_reference_is_served_without_hub(self):
        result = self.read(video_message(campaign=CAMPAIGN))
        self.assertEqual((result.status_code, result.content_type), (200, 'video/mp4'))
        self.assertTrue(result.data.startswith(b'\x00\x00\x00\x18ftyp'))
        self.hub.call_tool.assert_not_called()

    def test_file_of_another_campaign_is_denied_without_hub(self):
        self.row['values'] = {'header_media': {'file_url': '/private/files/other.mp4', 'filename': 'other.mp4'}}
        with self.assertRaises(campaign_media.PermissionError):
            self.read(video_message(campaign=CAMPAIGN))
        self.row['values'], self.row['destination'] = {'header_media': VIDEO}, '919000000001'
        with self.assertRaises(campaign_media.PermissionError):
            self.read(video_message(campaign=CAMPAIGN))
        self.hub.call_tool.assert_not_called()

    def test_message_outside_the_campaign_rows_falls_back_to_hub(self):
        source = video_message(campaign=CAMPAIGN)
        source.source_key = 'bulk-other-1'
        self.assertIsNone(campaign_media.sent_header(source, CAMPAIGN))


class OneToOneHeaderTests(unittest.TestCase):
    def setUp(self):
        self.file = SimpleNamespace(name='FILE-9', is_private=1, attached_to_doctype=None, file_name='offer.mp4', owner='staff@example.com',
                                    get_content=lambda: b'video', delete=Mock())
        self.cache = {template_media.UPLOADS + '9001': {'file': 'FILE-9', 'channel': 'wa-1'}}
        cache = SimpleNamespace(get_value=self.cache.get, delete_value=self.cache.pop)
        boundary = SimpleNamespace(cache=cache, get_doc=lambda doctype, name: self.file, session=SimpleNamespace(user='staff@example.com'),
                                   db=SimpleNamespace(get_value=lambda doctype, name, field: 'wa-1'))
        fixture = patch.object(template_media, 'frappe', boundary)
        fixture.start()
        self.addCleanup(fixture.stop)
        self.data = {'name': 'offer', 'language': 'en', 'components': [
            {'type': 'header', 'parameters': [{'type': 'video', 'video': {'id': '9001'}}]}]}

    def test_uploaded_header_moves_to_the_sent_message(self):
        with patch('relay_core.document_sends.keep_copy', return_value='RELAY-MSG-1') as keep_copy:
            self.assertEqual(template_media.keep_header({'action': 'ACT-1'}, 'template', self.data), 'RELAY-MSG-1')
        keep_copy.assert_called_once_with({'action': 'ACT-1'}, 'offer.mp4', b'video')
        self.file.delete.assert_called_once_with(ignore_permissions=True)
        self.assertEqual(self.cache, {})

    def test_whatsapp_operation_header_is_kept(self):
        with patch('relay_core.document_sends.keep_copy', return_value='RELAY-MSG-1') as keep_copy:
            template_media.keep_header({'action': 'ACT-2'}, 'whatsapp', {'operation': 'templates.send', 'arguments': self.data})
        keep_copy.assert_called_once_with({'action': 'ACT-2'}, 'offer.mp4', b'video')

    def test_upload_of_another_channel_user_attached_file_or_unknown_id_is_not_kept(self):
        with patch('relay_core.document_sends.keep_copy') as keep_copy:
            self.cache[template_media.UPLOADS + '9001']['channel'] = 'wa-2'
            self.assertIsNone(template_media.keep_header({'action': 'ACT-1'}, 'template', self.data))
            self.cache[template_media.UPLOADS + '9001']['channel'] = 'wa-1'
            self.file.owner = 'other@example.com'
            self.assertIsNone(template_media.keep_header({'action': 'ACT-1'}, 'template', self.data))
            self.file.owner = 'staff@example.com'
            self.file.attached_to_doctype = 'Relay Message'
            self.assertIsNone(template_media.keep_header({'action': 'ACT-1'}, 'template', self.data))
            self.data['components'][0]['parameters'][0]['video']['id'] = '9002'
            self.assertIsNone(template_media.keep_header({'action': 'ACT-1'}, 'template', self.data))
        keep_copy.assert_not_called()
        self.file.delete.assert_not_called()

    def test_upload_is_kept_when_no_message_took_the_copy(self):
        with patch('relay_core.document_sends.keep_copy', return_value=None):
            self.assertIsNone(template_media.keep_header({'action': 'ACT-1'}, 'template', self.data))
        self.file.delete.assert_not_called()
        self.assertIn(template_media.UPLOADS + '9001', self.cache)

    def test_missing_upload_file_raises_and_keeps_the_record(self):
        def gone():
            raise FileNotFoundError('offer.mp4')
        self.file.get_content = gone
        with patch('relay_core.document_sends.keep_copy') as keep_copy, self.assertRaises(FileNotFoundError):
            template_media.keep_header({'action': 'ACT-1'}, 'template', self.data)
        keep_copy.assert_not_called()
        self.file.delete.assert_not_called()

    def test_send_returns_the_hub_result_when_the_header_copy_fails(self):
        result = {'action': 'ACT-1', 'status': 'Sent'}
        lock = MagicMock()
        with patch.object(conversation_start, 'channel_endpoint', return_value='EP-1'), \
                patch.object(conversation_start, 'send_locked', return_value=result), \
                patch.object(conversation_start.frappe, 'cache', SimpleNamespace(lock=lambda *args, **kwargs: lock)), \
                patch.object(conversation_start.frappe, 'session', SimpleNamespace(user='staff@example.com')), \
                patch.object(conversation_start.frappe, 'log_error') as log_error, \
                patch.object(template_media, 'keep_header', side_effect=FileNotFoundError('offer.mp4')):
            self.assertIs(conversation_start.send('RC-1', 'EP-1', 'template', self.data, 'key-1'), result)
        log_error.assert_called_once()

    def test_kept_header_is_served_from_the_site(self):
        source = video_message(attachment='FILE-9', attachment_source='RELAY-MSG-0000200013')
        hub = Mock()
        kept = SimpleNamespace(file_name='offer.mp4')
        with patch.object(attachments.frappe, 'db', SimpleNamespace(get_value=lambda *args: None)), \
                patch.object(attachments.messaging, 'readable_source', return_value=(source, SimpleNamespace(channel='WhatsApp', name='wa-1'), {})), \
                patch.object(attachments, 'file_content', return_value=(kept, b'video')) as content, \
                patch.object(attachments.whatsapp, 'client', return_value=hub):
            result = attachments.read(source.name)
        content.assert_called_once_with('FILE-9', source)
        self.assertEqual((result.status_code, result.data), (200, b'video'))
        hub.call_tool.assert_not_called()


class KeepCopyTests(unittest.TestCase):
    def test_message_that_already_has_a_file_is_not_copied_again(self):
        values = {'Relay Message Action': 'request-1', 'Relay Message': 'RELAY-MSG-1'}

        def get_value(doctype, filters, field=None):
            return json.dumps({'attachment': 'FILE-1'}) if field == 'message_data' else values[doctype]

        with patch.object(document_sends.frappe, 'db', SimpleNamespace(get_value=get_value, set_value=Mock())) as db, \
                patch('frappe.utils.file_manager.save_file') as save_file:
            self.assertEqual(document_sends.keep_copy({'action': 'ACT-1'}, 'offer.mp4', b'video'), 'RELAY-MSG-1')
        save_file.assert_not_called()
        db.set_value.assert_not_called()


class UploadFileAccessTests(unittest.TestCase):
    def test_another_relay_user_cannot_read_the_uploaded_header(self):
        upload = SimpleNamespace(name='FILE-9', is_private=1, owner='sender@example.com',
                                 attached_to_doctype=None, attached_to_name=None)
        with patch('frappe.logger'):
            from frappe.core.doctype.file import file as file_doctype
        with patch.object(frappe.share, 'get_shared', return_value=[]):
            self.assertTrue(file_doctype.has_permission(upload, 'read', user='sender@example.com'))
            self.assertFalse(file_doctype.has_permission(upload, 'read', user='other.relay@example.com'))


if __name__ == '__main__':
    unittest.main()
