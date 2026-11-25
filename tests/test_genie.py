import hashlib
import hmac
import json
import unittest
from datetime import datetime
from unittest.mock import Mock, call, patch

import requests
from frappe import _dict
from relay_core import genie
from relay_core.automation import queue, service

FAILED = genie.DeliveryError('HTTP 503')


def message(**values):
    return _dict({'name': 'RELAY-MSG-0000000001', 'direction': 'Incoming', 'relay_contact': 'RELAY-CON-0000000001',
                  'channel': 'RELAY-CH-1', 'content': 'Where is my order?', 'message_type': 'text',
                  'creation': datetime(2026, 11, 25, 16, 20, 52), **values})


NOW = datetime(2026, 11, 25, 12, 0, 0)


def fake_frappe(settings=None):
    settings = {'genie_url': 'https://genie.example/relay', 'genie_business_types': '', 'genie_user': 'genie@relay.test',
                **(settings or {})}
    fake = Mock()
    fake.db.get_single_value.side_effect = lambda doctype, field: settings.get(field)
    fake.db.get_value.side_effect = lambda doctype, name, field=None, **kwargs: (0, 3) if doctype == 'Relay Contact' else None
    fake.cache.hget.return_value = None
    fake.local.site = 'relay.test'
    fake.throw.side_effect = ValueError
    return fake


