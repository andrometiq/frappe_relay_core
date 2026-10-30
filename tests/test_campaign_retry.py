"""Delivery failure reasons and retrying the failed rows of a completed campaign. Persistence and Hub are local doubles."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import frappe
from frappe import _dict
from relay_core import bulk_campaigns as bulk

USER = 'local-campaign-manager@example.invalid'


class DeliveryReasonTests(unittest.TestCase):
    def test_meta_codes_become_delivery_reasons_without_provider_text(self):
        reason = bulk.friendly_reason('Meta error 131026: Message undeliverable: secret provider detail')
        self.assertEqual(reason, bulk.DELIVERY_REASONS[131026])
        self.assertTrue(reason.startswith('WhatsApp could not deliver this message to this number'))
        self.assertNotIn('secret', reason)

    def test_unknown_meta_code_names_the_code(self):
        self.assertEqual(bulk.friendly_reason('Meta error 999999: secret'),
                         'WhatsApp could not deliver this message (WhatsApp error 999999)')

    def test_validation_reasons_are_unchanged(self):
        self.assertEqual(bulk.friendly_reason('Duplicate row'), 'Duplicate row')
        self.assertIn('could not be processed', bulk.friendly_reason('Hub refused this row: secret'))


class RetryFailedTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock(exists=Mock(return_value=True))
        self.fake = SimpleNamespace(db=self.db, cache=SimpleNamespace(lock=MagicMock(), delete_value=Mock()),
                                    session=_dict(user=USER), utils=SimpleNamespace(now=lambda: '2026-10-30 12:00:00'))
        self.enterContext(patch.object(bulk, 'frappe', self.fake))
        self.doc = _dict(name='Local retry', status='Completed', reply_window_hours=72, finished_at='2026-10-30 11:00:00',
                         arguments=json.dumps({'fields': [], 'phases': [{'phase': 'Retrying failed'}]}))
        self.enterContext(patch.object(bulk, 'bulk', return_value=self.doc))
        self.ready = self.enterContext(patch.object(bulk, 'check_ready', return_value={'media_id': '42'}))
        self.save = self.enterContext(patch.object(bulk, 'internal_save'))
        self.enqueue = self.enterContext(patch.object(bulk, 'enqueue'))
        self.enterContext(patch.object(bulk, 'read', side_effect=lambda name: {'name': name}))
        self.enterContext(patch('relay_core.bulk_updates.open_reply_window'))
        self.enterContext(patch('relay_core.bulk_updates.changed'))

    def test_failed_rows_go_back_to_pending_under_new_keys_and_send_again(self):
        self.assertEqual(bulk.retry_failed(self.doc.name), {'name': self.doc.name})
        sql, values = self.db.sql.call_args.args
        self.assertIn("SET status='Pending'", sql)
        self.assertIn("request_key=CONCAT(recipient_key, %s)", sql)
        self.assertIn("status='Failed'", sql)
        self.assertEqual(values, ('-retry2', self.doc.name))
        self.assertEqual((self.doc.status, self.doc.finished_at, self.doc.media_id), ('Running', None, '42'))
        self.assertEqual(json.loads(self.doc.arguments)['phases'][-1]['phase'], 'Retrying failed')
        self.enqueue.assert_called_once_with('send_job', self.doc.name, slot='control')
        self.fake.cache.lock.assert_called_once_with('relay-bulk-control:' + self.doc.name, timeout=30)
        self.assertEqual(self.db.commit.call_count, 2)  # Fresh snapshot inside the lock, then the retry.

    def test_repeated_call_or_no_failed_rows_changes_nothing(self):
        for status, failed in (('Running', True), ('Completed', False), ('Draft', True)):
            self.doc.status, self.db.exists.return_value = status, failed
            with self.subTest(status=status, failed=failed):
                bulk.retry_failed(self.doc.name)
        self.db.sql.assert_not_called()
        self.ready.assert_not_called()
        self.enqueue.assert_not_called()
        self.save.assert_not_called()

    def test_retry_started_by_another_request_inside_the_lock_is_not_repeated(self):
        def started(*args, **kwargs):
            self.doc.status = 'Running'
            return MagicMock()
        self.fake.cache.lock = Mock(side_effect=started)
        bulk.retry_failed(self.doc.name)
        self.db.sql.assert_not_called()
        self.enqueue.assert_not_called()


class RetryPermissionTests(unittest.TestCase):
    def test_denied_before_any_row_changes(self):
        with patch.object(bulk, 'require_access', side_effect=frappe.PermissionError), \
                patch.object(bulk, 'frappe', SimpleNamespace(db=Mock())) as fake:
            with self.assertRaises(frappe.PermissionError):
                bulk.retry_failed('denied')
        fake.db.sql.assert_not_called()
