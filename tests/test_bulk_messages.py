"""Bulk text and media campaigns: mapping, placeholders, media sources, reply window and Hub payloads."""
import json
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
import frappe
from frappe import _dict
from relay_core import bulk_campaigns, bulk_sheet, service_window
from test_bulk_campaigns import NAMED, POSITIONAL, UTILS, FakeCache
from site_file_limit import use_relay_file_limit


def setUpModule():
    use_relay_file_limit()
    # One-number sites name no Hub channel; the channel choice has its own tests.
    patcher = patch('relay_core.bulk_campaigns.hub_arguments', side_effect=lambda channel, arguments: arguments)
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)

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
        self.assertIn('HTTPS', bulk_sheet.prepare_row(dict(row, Picture='/private/files/a.jpg'), column, fields, 'IN')[2])

    def test_one_uploaded_file_is_sent_by_its_hub_media_id(self):
        fields = bulk_sheet.message_fields(PHOTO)
        mapping = bulk_sheet.check_mapping({'phone': 'Mobile', 'fields': {'text:Name': 'Name'},
                                            'fixed': {'media_url': '/private/files/offer.jpg'}}, ['Mobile', 'Name'], fields)
        values = bulk_sheet.prepare_row({'Mobile': '9876543210', 'Name': 'Asha'}, mapping, fields, 'IN')[1]['values']
        self.assertEqual(bulk_sheet.build_message(PHOTO, values, '555'),
                         {'operation': 'messages.media', 'media_type': 'image', 'media_id': '555', 'caption': 'Offer for Asha'})
        self.assertEqual(bulk_sheet.build_message({'kind': 'document', 'caption': ''}, {'media_url': '/private/files/March bill.pdf'}, '7'),
                         {'operation': 'messages.media', 'media_type': 'document', 'media_id': '7', 'filename': 'March bill.pdf'})
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            bulk_sheet.check_mapping({'phone': 'Mobile', 'fixed': {'header_media': '/files/a.jpg'}}, ['Mobile'],
                                     [{'key': 'header_media', 'label': 'Header image URL', 'component': 'header', 'media': 'image'}])

    def test_documents_carry_a_file_name_and_captions_may_be_empty(self):
        values = {'media_url': 'https://cdn.example/bills/March%20bill.pdf?v=2'}
        self.assertEqual(bulk_sheet.build_message({'kind': 'document', 'caption': ''}, values),
                         {'operation': 'messages.media', 'media_type': 'document', 'media_url': values['media_url'],
                          'filename': 'March bill.pdf'})
        self.assertEqual(bulk_sheet.file_name('https://cdn.example/'), 'document')


class CreateTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('frappe.utils.now', return_value='2026-10-26 10:00:00'))

    def test_a_message_campaign_snapshots_the_message_without_a_template_or_hub_call(self):
        saved = []
        fake = SimpleNamespace(db=Mock(exists=Mock(return_value=False),
                                      get_value=Mock(side_effect=['Essdee UK', 'United Kingdom'])),
                               session=_dict(user='manager@example.invalid'), utils=frappe.utils, parse_json=frappe.parse_json,
                               get_doc=lambda values: _dict(values), throw=Mock(side_effect=frappe.ValidationError))
        with patch.object(bulk_campaigns, 'frappe', fake), patch.object(bulk_campaigns, 'require_access'), \
                patch.object(bulk_campaigns, 'campaign_channel', return_value='WA'), \
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
        self.assertEqual(doc.country, 'GB')
        self.assertEqual((doc.operation, doc.template_name, doc.language), ('messages.media', None, None))
        snapshot = json.loads(doc.arguments)
        self.assertEqual(snapshot['message'], PHOTO)
        self.assertEqual([field['key'] for field in snapshot['fields']], ['text:Name', 'media_url'])
        self.assertTrue(bulk_campaigns.is_bulk(doc))
        self.assertFalse(bulk_campaigns.is_bulk(_dict(operation='messages.send', arguments='{"body": "old"}')))

    def test_fixed_file_must_be_a_readable_upload_of_an_accepted_type(self):
        doc = _dict(arguments=json.dumps({'message': PHOTO, 'fields': []}),
                    column_map=json.dumps({'fixed': {'media_url': '/private/files/offer.png'}}))
        file = _dict(file_name='offer.png')
        with patch.object(bulk_campaigns, 'frappe', SimpleNamespace(throw=Mock(side_effect=frappe.ValidationError))), \
                patch.object(bulk_campaigns, 'uploaded_file', return_value=file) as uploaded:
            self.assertEqual(bulk_campaigns.fixed_file(doc), (file, 'image/png'))
            uploaded.assert_called_once_with('/private/files/offer.png')
            file.file_name = 'offer.mp4'
            with self.assertRaises(frappe.ValidationError):
                bulk_campaigns.fixed_file(doc)
            self.assertIsNone(bulk_campaigns.fixed_file(_dict(doc, column_map=json.dumps({'fixed': {'media_url': 'https://cdn.example/a.png'}}))))
            self.assertIsNone(bulk_campaigns.fixed_file(_dict(doc, column_map=None)))