class GenieTests(unittest.TestCase):
    def setUp(self):
        self.frappe = fake_frappe()
        self.enterContext(patch.object(genie, 'frappe', self.frappe))
        self.enabled = self.enterContext(patch.object(genie.features, 'is_enabled', return_value=True))
        self.enterContext(patch('relay_core.opt_out.keywords', return_value={'stop', 'start'}))
        self.enterContext(patch.object(genie, 'now_datetime', return_value=NOW))
        self.enterContext(patch.object(genie, 'held_ticket', return_value=None))

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
        self.frappe.db.get_value.side_effect = None
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

    def test_hook_keeps_a_delivery_row_and_enqueues_once_after_commit(self):
        self.frappe.db.exists.return_value = False
        genie.on_message(message())
        row = self.frappe.get_doc.call_args.args[0]
        self.assertEqual((row['doctype'], row['message'], row['relay_contact'], row['status'], row['attempts']),
                         ('Relay Genie Delivery', 'RELAY-MSG-0000000001', 'RELAY-CON-0000000001', 'Pending', 0))
        self.assertEqual(row['next_try'], datetime(2026, 11, 25, 12, 2, 0))  # The scheduler's lease, if the job is lost.
        self.frappe.get_doc.return_value.insert.assert_called_once_with(ignore_permissions=True)
        self.frappe.enqueue.assert_called_once_with(
            'relay_core.genie.deliver', message='RELAY-MSG-0000000001', queue='default', timeout=30,
            job_id='relay-genie:RELAY-MSG-0000000001', deduplicate=True, enqueue_after_commit=True)
        self.frappe.enqueue.reset_mock()
        self.frappe.db.exists.return_value = True  # A drain replay of the same message.
        genie.on_message(message())
        genie.on_message(message(direction='Outgoing'))
        self.frappe.enqueue.assert_not_called()

    def test_hook_logs_instead_of_raising_into_inbound_work(self):
        self.frappe.db.exists.return_value = False
        self.frappe.enqueue.side_effect = ConnectionError
        genie.on_message(message())
        self.assertEqual(self.frappe.log_error.call_args.kwargs['title'], 'Relay Genie enqueue failed')

    def test_a_chat_staff_took_over_does_not_go_to_genie(self):
        contact = {'paused': 1, 'generation': 4}
        self.frappe.db.get_value.side_effect = lambda doctype, name, field=None, **kwargs: (contact['paused'], contact['generation'])
        self.assertFalse(genie.handles(message()))
        self.frappe.db.exists.return_value = False
        genie.on_message(message())
        self.frappe.enqueue.assert_not_called()
        # A pause made by an active MCP claim (Genie's own claim during its turn) is not a takeover.
        claim = {'user': 'genie@relay.test', 'until': 2e9, 'paused_generation': 4}
        self.frappe.cache.hget.return_value = json.dumps(claim)
        self.assertTrue(genie.handles(message()))
        # Staff took over again after the claim paused it, or the claim expired: a takeover.
        contact['generation'] = 5
        self.assertFalse(genie.handles(message()))
        self.frappe.cache.hget.return_value = json.dumps(dict(claim, until=1, paused_generation=5))
        self.assertFalse(genie.handles(message()))

    def test_a_ticket_held_by_staff_is_a_takeover_but_genies_own_reply_is_not(self):
        with patch.object(genie, 'held_ticket', return_value=_dict(ai_disabled=1, ownership_actor='staff@relay.test')):
            self.assertFalse(genie.handles(message()))
            self.assertTrue(genie.is_taken_over('RELAY-CON-0000000001', message()))
        with patch.object(genie, 'held_ticket', return_value=_dict(ai_disabled=1, ownership_actor='genie@relay.test')):
            self.assertTrue(genie.handles(message()))
        with patch.object(genie, 'held_ticket', return_value=_dict(ai_disabled=0, ownership_actor='staff@relay.test')):
            self.assertTrue(genie.handles(message()))

    def test_drain_sends_a_taken_over_chat_down_the_staff_path(self):
        with patch.object(genie, 'is_taken_over', return_value=True), patch.object(service, 'create_run') as admit:
            service.on_message(message())
        admit.assert_called_once()  # create_run cancels it as owned by staff.

    def test_reply_context_tells_the_agent_staff_took_over(self):
        from relay_core.mcp_tools import inbox
        with patch('relay_core.reply_context.read', return_value={'messages': {'items': []}}), \
             patch('relay_core.mcp_tools.coordination.with_actors', return_value=[]), \
             patch.object(genie, 'is_chat_taken_over', return_value=True) as taken:
            result = inbox.reply_context('RELAY-CON-0000000001')
        self.assertIs(result['taken_over'], True)
        taken.assert_called_once_with('RELAY-CON-0000000001')

    def deliver(self, attempts=0, error=FAILED, doc=None, status='Pending'):
        self.frappe.db.get_value.side_effect = lambda doctype, name, field=None, **kwargs: (
            _dict(status=status, attempts=attempts) if doctype == 'Relay Genie Delivery' else (0, 3))
        self.frappe.get_doc.return_value = doc or message()
        self.frappe.get_single.return_value.get_password.return_value = 'secret'
        self.frappe.db.set_value.reset_mock()
        with patch.object(genie, 'post', side_effect=error) as post:
            genie.deliver('RELAY-MSG-0000000001')
        return post

    def saved(self):
        return self.frappe.db.set_value.call_args.args[2]

    def test_failed_tries_keep_their_backoff_in_the_database_then_fail_once(self):
        self.deliver(0)
        self.assertEqual(self.saved(), {'attempts': 1, 'next_try': datetime(2026, 11, 25, 12, 1), 'last_error': 'HTTP 503'})
        self.deliver(4)
        self.assertEqual(self.saved(), {'attempts': 5, 'next_try': datetime(2026, 11, 25, 12, 15), 'last_error': 'HTTP 503'})
        self.frappe.log_error.assert_not_called()
        self.deliver(5)
        self.assertEqual(self.saved(), {'status': 'Failed', 'attempts': 6, 'last_error': 'HTTP 503'})
        self.frappe.log_error.assert_called_once()
        self.assertNotIn('secret', str(self.frappe.log_error.call_args))
        self.frappe.cache.zadd.assert_not_called()

    def test_success_is_sent_and_a_finished_or_disabled_row_is_not_tried(self):
        post = self.deliver(1, error=None)
        post.assert_called_once()
        self.assertEqual(self.saved(), {'status': 'Sent', 'attempts': 2, 'delivered_at': NOW, 'last_error': None})
        for status in ('Sent', 'Failed', 'Skipped'):
            self.deliver(error=None, status=status).assert_not_called()
        self.enabled.return_value = False
        self.deliver().assert_not_called()
        self.assertEqual(self.saved(), {'status': 'Skipped'})

    def test_voice_note_waits_for_its_transcript(self):
        post = self.deliver(0, doc=message(message_type='audio', transcript_status='Pending'))
        post.assert_not_called()
        self.assertEqual(self.saved()['last_error'], 'Waiting for the voice transcript')
        post = self.deliver(5, error=None, doc=message(message_type='audio', transcript_status='Pending'))
        post.assert_called_once()

    def test_due_retries_come_from_the_database_and_survive_a_cache_flush(self):
        self.frappe.cache = Mock(side_effect=AssertionError, **{name: Mock(side_effect=AssertionError('cache used'))
                                                                 for name in ('zadd', 'zrangebyscore', 'zrem', 'get_value')})
        self.frappe.get_all.return_value = ['RELAY-MSG-0000000001', 'RELAY-MSG-0000000002']
        genie.retry_due()
        filters = self.frappe.get_all.call_args.kwargs['filters']
        self.assertEqual(filters, {'status': 'Pending', 'next_try': ['<=', NOW]})
        self.assertEqual([entry.args[:3] for entry in self.frappe.db.set_value.call_args_list],
                         [('Relay Genie Delivery', name, 'next_try') for name in self.frappe.get_all.return_value])
        self.assertEqual([entry.kwargs['message'] for entry in self.frappe.enqueue.call_args_list],
                         ['RELAY-MSG-0000000001', 'RELAY-MSG-0000000002'])

    def watch(self, replied=False, noted=False, claimed=False):
        rows = [_dict(name='RELAY-MSG-0000000001', relay_contact='RELAY-CON-0000000001')]
        self.frappe.get_all.return_value = rows
        self.frappe.db.exists.side_effect = lambda doctype, filters: replied if doctype == 'Relay Message' else noted
        self.frappe.db.set_value.reset_mock()
        with patch('relay_core.mcp_tools.coordination.active_claim', return_value={'user': 'x'} if claimed else None), \
             patch('relay_core.collaboration.add') as add:
            genie.watch()
        return add

    def test_watchdog_notes_an_unanswered_chat_once(self):
        add = self.watch()
        add.assert_called_once_with('RELAY-CON-0000000001', 'Not answered automatically; please reply.',
                                    'genie-watch-RELAY-MSG-0000000001', messages=['RELAY-MSG-0000000001'])
        self.frappe.db.set_value.assert_called_once_with('Relay Genie Delivery', 'RELAY-MSG-0000000001', {'follow_up': 'Noted'})
        filters = self.frappe.get_all.call_args.kwargs['filters']
        self.assertEqual(filters, {'status': 'Sent', 'follow_up': ['is', 'not set'], 'delivered_at': ['<=', datetime(2026, 11, 25, 11, 50)]})

    def test_watchdog_leaves_answered_noted_and_claimed_chats(self):
        self.watch(replied=True).assert_not_called()
        self.assertEqual(self.saved(), {'follow_up': 'Replied'})
        self.watch(noted=True).assert_not_called()
        self.assertEqual(self.saved(), {'follow_up': 'Noted'})
        self.watch(claimed=True).assert_not_called()
        self.frappe.db.set_value.assert_not_called()  # Checked again next minute, after the claim.

    def test_a_failed_watchdog_note_is_marked_and_logged_not_retried_each_minute(self):
        self.frappe.get_all.return_value = [_dict(name='RELAY-MSG-0000000001', relay_contact='RELAY-CON-0000000001')]
        self.frappe.db.exists.return_value = False
        with patch('relay_core.mcp_tools.coordination.active_claim', return_value=None), \
             patch('relay_core.collaboration.add', side_effect=PermissionError):
            genie.watch()
        self.assertEqual(self.saved(), {'follow_up': 'Note Failed'})
        self.frappe.log_error.assert_called_once()

    def test_url_validation(self):
        for url in ('https://genie.example/relay', 'http://127.0.0.1:8080/relay', 'http://localhost/relay',
                    'http://10.0.0.4/relay', 'http://192.168.1.2/relay', 'http://100.64.0.11:9000/relay'):
            genie.validate_url(url)
        for url in ('http://genie.example/relay', 'http://8.8.8.8/relay', 'ftp://10.0.0.4/relay',
                    'https://user:pass@genie.example/relay', 'genie.example'):
            with self.assertRaises(ValueError, msg=url):
                genie.validate_url(url)

    def test_enabling_needs_url_secret_and_user(self):
        for values in ({}, {'genie_secret': '*' * 8}, {'genie_user': 'genie@relay.test'}):
            with self.assertRaises(ValueError):
                genie.validate_settings(_dict(genie_enabled=1, genie_url='https://genie.example/relay', **values))
        genie.validate_settings(_dict(genie_enabled=1, genie_url='https://genie.example/relay', genie_secret='*' * 8,
                                      genie_user='genie@relay.test'))


