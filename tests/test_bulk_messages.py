"""Bulk text and media campaigns: mapping, placeholders, media sources, reply window and Hub payloads."""
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import frappe
from frappe import _dict
from relay_core import bulk_campaigns, bulk_sheet, service_window
from test_bulk_campaigns import NAMED, POSITIONAL, UTILS, FakeCache

TEXT = {'kind': 'text', 'body': 'Hi {{Name}}, your order {{ Order No }} is ready'}
PHOTO = {'kind': 'photo', 'caption': 'Offer for {{Name}}'}


class MessageTests(unittest.TestCase):
    def test_text_placeholders_become_values_matched_by_column_name_and_fill_per_row(self):
        message = bulk_sheet.check_message(TEXT)
        fields = bulk_sheet.message_fields(message)
        self.assertEqual([field['key'] for field in fields], ['text:Name', 'text:Order No'])
        mapping = bulk_sheet.check_mapping(bulk_sheet.suggest(['Mobile', 'Order No', 'Name'], fields), ['Mobile', 'Order No', 'Name'], fields)
        _, values, problem = bulk_sheet.prepare_row({'Mobile': '9876543210', 'Name': 'Asha', 'Order No': 'SO-7'}, mapping, fields, 'IN')
        self.assertIsNone(problem)
        self.assertEqual(bulk_sheet.build_message(message, values['values']),
                         {'operation': 'messages.send', 'body': 'Hi Asha, your order SO-7 is ready'})
        self.assertEqual(bulk_sheet.prepare_row({'Mobile': '9876543210', 'Name': '', 'Order No': 'SO-7'}, mapping, fields, 'IN')[2],
                         'Missing Name')

    def test_messages_are_checked_against_the_whatsapp_registry(self):
        for message, reason in (({'kind': 'text', 'body': ' '}, 'characters'), ({'kind': 'sticker'}, 'photo, video'),
                                ({'kind': 'audio'}, 'photo, video'), ({'kind': 'video', 'caption': 'x' * 1025}, 'caption')):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, reason):
                bulk_sheet.check_message(message)
        self.assertEqual(bulk_sheet.check_message({'kind': 'document', 'caption': ' Bill '}), {'kind': 'document', 'caption': 'Bill'})
        self.assertEqual(bulk_sheet.message_problem(TEXT, {'text:Name': 'x' * 4096}), 'Message is too long')
        self.assertEqual(bulk_sheet.message_problem(PHOTO, {'text:Name': 'x' * 1024}), 'Caption is too long')
        self.assertIsNone(bulk_sheet.message_problem(PHOTO, {'text:Name': 'Asha'}))

    def test_media_comes_from_one_fixed_link_or_a_column_per_row(self):
        fields = bulk_sheet.message_fields(PHOTO)
        self.assertEqual(fields[-1], {'key': 'media_url', 'label': 'Photo link', 'component': 'media', 'media': 'image'})
        header, row = ['Mobile', 'Name', 'Picture'], {'Mobile': '9876543210', 'Name': 'Asha', 'Picture': 'https://cdn.example/a.jpg'}
        fixed = bulk_sheet.check_mapping({'phone': 'Mobile', 'fields': {'text:Name': 'Name'},
                                          'fixed': {'media_url': 'https://relay.example/files/offer.jpg'}}, header, fields)
        column = bulk_sheet.check_mapping({'phone': 'Mobile', 'fields': {'text:Name': 'Name', 'media_url': 'Picture'}}, header, fields)
        for mapping, link in ((fixed, 'https://relay.example/files/offer.jpg'), (column, 'https://cdn.example/a.jpg')):
            values = bulk_sheet.prepare_row(row, mapping, fields, 'IN')[1]['values']
            self.assertEqual(bulk_sheet.build_message(PHOTO, values), {'operation': 'messages.media', 'media_type': 'image',
                             'media_url': link, 'caption': 'Offer for Asha'})
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            bulk_sheet.check_mapping(dict(fixed, fixed={'media_url': 'http://relay.localhost/files/offer.jpg'}), header, fields)
        self.assertIn('HTTPS', bulk_sheet.prepare_row(dict(row, Picture='ftp://x/a.jpg'), column, fields, 'IN')[2])

    def test_documents_carry_a_file_name_and_captions_may_be_empty(self):
        values = {'media_url': 'https://cdn.example/bills/March%20bill.pdf?v=2'}
        self.assertEqual(bulk_sheet.build_message({'kind': 'document', 'caption': ''}, values),
                         {'operation': 'messages.media', 'media_type': 'document', 'media_url': values['media_url'],
                          'filename': 'March bill.pdf'})
        self.assertEqual(bulk_sheet.file_name('https://cdn.example/'), 'document')