class MediaUploadTests(unittest.TestCase):
    """The fixed file goes to Hub once at start; every row then sends its media id."""
    NOW = frappe.utils.get_datetime('2026-10-26 10:00:00')

    def setUp(self):
        self.path = self.enterContext(tempfile.TemporaryDirectory()) + '/offer.png'
        with open(self.path, 'wb') as handle:
            handle.write(b'\x89PNG\r\n\x1a\n')
        self.file = _dict(file_name='offer.png', get_full_path=lambda: self.path)
        self.doc = _dict(name='Offer', status='Draft', channel='WA', operation='messages.media', last_error='', reply_window_hours=72,
                         arguments=json.dumps({'message': PHOTO, 'fields': bulk_sheet.message_fields(PHOTO)}),
                         column_map=json.dumps({'phone': 'Mobile', 'fields': {'text:Name': 'Name'},
                                                'fixed': {'media_url': '/private/files/offer.png'}}))
        self.hub = Mock()
        self.hub.execute.return_value = {'id': '555'}
        self.cache = FakeCache()
        self.cache.lock = Mock(side_effect=lambda *a, **k: MagicMock())
        utils = SimpleNamespace(now=lambda: '2026-10-26 10:00:00', now_datetime=lambda: self.NOW, get_datetime=frappe.utils.get_datetime,
                                add_to_date=frappe.utils.add_to_date, cint=frappe.utils.cint, flt=frappe.utils.flt)
        self.fake = SimpleNamespace(db=Mock(exists=Mock(return_value=True), count=Mock(return_value=1)), cache=self.cache, utils=utils, enqueue=Mock(),
                                    session=_dict(user='manager@example.invalid'), throw=Mock(side_effect=frappe.ValidationError))
        self.enterContext(patch.object(bulk_campaigns, 'frappe', self.fake))
        for name in ('require_access', 'whatsapp_channel', 'read'):
            self.enterContext(patch.object(bulk_campaigns, name))
        self.save = self.enterContext(patch.object(bulk_campaigns, 'internal_save'))
        self.enterContext(patch.object(bulk_campaigns, 'bulk', return_value=self.doc))
        self.enterContext(patch.object(bulk_campaigns, 'uploaded_file', return_value=self.file))
        self.enterContext(patch.object(bulk_campaigns.whatsapp, 'checked_client', return_value=(self.hub, {})))
        self.enterContext(patch.object(bulk_campaigns.whatsapp, 'failure_message', side_effect=str))
        self.prepare = self.enterContext(patch.object(bulk_campaigns.whatsapp, 'prepare',
                                                      side_effect=lambda operation, arguments: {**arguments, 'operation': operation}))
        self.enterContext(patch('relay_core.bulk_updates.open_reply_window'))

    def test_start_uploads_once_and_every_row_sends_the_media_id(self):
        bulk_campaigns.control('Offer', 'start')
        self.hub.execute.assert_called_once_with({'operation': 'messages.media_upload', 'media_type': 'image',
            'mime_type': 'image/png', 'filename': 'offer.png', 'content_base64': 'iVBORw0KGgo='})
        self.prepare.assert_called_once()
        self.assertEqual((self.doc.status, self.doc.media_id, self.doc.media_uploaded_at), ('Running', '555', self.NOW))
        rows = [_dict(destination=f'91987654320{i}', arguments=json.dumps({'values': {'text:Name': 'Asha',
                      'media_url': '/private/files/offer.png'}})) for i in range(3)]
        snapshot = json.loads(self.doc.arguments)
        messages = [bulk_campaigns.hub_message(self.doc, snapshot, row) for row in rows]
        self.assertEqual({m['media_id'] for m in messages}, {'555'})
        self.assertFalse([m for m in messages if 'media_url' in m])
        self.hub.execute.assert_called_once()

    def test_resume_reuploads_only_when_the_media_id_would_expire(self):
        self.doc.update(status='Paused', media_id='444', media_uploaded_at=self.NOW.replace(day=1))
        bulk_campaigns.control('Offer', 'resume')
        self.hub.execute.assert_not_called()
        self.assertEqual(self.doc.media_id, '444')
        self.doc.update(status='Paused', media_uploaded_at=frappe.utils.add_to_date(self.NOW, days=-30))
        bulk_campaigns.control('Offer', 'resume')
        self.hub.execute.assert_called_once()
        self.assertEqual((self.doc.media_id, self.doc.media_uploaded_at), ('555', self.NOW))

    def test_a_failed_upload_leaves_the_campaign_in_draft(self):
        self.hub.execute.side_effect = bulk_campaigns.whatsapp.HubError('Hub rejected', detail='mime type mismatch')
        for result in (None, {}):
            if result is not None:
                self.hub.execute.side_effect, self.hub.execute.return_value = None, result
            with self.subTest(result=result), self.assertRaises(frappe.ValidationError):
                bulk_campaigns.control('Offer', 'start')
        self.assertEqual(self.doc.status, 'Draft')
        self.assertIsNone(self.doc.media_id)
        self.save.assert_not_called()
        self.cache.lock.assert_not_called()
        self.fake.enqueue.assert_not_called()


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
        self.enterContext(patch.object(bulk_campaigns, 'endpoint_facts', return_value=({}, set())))
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
                patch.object(bulk_campaigns, 'enqueue') as enqueue, patch('relay_core.bulk_updates.recover'), \
                patch('relay_core.campaign_schedule.start_due'):
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
