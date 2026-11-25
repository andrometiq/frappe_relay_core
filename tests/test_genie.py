import hashlib
import hmac
import json
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import requests
from frappe import _dict
from relay_core import genie
from relay_core.automation import queue

FAILED = genie.DeliveryError('HTTP 503')


def message(**values):
    return _dict({'name': 'RELAY-MSG-0000000001', 'direction': 'Incoming', 'relay_contact': 'RELAY-CON-0000000001',
                  'channel': 'RELAY-CH-1', 'content': 'Where is my order?', 'message_type': 'text',
                  'creation': datetime(2026, 11, 25, 16, 20, 52), **values})


def fake_frappe(settings=None):
    settings = {'genie_url': 'https://genie.example/relay', 'genie_business_types': '', **(settings or {})}
    fake = Mock()
    fake.db.get_single_value.side_effect = lambda doctype, field: settings.get(field)
    fake.local.site = 'relay.test'
    fake.throw.side_effect = ValueError
    return fake


class GenieTests(unittest.TestCase):
    def setUp(self):
        self.frappe = fake_frappe()
        self.enterContext(patch.object(genie, 'frappe', self.frappe))
        self.enabled = self.enterContext(patch.object(genie.features, 'is_enabled', return_value=True))
        self.enterContext(patch('relay_core.opt_out.keywords', return_value={'stop', 'start'}))

    def test_payload_has_the_contract_shape_and_no_contact_details(self):
        values = {('Relay Contact', 'display_name'): '+91 98765 43210', ('Relay Channel', 'channel'): 'WhatsApp'}
        self.frappe.db.get_value.side_effect = lambda doctype, name, field: values[(doctype, field)]
        doc = message(business_doctype='Customer', business_name='CUST-0001',
                      message_data=json.dumps({'kind': 'image', 'media': {'id': 'm1'}}), message_type='image')
        with patch.object(genie, 'get_system_timezone', return_value='Asia/Kolkata'), \
             patch('relay_core.business_types.type_label', return_value='Retailer'):
            body = genie.payload(doc)
        self.assertEqual(body, {'version': 1, 'site': 'relay.test', 'message_id': doc.name, 'chat': doc.relay_contact,
                                'contact': doc.relay_contact, 'contact_name': '', 'channel': 'WhatsApp',
                                'text': 'Where is my order?', 'message_type': 'image', 'has_media': True,
                                'business': {'doctype': 'Customer', 'doctype_label': 'Retailer', 'name': 'CUST-0001'},
                                'timestamp': '2026-11-25T10:50:52Z'})

    def test_voice_transcript_is_the_text_and_a_missing_business_is_null(self):
        self.frappe.db.get_value.return_value = 'Asha'
        with patch.object(genie, 'get_system_timezone', return_value='UTC'):
            body = genie.payload(message(transcript='Send the bill', content='', message_type='audio'))
        self.assertEqual((body['text'], body['business'], body['contact_name'], body['has_media']),
                         ('Send the bill', None, 'Asha', False))

    def test_post_signs_the_exact_raw_body(self):
        response = Mock(status_code=202)
        with patch.object(genie, 'payload', return_value={'text': 'வணக்கம்'}), \
             patch.object(genie.requests, 'post', return_value=response) as post:
            genie.post('https://genie.example/relay', 'secret-' * 6, message())
        body, headers = post.call_args.kwargs['data'], post.call_args.kwargs['headers']
        expected = hmac.new(('secret-' * 6).encode(), body, hashlib.sha256).hexdigest()
        self.assertEqual(headers['X-Hub-Signature-256'], 'sha256=' + expected)
        self.assertEqual(headers['X-Relay-Delivery'], 'RELAY-MSG-0000000001')
        self.assertEqual(json.loads(body), {'text': 'வணக்கம்'})
        self.assertEqual(post.call_args.kwargs['timeout'], 10)

    def test_non_2xx_and_timeouts_are_delivery_errors(self):
        with patch.object(genie, 'payload', return_value={}):
            for outcome in (Mock(status_code=500), requests.Timeout('slow')):
                with patch.object(genie.requests, 'post', side_effect=[outcome]), self.assertRaises(genie.DeliveryError):
                    genie.post('https://genie.example/relay', 'secret', message())

    def test_only_real_customer_messages_go_when_enabled(self):
        self.assertTrue(genie.handles(message()))
        for doc in (message(direction='Outgoing'), message(legacy_source='old'), message(message_type='system'),
                    message(content='STOP'), message(provider_context=json.dumps({'provider': 'WhatsApp', 'group_id': 'g1'})),
                    message(provider_context=json.dumps({'provider': 'Telegram', 'chat_type': 'supergroup'})),
                    message(provider_context=json.dumps({'provider': 'Email', 'auto_submitted': True}))):
            self.assertFalse(genie.handles(doc), doc)
        self.enabled.return_value = False
        self.assertFalse(genie.handles(message()))

    def test_business_type_filter(self):
        self.frappe.db.get_single_value.side_effect = lambda doctype, field: {
            'genie_url': 'https://genie.example/relay', 'genie_business_types': 'Customer\nSupplier\n'}.get(field)
        self.assertTrue(genie.handles(message(business_doctype='Supplier')))
        self.assertFalse(genie.handles(message(business_doctype='Lead')))
        self.assertFalse(genie.handles(message()))

    def test_hook_enqueues_once_per_message_after_commit(self):
        genie.on_message(message())
        self.frappe.enqueue.assert_called_once_with(
            'relay_core.genie.deliver', message='RELAY-MSG-0000000001', attempt=1, queue='default', timeout=30,
            job_id='relay-genie:RELAY-MSG-0000000001', deduplicate=True, enqueue_after_commit=True)
        self.frappe.enqueue.reset_mock()
        genie.on_message(message(direction='Outgoing'))
        self.frappe.enqueue.assert_not_called()

    def test_hook_logs_instead_of_raising_into_inbound_work(self):
        self.frappe.enqueue.side_effect = ConnectionError
        genie.on_message(message())
        self.assertEqual(self.frappe.log_error.call_args.kwargs['title'], 'Relay Genie enqueue failed')

    def deliver(self, attempt, error=FAILED, doc=None):
        self.frappe.get_doc.return_value = doc or message()
        self.frappe.get_single.return_value.get_password.return_value = 'secret'
        self.frappe.cache.make_key.side_effect = lambda key: 'site|' + key
        with patch.object(genie, 'post', side_effect=error) as post, patch.object(genie.time, 'time', return_value=1000):
            genie.deliver('RELAY-MSG-0000000001', attempt)
        return post

    def test_failed_tries_are_scheduled_with_backoff_then_logged_once(self):
        self.deliver(1)
        self.frappe.cache.zadd.assert_called_once_with('site|relay-genie-retries', {'2:RELAY-MSG-0000000001': 1060})
        self.frappe.cache.zadd.reset_mock()
        self.deliver(5)
        self.frappe.cache.zadd.assert_called_once_with('site|relay-genie-retries', {'6:RELAY-MSG-0000000001': 1900})
        self.frappe.cache.zadd.reset_mock()
        self.deliver(6)
        self.frappe.cache.zadd.assert_not_called()
        self.frappe.log_error.assert_called_once()
        self.assertNotIn('secret', str(self.frappe.log_error.call_args))

    def test_success_and_disabled_do_not_retry(self):
        post = self.deliver(1, error=None)
        post.assert_called_once()
        self.enabled.return_value = False
        post = self.deliver(1)
        post.assert_not_called()
        self.frappe.cache.zadd.assert_not_called()

    def test_voice_note_waits_for_its_transcript(self):
        post = self.deliver(1, doc=message(message_type='audio', transcript_status='Pending'))
        post.assert_not_called()
        self.frappe.cache.zadd.assert_called_once()
        post = self.deliver(6, error=None, doc=message(message_type='audio', transcript_status='Pending'))
        post.assert_called_once()

    def test_due_retries_are_taken_once_and_requeued_with_their_attempt(self):
        self.frappe.cache.make_key.side_effect = lambda key: key
        self.frappe.cache.zrangebyscore.return_value = [b'3:RELAY-MSG-0000000001', b'2:RELAY-MSG-0000000002']
        self.frappe.cache.zrem.side_effect = [1, 0]
        genie.retry_due()
        self.frappe.enqueue.assert_called_once()
        self.assertEqual(self.frappe.enqueue.call_args.kwargs['attempt'], 3)
        self.assertEqual(self.frappe.enqueue.call_args.kwargs['job_id'], 'relay-genie:RELAY-MSG-0000000001')

    def test_url_validation(self):
        for url in ('https://genie.example/relay', 'http://127.0.0.1:8080/relay', 'http://localhost/relay',
                    'http://10.0.0.4/relay', 'http://192.168.1.2/relay', 'http://100.64.0.11:9000/relay'):
            genie.validate_url(url)
        for url in ('http://genie.example/relay', 'http://8.8.8.8/relay', 'ftp://10.0.0.4/relay',
                    'https://user:pass@genie.example/relay', 'genie.example'):
            with self.assertRaises(ValueError, msg=url):
                genie.validate_url(url)

    def test_enabling_needs_url_and_secret(self):
        with self.assertRaises(ValueError):
            genie.validate_settings(_dict(genie_enabled=1, genie_url='https://genie.example/relay'))
        genie.validate_settings(_dict(genie_enabled=1, genie_url='https://genie.example/relay', genie_secret='*' * 8))


class DrainTests(unittest.TestCase):
    def test_genie_runs_last_in_the_inbound_drain(self):
        self.assertEqual(queue.HANDLERS[-1], 'relay_core.genie.on_message')


if __name__ == '__main__':
    unittest.main()