class CreateTests(unittest.TestCase):
    def test_a_message_campaign_snapshots_the_message_without_a_template_or_hub_call(self):
        saved = []
        fake = SimpleNamespace(db=Mock(exists=Mock(return_value=False)), utils=frappe.utils, parse_json=frappe.parse_json,
                               get_doc=lambda values: _dict(values), throw=Mock(side_effect=frappe.ValidationError))
        with patch.object(bulk_campaigns, 'frappe', fake), patch.object(bulk_campaigns, 'require_access'), \
                patch.object(bulk_campaigns, 'whatsapp_channel', return_value='WA'), \
                patch.object(bulk_campaigns.whatsapp, 'checked_client') as hub, \
                patch.object(bulk_campaigns, 'connection_value', return_value='acct'), \
                patch.object(bulk_campaigns, 'default_region', return_value='IN'), \
                patch.object(bulk_campaigns, 'internal_save', side_effect=lambda doc, new: saved.append(doc)), \
                patch.object(bulk_campaigns, 'read', side_effect=lambda name: name):
            bulk_campaigns.create('Order ready', message=json.dumps(PHOTO))
            hub.assert_not_called()
            with self.assertRaises(frappe.ValidationError):
                bulk_campaigns.create('Stickers', message={'kind': 'sticker'})
        doc = saved[0]
        self.assertEqual((doc.operation, doc.template_name, doc.language), ('messages.media', None, None))
        snapshot = json.loads(doc.arguments)
        self.assertEqual(snapshot['message'], PHOTO)
        self.assertEqual([field['key'] for field in snapshot['fields']], ['text:Name', 'media_url'])
        self.assertTrue(bulk_campaigns.is_bulk(doc))
        self.assertFalse(bulk_campaigns.is_bulk(_dict(operation='messages.send', arguments='{"body": "old"}')))

    def test_media_link_needs_a_public_file_of_an_accepted_type(self):
        doc = _dict(arguments=json.dumps({'message': PHOTO, 'fields': []}))
        file = _dict(is_private=0, file_name='offer.png', file_url='/files/offer.png')
        fake = SimpleNamespace(utils=SimpleNamespace(get_url=lambda path: 'https://relay.example' + path),
                               throw=Mock(side_effect=frappe.ValidationError))
        with patch.object(bulk_campaigns, 'frappe', fake), patch.object(bulk_campaigns, 'bulk', return_value=doc), \
                patch.object(bulk_campaigns, 'uploaded_file', return_value=file):
            self.assertEqual(bulk_campaigns.media_link('Offer', '/files/offer.png'),
                             {'url': 'https://relay.example/files/offer.png', 'file_name': 'offer.png'})
            for change in ({'is_private': 1}, {'file_name': 'offer.mp4'}):
                file.update({'is_private': 0, 'file_name': 'offer.png', **change})
                with self.subTest(change=change), self.assertRaises(frappe.ValidationError):
                    bulk_campaigns.media_link('Offer', '/files/offer')


class WindowTests(unittest.TestCase):
    def test_open_numbers_use_the_reply_window_rule_and_ignore_future_provider_clocks(self):
        now = frappe.utils.get_datetime('2026-10-26 10:00:00')
        rows = [_dict(sender_endpoint='9101', sent_at=None, creation=now.replace(hour=9)),
                _dict(sender_endpoint='9102', sent_at=now.replace(day=25, hour=9), creation=now.replace(hour=9)),
                _dict(sender_endpoint='9103', sent_at=now.replace(day=27), creation=now.replace(day=25, hour=11))]
        get_all = Mock(return_value=rows)
        fake = SimpleNamespace(get_all=get_all, utils=SimpleNamespace(now_datetime=lambda: now, get_datetime=frappe.utils.get_datetime,
                                                                      add_to_date=frappe.utils.add_to_date))
        with patch.object(service_window, 'frappe', fake):
            self.assertEqual(service_window.open_numbers('WA', ['9101', '9102', '9103']), {'9101', '9103'})
            self.assertEqual(service_window.open_numbers('WA', []), set())
        filters = get_all.call_args.kwargs['filters']
        self.assertEqual((filters['direction'], filters['sender_endpoint'], str(filters['creation'][1])),
                         ('Incoming', ['in', ['9101', '9102', '9103']], '2026-10-25 10:00:00'))
        get_all.assert_called_once()

    def test_preflight_counts_pending_numbers_with_an_open_window(self):
        numbers = [f'91987654{i:04d}' for i in range(1500)]
        fake = SimpleNamespace(get_all=Mock(return_value=numbers))
        with patch.object(bulk_campaigns, 'frappe', fake), patch.object(bulk_campaigns, 'bulk', return_value=_dict(channel='WA')), \
                patch.object(service_window, 'open_numbers', side_effect=lambda channel, chunk: set(chunk[:10])) as reachable:
            self.assertEqual(bulk_campaigns.window('Offer'), {'open': 20, 'closed': 1480})
        self.assertEqual([len(call.args[1]) for call in reachable.call_args_list], [1000, 500])


class PushTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.db.get_value.return_value = 'Running'
        self.enterContext(patch.object(bulk_campaigns, 'frappe', SimpleNamespace(db=self.db, utils=UTILS, cache=FakeCache())))
        self.timeline = self.enterContext(patch('relay_core.bulk_timeline.record'))
        self.enterContext(patch('relay_core.bulk_timeline.reserve', return_value=41))
        self.changed = self.enterContext(patch('relay_core.bulk_updates.changed'))
        self.hub = Mock()
        self.hub.call_tool.side_effect = lambda tool, args: {'queued': 1, 'deliveries': [
            {'id': str(i), 'key': m['key'], 'state': 'queued'} for i, m in enumerate(args['messages'])]}
        self.enterContext(patch.object(bulk_campaigns.whatsapp, 'client', return_value=self.hub))

    def run_push(self, message, rows, reachable):
        doc = _dict(name='Offer', channel='WA', operation='messages.media', status='Running', last_error='',
                    arguments=json.dumps({'message': message, 'fields': bulk_sheet.message_fields(message)}))
        batches = [rows, []]
        self.db.sql.side_effect = lambda query, *args, **kwargs: batches.pop(0) if query.lstrip().startswith('SELECT') else None
        with patch.object(service_window, 'open_numbers', return_value=set(reachable)):
            self.assertFalse(bulk_campaigns.push(doc, time.monotonic() + 30))

    def row(self, index, values):
        return _dict(name=f'r{index}', request_key=f'bulk-k-{index}', destination=f'9198765432{index:02d}',
                     arguments=json.dumps({'values': values}))

    def test_hub_gets_one_payload_per_message_type(self):
        cases = ((TEXT, {'text:Name': 'Asha', 'text:Order No': 'SO-7'},
                  {'operation': 'messages.send', 'body': 'Hi Asha, your order SO-7 is ready'}),
                 (PHOTO, {'text:Name': 'Asha', 'media_url': 'https://cdn.example/a.jpg'},
                  {'operation': 'messages.media', 'media_type': 'image', 'media_url': 'https://cdn.example/a.jpg', 'caption': 'Offer for Asha'}),
                 ({'kind': 'video', 'caption': ''}, {'media_url': 'https://cdn.example/a.mp4'},
                  {'operation': 'messages.media', 'media_type': 'video', 'media_url': 'https://cdn.example/a.mp4'}))
        for message, values, expected in cases:
            with self.subTest(kind=message['kind']):
                self.hub.call_tool.reset_mock()
                self.run_push(message, [self.row(0, values)], ['919876543200'])
                tool, arguments = self.hub.call_tool.call_args.args
                self.assertEqual(tool, 'whatsapp.bulk')
                self.assertEqual(arguments['messages'], [{'key': 'bulk-k-0', 'message': {**expected, 'to': '919876543200'}}])

    def test_rows_outside_the_window_fail_without_a_hub_call(self):
        values = {'text:Name': 'Asha', 'text:Order No': 'SO-7'}
        self.run_push(TEXT, [self.row(0, values), self.row(1, values)], ['919876543201'])
        failed = [c for c in self.db.sql.call_args_list if "SET status='Failed'" in c.args[0]]
        self.assertEqual(failed[0].args[1], (bulk_campaigns.OUTSIDE_WINDOW, ('r0',)))
        self.assertEqual([m['key'] for m in self.hub.call_tool.call_args.args[1]['messages']], ['bulk-k-1'])
        self.assertEqual([row.request_key for row in self.timeline.call_args.args[2]], ['bulk-k-1'])
        self.changed.assert_any_call('Offer')

    def test_a_batch_wholly_outside_the_window_never_reaches_hub(self):
        self.run_push(TEXT, [self.row(0, {'text:Name': 'Asha', 'text:Order No': 'SO-7'})], [])
        self.hub.call_tool.assert_not_called()


class RecoverTests(unittest.TestCase):
    def test_recovery_skips_older_text_campaigns_in_sql_and_resumes_bulk_ones(self):
        rows = [_dict(name='Old', status='Running', operation='messages.send', template_name=None, arguments='{"body": "x"}'),
                _dict(name='Offer', status='Running', operation='messages.media', template_name=None,
                      arguments=json.dumps({'message': PHOTO, 'fields': []}))]
        get_all = Mock(return_value=rows)
        with patch.object(bulk_campaigns, 'frappe', SimpleNamespace(get_all=get_all)), \
                patch.object(bulk_campaigns, 'enqueue') as enqueue, patch('relay_core.bulk_updates.recover'):
            bulk_campaigns.recover()
        self.assertEqual(get_all.call_args.kwargs['or_filters'],
                         {'template_name': ['is', 'set'], 'arguments': ['like', '%"message"%']})
        enqueue.assert_called_once_with('send_job', 'Offer')


class TimelineTests(unittest.TestCase):
    def test_text_and_media_rows_show_what_was_sent(self):
        from relay_core.bulk_timeline import sent_content
        doc = _dict(name='Offer')
        self.assertEqual(sent_content(doc, {'message': TEXT}, {'body': 'Hi Asha'}),
                         {'kind': 'text', 'text': 'Hi Asha', 'campaign': 'Offer'})
        self.assertEqual(sent_content(doc, {'message': PHOTO}, {'caption': 'Offer for Asha'})['text'], 'Photo: Offer for Asha')
        self.assertEqual(sent_content(doc, {'message': {'kind': 'video', 'caption': ''}}, {})['text'], 'Video')


if __name__ == '__main__':
    unittest.main()
