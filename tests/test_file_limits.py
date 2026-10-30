import base64
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from relay_core import attachments, bulk_campaigns, file_limits

MB = 1024 * 1024


def throw(message, exception=frappe.ValidationError):
    raise exception(message)


class FileLimitTests(unittest.TestCase):
    def limit(self, site_file_bytes, request_bytes=None):
        conf = frappe._dict(max_file_size=request_bytes) if request_bytes else frappe._dict()
        site = SimpleNamespace(get_max_file_size=lambda: site_file_bytes)
        with patch.dict(sys.modules, {'frappe.core.api.file': site}), patch.object(file_limits.frappe, 'conf', conf):
            return file_limits.get_max_bytes()

    def test_site_file_size_lowers_the_relay_limit_and_never_raises_it(self):
        self.assertEqual(self.limit(200 * MB), file_limits.MAX_BYTES)
        self.assertEqual(self.limit(3 * MB), 3 * MB)

    def test_a_base64_request_body_must_fit_in_the_site_request_limit(self):
        request_bytes = 8 * MB
        limit = self.limit(200 * MB, request_bytes)
        self.assertLess(limit, request_bytes)
        self.assertLessEqual(file_limits.encoded_length(limit), request_bytes - file_limits.REQUEST_OVERHEAD_BYTES)

    def test_whatsapp_kind_limits_apply_only_where_meta_accepts_less(self):
        with patch.object(file_limits, 'get_max_bytes', return_value=10 * MB):
            photo = file_limits.get_media_max_bytes('WhatsApp', 'photo')
            self.assertLess(photo, 10 * MB)
            self.assertEqual(file_limits.get_media_max_bytes('WhatsApp', 'video'), 10 * MB)
            self.assertEqual(file_limits.get_media_max_bytes('Email', 'document'), 10 * MB)
        with patch.object(file_limits, 'get_max_bytes', return_value=photo - 1):
            self.assertEqual(file_limits.get_media_max_bytes('WhatsApp', 'photo'), photo - 1)

    def test_size_error_at_the_limit_and_one_byte_above(self):
        self.assertEqual(file_limits.size_error(10 * MB, 10 * MB), '')
        self.assertEqual(file_limits.size_error(10 * MB + 1, 10 * MB), 'The file must be at most 10 MB')
        self.assertEqual(file_limits.size_error(0, 10 * MB, 'Header attachment'), 'Header attachment is empty')
        self.assertEqual(file_limits.size_error(501 * 1024, 500 * 1024), 'The file must be at most 500 KB')


class AttachmentUploadLimitTests(unittest.TestCase):
    def setUp(self):
        source = frappe._dict(name='MSG-1')
        channel = frappe._dict(channel='WhatsApp')
        for item in (patch.object(attachments.messaging, 'readable_source', return_value=(source, channel, {})),
                     patch.object(file_limits, 'get_max_bytes', return_value=12),
                     patch.object(attachments.frappe, 'throw', side_effect=throw)):
            item.start()
            self.addCleanup(item.stop)
        saved = patch('frappe.utils.file_manager.save_file', return_value=frappe._dict(name='FILE-1', file_name='a.pdf'))
        self.save = saved.start()
        self.addCleanup(saved.stop)

    def upload(self, size):
        return attachments.upload('MSG-1', 'a.pdf', base64.b64encode(b'x' * size).decode())

    def test_upload_accepts_the_limit_and_refuses_one_byte_more(self):
        self.assertEqual(self.upload(12)['size'], 12)
        for size in (13, 15):
            with self.subTest(size=size), self.assertRaisesRegex(frappe.ValidationError, 'at most 12 bytes'):
                self.upload(size)
        self.assertEqual(self.save.call_count, 1)


class CampaignReasonTests(unittest.TestCase):
    def test_header_size_reasons_reach_the_campaign_error_sheet(self):
        for reason in ('Header attachment is empty', 'Header attachment must be at most 10 MB', 'Header attachment must be at most 500 KB'):
            self.assertEqual(bulk_campaigns.friendly_reason(reason), reason)
        self.assertNotEqual(bulk_campaigns.friendly_reason('Header attachment must be at most 10 MB at /private/x'),
                            'Header attachment must be at most 10 MB at /private/x')