class DrainTests(unittest.TestCase):
    def test_relay_automation_does_not_admit_messages_genie_answers(self):
        with patch.object(genie, 'handles', return_value=True), patch.object(service, 'create_run') as admit:
            self.assertEqual(service.on_message(message()), {'status': 'Ignored'})
        admit.assert_not_called()
        with patch.object(genie, 'handles', return_value=False), patch.object(service, 'create_run') as admit:
            service.on_message(message())
        admit.assert_called_once()

    def test_email_rule_does_not_reply_to_messages_genie_answers(self):
        from relay_core import email_preferences
        fake = Mock()
        with patch.object(genie, 'handles', return_value=True), patch.object(email_preferences, 'frappe', fake):
            email_preferences.on_message(message())
        fake.db.set_value.assert_not_called()

    def test_genie_runs_last_in_the_inbound_drain(self):
        self.assertEqual(queue.HANDLERS[-1], 'relay_core.genie.on_message')

    def test_the_genie_job_runs_without_a_relay_hub(self):
        from relay_core import scheduled_jobs
        with patch.object(scheduled_jobs, 'is_hub_configured', return_value=False), patch.object(genie, 'run_due') as run:
            scheduled_jobs.retry_genie()
        run.assert_called_once()

    def test_the_delivery_table_is_indexed_for_the_scheduler(self):
        from relay_core.relay_core.doctype.relay_genie_delivery import relay_genie_delivery as doctype
        fake = Mock()
        with patch.object(doctype, 'frappe', fake):
            doctype.on_doctype_update()
        self.assertIn(call('Relay Genie Delivery', ['status', 'next_try'], 'relay_genie_delivery_due'),
                      fake.db.add_index.call_args_list)


if __name__ == '__main__':
    unittest.main()
