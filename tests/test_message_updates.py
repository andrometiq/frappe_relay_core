"""Delivery receipt ordering without provider calls or a database."""
import importlib.util
import json
import pathlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class DeliveryReceiptTests(unittest.TestCase):
    def setUp(self):
        self.doc = types.SimpleNamespace(relay_contact='contact', sender_endpoint='15551234567',
                                         direction='Outgoing', status='Pending')
        self.values = {}
        self.doc.get = lambda key: self.values.get(key)
        db = Mock()
        db.get_value.side_effect = lambda doctype, *args, **kwargs: 'contact' if doctype == 'Relay Contact Endpoint' else 'message'
        def save(doctype, name, values, **kwargs):
            self.values.update(values)
            for key, value in values.items(): setattr(self.doc, key, value)
        db.set_value.side_effect = save
        self.frappe = types.SimpleNamespace(db=db, get_doc=lambda *args: self.doc)
        spec = importlib.util.spec_from_file_location('updates_under_test', pathlib.Path(__file__).parents[1] / 'relay_core/message_updates.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe': self.frappe}): spec.loader.exec_module(self.module)
        self.notifications = Mock()
        realtime = patch.dict(sys.modules, {'relay_core.realtime': types.SimpleNamespace(changed=self.notifications, contact_changed=Mock())})
        realtime.start()
        self.addCleanup(realtime.stop)

    def receipt(self, status, timestamp):
        return {'entry': [{'changes': [{'value': {'statuses': [{'id': 'wamid.test',
            'recipient_id': '15551234567', 'status': status, 'timestamp': str(timestamp)}]}}]}]}

    def apply(self, state, timestamp):
        return self.module.apply_updates(self.receipt(state, timestamp), 'channel', 'event')

    def test_read_never_regresses_on_late_or_newer_delivery(self):
        self.apply('read', 20)
        self.apply('delivered', 10)
        self.apply('sent', 30)
        self.apply('failed', 40)
        self.assertEqual(self.doc.status, 'Read')
        self.assertEqual(self.frappe.db.set_value.call_count, 1)

    def test_delayed_stronger_receipt_is_not_lost(self):
        self.apply('sent', 30)
        self.apply('delivered', 20)
        self.assertEqual(self.doc.status, 'Delivered')
        self.apply('read', 10)
        self.assertEqual(self.doc.status, 'Read')
        self.apply('failed', 40)
        self.assertEqual(self.doc.status, 'Read')

    def test_old_sent_does_not_undo_later_failure(self):
        self.apply('failed', 30)
        self.apply('sent', 20)
        self.assertEqual(self.doc.status, 'Failed')
        self.apply('delivered', 10)
        self.assertEqual(self.doc.status, 'Delivered')

    def test_duplicate_and_failure_recovery(self):
        self.apply('sent', 10)
        self.apply('failed', 11)
        self.assertEqual(self.doc.status, 'Failed')
        self.apply('delivered', 12)
        self.apply('delivered', 12)
        self.assertEqual(self.doc.status, 'Delivered')
        self.assertEqual(self.frappe.db.set_value.call_count, 3)

    def test_delivery_preserves_modified_and_notifies_once_for_duplicate(self):
        self.apply('sent', 10)
        self.apply('sent', 10)
        self.assertEqual(self.frappe.db.set_value.call_count, 1)
        self.assertFalse(self.frappe.db.set_value.call_args.kwargs['update_modified'])
        self.notifications.assert_called_once_with(self.doc)

    def test_incoming_message_is_not_changed_by_receipt(self):
        self.doc.direction = 'Incoming'
        self.apply('read', 20)
        self.frappe.db.set_value.assert_not_called()

    def test_wrong_endpoint_cannot_mutate_message(self):
        self.doc.sender_endpoint = 'another-recipient'
        self.assertEqual(self.apply('read', 20), 'Uncategorized')
        self.frappe.db.set_value.assert_not_called()

    def test_negative_timestamp_rejected(self):
        with self.assertRaises(ValueError): self.apply('sent', -1)
        self.frappe.db.set_value.assert_not_called()
