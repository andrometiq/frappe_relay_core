"""Shared Telegram/email journal contracts independent of the provider transport."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core import messaging
import frappe


class NotificationRetryTests(unittest.TestCase):
    def test_email_and_telegram_notifications_cannot_lose_provenance_on_retry(self):
        for operation,payload in [('email',{'email_values':{'to':['a@example.test']}}),
                                  ('text',{'group':{'chat_id':123,'text':'Ticket update'}})]:
            action=_dict(name='action',owner='sender',status='Rejected',operation=operation,
                payload=json.dumps(dict(payload,notification='notice')),check_permission=Mock())
            with self.subTest(operation=operation),patch.object(messaging,'require_access'), \
                 patch.object(frappe,'get_doc',return_value=action),patch.object(frappe,'session',_dict(user='sender')), \
                 patch.object(frappe,'throw',side_effect=frappe.PermissionError), \
                 patch('relay_core.email.send') as email_send,patch('relay_core.telegram.send') as telegram_send:
                with self.assertRaises(frappe.PermissionError):messaging.retry(action.name)
                email_send.assert_not_called();telegram_send.assert_not_called()


class ChannelReceiptTests(unittest.TestCase):
    def test_pending_receipts_are_queued_without_provider_acceptance(self):
        for state in ('queued', 'dispatching', 'submitting'):
            self.assertEqual(messaging.receipt_status({'pending':True,'state':state}), 'Queued')
            self.assertEqual(messaging.receipt_status({'delivery':{'state':state}}), 'Queued')
        self.assertEqual(messaging.receipt_status({'pending':True}), 'Uncertain')

    def test_callback_order_is_monotonic(self):
        action = _dict(status='Uncertain', result=json.dumps({'_relay_status_id':20}))
        for receipt in ({'_relay_status_id':19}, {'_relay_status_id':20}, {'pending':True,'state':'queued'}):
            self.assertTrue(messaging.stale_receipt(action, receipt))
        self.assertFalse(messaging.stale_receipt(action, {'_relay_status_id':21}))
        self.assertTrue(messaging.stale_receipt(action, {'message_id':'invalid'}))
        self.assertFalse(messaging.stale_receipt(action, {'message_id':'verified'},accepted=True))
        action.status='Submitted'
        self.assertTrue(messaging.stale_receipt(action, {'_relay_status_id':22,'state':'rejected'}))

    def test_receipt_lookup_requires_the_original_key_and_channel(self):
        action = _dict(request_key='original-key')
        hub = Mock()
        with patch.object(messaging.whatsapp,'client',return_value=hub):
            for medium,operation in [('Telegram','telegram.message'),('Email','email.send')]:
                channel = _dict(channel=medium)
                hub.call_tool.return_value={'deliveries':[{'key':'original-key','operation':operation,'state':'queued'}]}
                self.assertEqual(messaging.receipt_status(messaging.delivery_receipt(action,channel)), 'Queued')
                hub.call_tool.assert_called_with('channels.deliveries', {'request_key':'original-key'})
                for rows in (None,[{'key':'wrong','operation':operation}], [{'key':'original-key','operation':'other'}]):
                    hub.call_tool.return_value={'deliveries':rows}
                    with self.assertRaises(ValueError):messaging.delivery_receipt(action,channel)


class TelegramAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.payload={'tool':'telegram.message','arguments':{'operation':'text','chat_id':123,'text':'Quantity 25'},
            'content':{'kind':'text','text':'Quantity 25'},'business':['Customer','original']}
        self.action=_dict(name='action',status='Dispatching',operation='text',request_key='original-key',
            payload=json.dumps(self.payload),source_message='source',check_permission=Mock())
        self.source=_dict(name='source',business_doctype='Customer',business_name='original')
        self.hub=Mock();self.finish=Mock(return_value={'status':'Queued'})
        for boundary in (patch.object(messaging,'frappe',SimpleNamespace(get_doc=Mock(return_value=self.action), PermissionError=PermissionError, DoesNotExistError=LookupError)),
                         patch.object(messaging,'readable_source',return_value=(self.source,_dict(channel='Telegram'),{})),
                         patch.object(messaging.whatsapp,'client',return_value=self.hub),patch.object(messaging,'finish',self.finish)):
            boundary.start();self.addCleanup(boundary.stop)

    def test_empty_lookup_recovers_dispatching_with_the_original_key(self):
        self.hub.call_tool.side_effect=[{'deliveries':[]},{'state':'queued','pending':True}]
        self.assertEqual(messaging.reconcile('action'),{'status':'Queued'})
        self.assertEqual(self.hub.call_tool.call_args.args,('telegram.message',dict(self.payload['arguments'],request_key='original-key')))

    def test_business_change_refuses_missing_intent_recovery(self):
        self.source.business_name='different'
        self.hub.call_tool.return_value={'deliveries':[]}
        with self.assertRaises(ValueError):messaging.reconcile('action')
        self.hub.call_tool.assert_called_once_with('channels.deliveries',{'request_key':'original-key'})
        self.finish.assert_not_called()

    def test_uncertain_missing_intent_is_not_resubmitted(self):
        self.action.status='Uncertain';self.hub.call_tool.return_value={'deliveries':[]}
        with self.assertRaises(ValueError):messaging.reconcile('action')
        self.hub.call_tool.assert_called_once_with('channels.deliveries',{'request_key':'original-key'})


class AutomatedRetryTests(unittest.TestCase):
    def test_ai_and_business_events_cannot_be_retried_without_provenance(self):
        for operation in ('text', 'email'):
            for provenance in ('automation_run', 'flow_run', 'business_event', 'notification', 'email_values'):
                action = _dict(name='action', owner='sender', status='Rejected', operation=operation,
                    payload=json.dumps({'email_values':{'to':['a@example.invalid']},
                        provenance: {'auto_submitted':1} if provenance=='email_values' else 'origin'}),
                    check_permission=Mock())
                with self.subTest(operation=operation, provenance=provenance), \
                        patch.object(messaging, 'require_access'), patch.object(frappe, 'get_doc', return_value=action), \
                        patch.object(frappe, 'session', _dict(user='sender')), \
                        patch.object(frappe, 'throw', side_effect=frappe.PermissionError), \
                        patch.object(messaging, 'send') as send, patch('relay_core.email.send') as email_send:
                    with self.assertRaises(frappe.PermissionError):
                        messaging.retry(action.name)
                    send.assert_not_called()
                    email_send.assert_not_called()


class EmailDeliveryEvidenceTests(unittest.TestCase):
    def test_dsn_waits_for_submission_and_rejects_mismatched_recipient_or_message(self):
        from relay_core import channel_statuses
        action = _dict(name='action', operation='email', status='Queued', outbound_message=None,
            payload=json.dumps({'email_values':{'to':['a@example.invalid']}}))
        row = dict(id=1, receipt=dict(message_id='<id@example.invalid>', recipient='a@example.invalid',
                                    delivery_status='bounced', status_code='5.1.1'))
        self.assertFalse(channel_statuses.apply_email_evidence(action, row))
        row['receipt']['recipient'] = 'other@example.invalid'
        with self.assertRaisesRegex(ValueError, 'recipient mismatch'):
            channel_statuses.apply_email_evidence(action, row)
        row['receipt']['recipient'] = 'a@example.invalid'
        action.outbound_message = 'message'
        message = _dict(name='message', provider_context=json.dumps({'provider':'Email','message_id':'<other@example.invalid>'}))
        with patch.object(frappe, 'get_doc', return_value=message):
            with self.assertRaisesRegex(ValueError, 'message mismatch'):
                channel_statuses.apply_email_evidence(action, row)
