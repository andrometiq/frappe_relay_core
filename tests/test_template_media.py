import base64
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from relay_core import conversation_start, template_media
from site_file_limit import use_relay_file_limit


def header(kind, media):
    return [{'type': 'header', 'parameters': [{'type': kind, kind: media}]}, {'type': 'body', 'parameters': []}]


def throw(message, exception=frappe.ValidationError):
    raise exception(message)


def setUpModule():
    use_relay_file_limit()
    patcher = patch.object(frappe, 'throw', side_effect=throw)
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


class FakeChannel(SimpleNamespace):
    def check_permission(self, permission):
        if self.denied:
            raise frappe.PermissionError('private channel')


class HeaderMediaTests(unittest.TestCase):
    def test_upload_id_and_public_https_link_pass(self):
        template_media.check_header(header('image', {'id': '1793109928314783'}))
        template_media.check_header(header('image', {'link': 'https://cdn.example.com/offer.png'}))
        template_media.check_header(header('document', {'link': 'https://cdn.example.com/bill.pdf', 'filename': 'bill.pdf'}))
        template_media.check_header(header('video', {'id': '42'}))

    def test_http_and_private_links_are_refused(self):
        for link in ('http://cdn.example.com/a.png', 'https://localhost/a.png', 'https://127.0.0.1/a.png',
                     'https://10.0.0.8/a.png', 'https://192.168.1.4/a.png', 'https://[::1]/a.png',
                     'https://169.254.169.254/latest', 'https://intranet/a.png', 'https://printer.local/a.png',
                     'https://relay.localhost/a.png', 'https://127.1/a.png', 'https://user:secret@cdn.example.com/a.png',
                     'ftp://cdn.example.com/a.png', 'javascript:alert(1)'):
            with self.subTest(link=link), self.assertRaises(frappe.ValidationError):
                template_media.check_header(header('image', {'link': link}))

    def test_header_needs_exactly_one_valid_source(self):
        for media in ({}, {'id': '1', 'link': 'https://cdn.example.com/a.png'}, {'id': 'abc'}, {'id': '../1'},
                      {'link': 'https://cdn.example.com/a.png', 'caption': 'x'}, 'https://cdn.example.com/a.png'):
            with self.subTest(media=media), self.assertRaises(frappe.ValidationError):
                template_media.check_header(header('image', media))
        with self.assertRaisesRegex(frappe.ValidationError, 'document header'):
            template_media.check_header(header('image', {'id': '1', 'filename': 'a.png'}))
        with self.assertRaisesRegex(frappe.ValidationError, 'plain file name'):
            template_media.check_header(header('document', {'id': '1', 'filename': '../bill.pdf'}))

    def test_text_header_and_body_parameters_are_untouched(self):
        template_media.check_header([{'type': 'header', 'parameters': [{'type': 'text', 'text': 'http://x'}]},
                                     {'type': 'body', 'parameters': [{'type': 'text', 'text': 'https://localhost'}]}])

    def test_template_start_refuses_a_private_header_link(self):
        source = frappe._dict(sender_endpoint='919811000004')
        channel = SimpleNamespace(channel='WhatsApp', name='yrp-1')
        data = {'name': 'offer', 'language': 'en_US', 'components': header('image', {'link': 'https://10.1.1.1/x.png'})}
        with patch.object(conversation_start, 'target', return_value=(source, channel, {'provider': 'WhatsApp'})):
            with self.assertRaisesRegex(frappe.ValidationError, 'public host'):
                conversation_start.prepared('RC-1', 'EP-1', 'template', data)


class HeaderUploadTests(unittest.TestCase):
    def setUp(self):
        self.channel = FakeChannel(name='yrp-1', channel='WhatsApp', enabled=1, account='yrp', denied=False)
        self.hub_upload = Mock(return_value='9001')
        self.save_file = Mock(return_value=SimpleNamespace(name='FILE-1'))
        self.cache = Mock()
        self.patches = [
            patch('frappe.utils.file_manager.save_file', self.save_file),
            patch.object(template_media.frappe, 'cache', self.cache),
            patch('relay_core.permissions.require_access'),
            patch.object(template_media.frappe, 'get_doc', return_value=self.channel),
            patch('relay_core.settings.value', return_value='yrp'),
            patch('relay_core.document_sends.upload', self.hub_upload),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def upload(self, filename='offer.png', raw=b'\x89PNG data', media_type='image'):
        return template_media.upload('yrp-1', media_type, filename, base64.b64encode(raw).decode())

    def test_upload_returns_the_hub_media_id(self):
        self.assertEqual(self.upload(), {'id': '9001', 'filename': 'offer.png', 'size': 9})
        self.hub_upload.assert_called_once_with(self.channel, 'offer.png', b'\x89PNG data', 'image', 'image/png')
        self.save_file.assert_called_once_with('offer.png', b'\x89PNG data', None, None, is_private=1)
        self.cache.set_value.assert_called_once_with(template_media.UPLOADS + '9001', {'file': 'FILE-1', 'channel': 'yrp-1'},
                                                     expires_in_sec=29 * 86400)
        self.assertEqual(self.upload('bill.pdf', b'%PDF', 'document')['id'], '9001')

    def test_upload_refuses_wrong_type_size_and_channel(self):
        with self.assertRaisesRegex(frappe.ValidationError, 'not accepted for this image'):
            self.upload('offer.gif')
        with self.assertRaisesRegex(frappe.ValidationError, 'not accepted for this video'):
            self.upload('offer.png', media_type='video')
        with patch('relay_core.file_limits.get_max_bytes', return_value=16):
            with self.assertRaisesRegex(frappe.ValidationError, 'at most 16 bytes'):
                self.upload(raw=b'\x89PNG' + b'x' * 13)
        with self.assertRaisesRegex(frappe.ValidationError, 'plain file name'):
            self.upload('../offer.png')
        self.channel.account = 'other'
        with self.assertRaises(frappe.PermissionError):
            self.upload()
        self.channel.account, self.channel.denied = 'yrp', True
        with self.assertRaises(frappe.PermissionError):
            self.upload()
        self.hub_upload.assert_not_called()
        self.save_file.assert_not_called()

    def test_upload_accepts_a_file_at_the_limit(self):
        with patch('relay_core.file_limits.get_max_bytes', return_value=16):
            self.assertEqual(self.upload(raw=b'\x89PNG' + b'x' * 12)['size'], 16)


if __name__ == '__main__':
    unittest.main()
