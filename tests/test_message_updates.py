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
        from frappe import _dict
        self.doc = _dict(doctype='Relay Message', name='message', relay_contact='contact', sender_endpoint='15551234567',
                         direction='Outgoing', status='Pending', business_doctype='Customer',business_name='customer')
        self.values = {}
        self.pending = {}
        db = Mock()
        def save(doctype, name, values, **kwargs):
            self.values.update(values)
            self.doc.update(values)
        def bulk(doctype, values, **kwargs):
            for name, fields in values.items():
                if doctype == 'Relay Message': save(doctype,name,fields,**kwargs)
                else:self.pending[name].update(fields)
        def insert(doctype, fields, values):
            for row in values:
                record=_dict(zip(fields,row));self.pending[record.name]=record
        db.set_value.side_effect=save
        db.bulk_update.side_effect=bulk
        db.bulk_insert.side_effect=insert
        db.get_value.side_effect=lambda dt,key,*a,**kw:self.pending.get(key)
        self.query=Mock()
        for method in ('select','where','orderby','for_update'):getattr(self.query,method).return_value=self.query
        table=Mock();table.provider_message_key.isin.return_value=True
        self.frappe = types.SimpleNamespace(db=db, get_all=lambda *a,**kw:list(self.pending.values()),
            qb=types.SimpleNamespace(DocType=lambda dt:table,from_=lambda dt:self.query),
            utils=types.SimpleNamespace(now_datetime=lambda:'2026-10-24 10:00:00'), session=types.SimpleNamespace(user='fixture'))
        def load(name, path):
            spec=importlib.util.spec_from_file_location(name,path)
            module=importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules,frappe=self.frappe):spec.loader.exec_module(module)
            return module
        self.module=load('updates_under_test','relay_core/message_updates.py')
        self.batch=load('receipts_under_test','relay_core/whatsapp_receipts.py')
        self.doc.provider_message_key=self.module.provider_key('channel','15551234567','wamid.test')
        self.query.run.return_value=[self.doc]
        self.batch.lock_endpoints=Mock(return_value={'15551234567':'contact'})
        self.notifications = Mock()
        modules=patch.dict(sys.modules, {'relay_core.realtime':types.SimpleNamespace(changed=self.notifications,contact_changed=Mock()),
                                       'relay_core.whatsapp_receipts':self.batch})
        modules.start();self.addCleanup(modules.stop)

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
        self.assertEqual(self.frappe.db.bulk_update.call_count, 1)

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
        self.assertEqual(self.frappe.db.bulk_update.call_count, 3)

    def test_delivery_preserves_modified_and_notifies_once_for_duplicate(self):
        self.apply('sent', 10)
        self.apply('sent', 10)
        self.assertEqual(self.frappe.db.bulk_update.call_count, 1)
        self.assertFalse(self.frappe.db.bulk_update.call_args.kwargs['update_modified'])
        self.notifications.assert_called_once_with(self.doc)

    def test_incoming_message_is_not_changed_by_receipt(self):
        self.doc.direction = 'Incoming'
        self.apply('read', 20)
        self.frappe.db.bulk_update.assert_not_called()

    def test_wrong_endpoint_cannot_mutate_message(self):
        self.doc.sender_endpoint = 'another-recipient'
        self.assertEqual(self.apply('read', 20), 'Uncategorized')
        self.frappe.db.bulk_update.assert_not_called()

    def test_negative_timestamp_rejected(self):
        with self.assertRaises(ValueError): self.apply('sent', -1)
        self.frappe.db.bulk_update.assert_not_called()

    def test_500_receipts_for_one_message_write_once(self):
        statuses=[]
        for number in range(500):
            statuses.extend(self.receipt('delivered' if number % 2 else 'sent',number)['entry'][0]['changes'][0]['value']['statuses'])
        result=self.module.apply_updates({'entry':[{'changes':[{'value':{'statuses':statuses}}]}]},'channel','event')
        self.assertEqual(result,'Projected')
        self.assertEqual(self.doc.status,'Delivered')
        self.frappe.db.bulk_update.assert_called_once()
        self.query.run.assert_called_once()
        self.batch.lock_endpoints.assert_called_once()
        self.notifications.assert_called_once()

    def test_early_receipt_is_durable_and_applied_when_message_exists(self):
        self.query.run.return_value=[]
        self.assertEqual(self.apply('read',20),'Projected')
        self.assertEqual(len(self.pending),1)
        self.assertEqual(self.doc.status,'Pending')
        self.batch.apply_pending(self.doc)
        self.assertEqual(self.doc.status,'Read')
        self.query.run.return_value=[self.doc]
        self.apply('sent',30)
        self.assertEqual(self.doc.status,'Read')

    def test_collapse_is_independent_of_batch_order(self):
        rows=[{'destination':'one','target':'id','status':state,'timestamp':stamp} for state,stamp in [('Sent',30),('Failed',40),('Read',10),('Delivered',20)]]
        self.assertEqual(self.batch.collapse(rows),self.batch.collapse(list(reversed(rows))))
        self.assertEqual(self.batch.collapse(rows)[0]['status'],'Read')

    def test_unverified_endpoint_keeps_event_unresolved(self):
        self.batch.lock_endpoints.return_value={}
        self.assertEqual(self.apply('read',20),'Uncategorized')
        self.frappe.db.bulk_update.assert_not_called()
        self.frappe.db.bulk_insert.assert_not_called()

    def test_500_distinct_messages_share_batched_lookup_and_write(self):
        from frappe import _dict
        docs=[_dict(self.doc,name='message-'+str(i),provider_message_key=self.module.provider_key('channel','15551234567','wamid.'+str(i))) for i in range(500)]
        self.query.run.return_value=docs
        statuses=[dict(self.receipt('read',20)['entry'][0]['changes'][0]['value']['statuses'][0],id='wamid.'+str(i)) for i in range(500)]
        self.module.apply_updates({'entry':[{'changes':[{'value':{'statuses':statuses}}]}]},'channel','event')
        self.query.run.assert_called_once()
        self.frappe.db.bulk_update.assert_called_once()
        writes=self.frappe.db.bulk_update.call_args.args[1]
        self.assertEqual(len(writes),500)
        self.assertTrue(all(row['status']=='Read' for row in writes.values()))
        self.notifications.assert_called_once()
