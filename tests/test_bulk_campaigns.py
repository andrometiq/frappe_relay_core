"""Bulk campaign sheet parsing, Hub push batching, update contract and reply links."""
import csv
import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
import frappe
from frappe import _dict
from relay_core import bulk_campaigns, bulk_sheet, bulk_updates, inbound
from relay_core.hub import HubError

NAMED = {'name': 'winter_offer', 'language': 'en', 'parameter_format': 'NAMED', 'components': [
    {'type': 'HEADER', 'format': 'IMAGE'},
    {'type': 'BODY', 'text': 'Hi {{customer_name}}, {{discount}} off. Again {{customer_name}}'},
    {'type': 'BUTTONS', 'buttons': [{'type': 'URL', 'text': 'Shop', 'url': 'https://shop.example/{{1}}'},
                                    {'type': 'QUICK_REPLY', 'text': 'Stop'}]}]}
POSITIONAL = {'name': 'notice', 'language': 'en_US', 'components': [
    {'type': 'HEADER', 'format': 'TEXT', 'text': 'Hello {{1}}'}, {'type': 'BODY', 'text': '{{2}} and {{1}}'}]}


class SheetTests(unittest.TestCase):
    def test_template_fields_cover_media_named_positional_and_buttons(self):
        self.assertEqual([f['key'] for f in bulk_sheet.template_fields(NAMED)],
                         ['header_media', 'body:customer_name', 'body:discount', 'button:0'])
        self.assertEqual([f['key'] for f in bulk_sheet.template_fields(POSITIONAL)], ['header:1', 'body:1', 'body:2'])

    def test_components_follow_meta_shape(self):
        fields = bulk_sheet.template_fields(NAMED)
        values = {'header_media': 'https://cdn.example/a.jpg', 'body:customer_name': 'Asha',
                  'body:discount': '20%', 'button:0': 'winter'}
        self.assertEqual(bulk_sheet.build_components(fields, values), [
            {'type': 'header', 'parameters': [{'type': 'image', 'image': {'link': 'https://cdn.example/a.jpg'}}]},
            {'type': 'body', 'parameters': [{'type': 'text', 'text': 'Asha', 'parameter_name': 'customer_name'},
                                            {'type': 'text', 'text': '20%', 'parameter_name': 'discount'}]},
            {'type': 'button', 'sub_type': 'url', 'index': '0', 'parameters': [{'type': 'text', 'text': 'winter'}]}])

    def test_coupon_buttons_are_filled_and_unsupported_parts_refused(self):
        coupon = {'components': [{'type': 'BODY', 'text': 'Your code'},
                                 {'type': 'BUTTONS', 'buttons': [{'type': 'COPY_CODE', 'example': 'SAVE10'}]}]}
        fields = bulk_sheet.template_fields(coupon)
        self.assertEqual(fields, [{'key': 'button:0', 'label': 'Button coupon code', 'component': 'button',
                                   'index': 0, 'sub_type': 'copy_code'}])
        self.assertEqual(bulk_sheet.build_components(fields, {'button:0': 'SAVE10'}), [
            {'type': 'button', 'sub_type': 'copy_code', 'index': '0', 'parameters': [{'type': 'coupon_code', 'coupon_code': 'SAVE10'}]}])
        refused = {'OTP buttons': {'type': 'BUTTONS', 'buttons': [{'type': 'OTP', 'otp_type': 'COPY_CODE'}]},
                   'location header': {'type': 'HEADER', 'format': 'LOCATION'},
                   'carousel templates': {'type': 'CAROUSEL', 'cards': []}}
        for message, component in refused.items():
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                bulk_sheet.template_fields({'components': [component]})

    def test_create_refuses_unsupported_templates_with_the_reason(self):
        hub = Mock()
        hub.execute.return_value = {'data': [{'name': 'login_code', 'language': 'en', 'status': 'APPROVED',
                                              'components': [{'type': 'BUTTONS', 'buttons': [{'type': 'OTP'}]}]}]}
        def throw(message):
            raise frappe.ValidationError(message)
        fake = SimpleNamespace(db=Mock(exists=Mock(return_value=False)), utils=frappe.utils, throw=throw)
        with patch.object(bulk_campaigns, 'require_access'), patch.object(bulk_campaigns, 'whatsapp_channel', return_value='WA'), \
                patch.object(bulk_campaigns, 'frappe', fake), \
                patch.object(bulk_campaigns.whatsapp, 'checked_client', return_value=(hub, {})), \
                patch('relay_core.whatsapp_templates.overlay', side_effect=lambda page: page):
            with self.assertRaisesRegex(frappe.ValidationError, 'OTP buttons'):
                bulk_campaigns.create('Login codes', 'login_code', 'en')

    def test_sheet_numbers_use_the_shared_phone_helper(self):
        self.assertEqual(bulk_sheet.phone_number('98765 43210', 'IN'), '919876543210')
        self.assertEqual(bulk_sheet.phone_number('+91 98765-43210', ''), '919876543210')
        self.assertEqual(bulk_sheet.phone_number('0091 9876543210', ''), '919876543210')
        for bad in ('', '12345', 'call me', '9876543210'):
            self.assertIsNone(bulk_sheet.phone_number(bad, ''))

    def write(self, suffix, rows):
        handle, path = tempfile.mkstemp(suffix=suffix)
        os.close(handle)
        self.addCleanup(os.unlink, path)
        if suffix == '.csv':
            with open(path, 'w', newline='') as out:
                csv.writer(out).writerows(rows)
        else:
            from openpyxl import Workbook
            book = Workbook(write_only=True)
            sheet = book.create_sheet()
            for row in rows:
                sheet.append(row)
            book.save(path)
        return path

    def test_csv_and_xlsx_stream_with_row_numbers_and_skip_blank_rows(self):
        rows = [['Mobile', 'Customer Name', 'Image'], ['9876543210', 'Asha', 'https://cdn.example/a.jpg'],
                [None, None, None], [9876543211, 'Ravi', '']]
        for suffix in ('.csv', '.xlsx'):
            found = list(bulk_sheet.read_rows(self.write(suffix, rows)))
            self.assertEqual([number for number, _ in found], [2, 4])
            self.assertEqual(found[1][1]['Mobile'], '9876543211')
        with self.assertRaises(ValueError):
            list(bulk_sheet.read_rows(self.write('.csv', [['Mobile', 'Mobile'], ['1', '2']])))
        with self.assertRaises(ValueError):
            list(bulk_sheet.read_rows('/tmp/people.txt'))

    def test_mapping_suggestion_validation_and_row_problems(self):
        fields = bulk_sheet.template_fields(NAMED)
        header = ['Mobile', 'Customer_Name', 'Discount', 'Image', 'Code']
        suggested = bulk_sheet.suggest(header, fields)
        self.assertEqual(suggested['phone'], 'Mobile')
        self.assertEqual(suggested['fields']['body:customer_name'], 'Customer_Name')
        with self.assertRaises(ValueError):
            bulk_sheet.check_mapping(suggested, header, fields)  # button value is missing
        mapping = bulk_sheet.check_mapping(dict(suggested, fixed={'button:0': 'winter'}, extra=['Code']), header, fields)
        with self.assertRaises(ValueError):
            bulk_sheet.check_mapping(dict(mapping, fixed={'header_media': 'http://insecure.example/a.jpg'},
                                          fields={k: v for k, v in mapping['fields'].items() if k != 'header_media'}), header, fields)
        row = {'Mobile': '9876543210', 'Customer_Name': 'Asha', 'Discount': '20%', 'Image': 'https://cdn.example/a.jpg', 'Code': 'C1'}
        destination, values, problem = bulk_sheet.prepare_row(row, mapping, fields, 'IN')
        self.assertEqual((destination, problem), ('919876543210', None))
        self.assertEqual(values, {'values': {'header_media': 'https://cdn.example/a.jpg', 'body:customer_name': 'Asha',
                                             'body:discount': '20%', 'button:0': 'winter'}, 'extra': {'Code': 'C1'}})
        self.assertEqual(bulk_sheet.prepare_row(dict(row, Mobile='12'), mapping, fields, 'IN')[2], 'Invalid phone number')
        self.assertEqual(bulk_sheet.prepare_row(dict(row, Discount=''), mapping, fields, 'IN')[2], 'Missing Body value discount')
        self.assertIn('HTTPS', bulk_sheet.prepare_row(dict(row, Image='ftp://x/a.jpg'), mapping, fields, 'IN')[2])


class UpdateContractTests(unittest.TestCase):
    secret = 's' * 64
    row = {'id': 1, 'key': 'bulk-abc-2', 'state': 'submitted', 'message_id': 'wamid.one', 'status': 'delivered',
           'updated_at': '2026-10-25T10:00:00Z'}

    def check(self, rows, account='site-a', raw=None):
        raw = raw or json.dumps({'account': account, 'updates': rows}).encode()
        now = str(int(time.time()))
        signature = hmac.new(self.secret.encode(), now.encode() + b'.' + raw, hashlib.sha256).hexdigest()
        return inbound.validate_bulk_update_callback(raw, now, signature, self.secret, 'site-a')

    def test_accepts_full_batch_all_outbox_states_and_meta_errors(self):
        self.assertEqual(len(self.check([dict(self.row, id=i + 1) for i in range(500)])['updates']), 500)
        for state in inbound.BULK_STATES:
            self.check([dict(self.row, state=state, status='', message_id='')])
        failed = dict(self.row, status='failed', error={'code': 131049, 'title': 'Marketing cap', 'message': 'Not delivered'})
        self.assertEqual(self.check([failed])['updates'][0]['error']['code'], 131049)

    def test_rejects_malformed_rows(self):
        bad = [[], [dict(self.row, id=i + 1) for i in range(501)], [self.row, self.row], [dict(self.row, id=True)],
               [dict(self.row, key='bad key')], [dict(self.row, state='sent')], [dict(self.row, status='seen')],
               [dict(self.row, message_id='')], [dict(self.row, error={'code': -1})], [dict(self.row, extra=1)],
               [dict(self.row, error={'title': 'line\nbreak'})], [dict(self.row, error={'secret': 'x'})],
               [dict(self.row, updated_at='2026-10-25T10:00:00')], [{k: v for k, v in self.row.items() if k != 'status'}]]
        for rows in bad:
            with self.assertRaises(ValueError, msg=rows if len(rows) < 3 else len(rows)):
                self.check(rows)
        with self.assertRaises(ValueError):
            self.check([self.row], account='another-site')


class ApplyTests(unittest.TestCase):
    def test_status_mapping_rank_guard_and_reason(self):
        self.assertEqual(bulk_updates.target({'state': 'submitted', 'status': ''}), 'Sent')
        self.assertEqual(bulk_updates.target({'state': 'submitting', 'status': ''}), 'Queued')
        self.assertEqual(bulk_updates.target({'state': 'submitted', 'status': 'read'}), 'Read')
        self.assertEqual(bulk_updates.target({'state': 'rejected', 'status': ''}), 'Failed')
        self.assertNotIn('Delivered', bulk_updates.lower('Failed'))
        self.assertIn('Sent', bulk_updates.lower('Failed'))
        self.assertEqual(bulk_updates.lower('Queued'), ('Pending',))
        self.assertEqual(bulk_updates.reason({'code': 131026, 'title': 'Message undeliverable'}),
                         'Meta error 131026: Message undeliverable')

    def test_tally_counts_reached_states_and_replies(self):
        counts = bulk_updates.tally([('Pending', 2, 0), ('Skipped', 3, 0), ('Sent', 4, 0), ('Read', 5, 2), ('Failed', 1, 0)])
        self.assertEqual(counts, {'total': 12, 'skipped': 3, 'queued': 2, 'sent': 9, 'delivered': 5, 'read': 5,
                                  'failed': 1, 'replied': 2})

    def test_project_batch_uses_sql_guards_updates_the_timeline_and_marks_each_campaign_once(self):
        db = Mock()
        fake = SimpleNamespace(db=db, get_all=Mock(return_value=['Winter launch']))
        rows = [dict(UpdateContractTests.row, key='b'), dict(UpdateContractTests.row, id=2, key='a', state='rejected',
                status='', message_id='', error={'code': 132001, 'title': 'Template missing'})]
        with patch.object(bulk_updates, 'frappe', fake), patch.object(bulk_updates, 'changed') as changed, \
                patch.object(bulk_updates, 'connection_value', return_value='site-a'), \
                patch('relay_core.bulk_timeline.apply') as timeline:
            bulk_updates.project_batch(_dict(name='event', account='site-a'), rows)
            with self.assertRaises(ValueError):
                bulk_updates.project_batch(_dict(name='event', account='other'), rows)
        params = [call.args[1] for call in db.sql.call_args_list]
        self.assertEqual([p['key'] for p in params], ['a', 'b'])
        self.assertEqual((params[0]['status'], params[0]['code'], params[0]['failed']), ('Failed', 132001, True))
        self.assertEqual(params[1]['lower'], ('Pending', 'Queued', 'Uncertain', 'Cancelled', 'Sent', 'Failed'))
        self.assertEqual(timeline.call_args.args[0], [
            {'key': 'a', 'status': 'Failed', 'message_id': '', 'reason': 'Meta error 132001: Template missing'},
            {'key': 'b', 'status': 'Delivered', 'message_id': 'wamid.one', 'reason': ''}])
        changed.assert_called_once_with('Winter launch')

    def test_a_committed_change_enqueues_one_trailing_refresh_that_waits_out_the_throttle(self):
        cache, callbacks = FakeCache(), []
        db = SimpleNamespace(after_commit=SimpleNamespace(add=callbacks.append), commit=Mock())
        fake = SimpleNamespace(cache=cache, db=db, utils=frappe.utils, enqueue=Mock())
        with patch.object(bulk_updates, 'frappe', fake), patch.object(bulk_updates, 'recount', return_value={}) as recount, \
                patch.object(bulk_updates, 'publish') as publish, patch.object(bulk_updates.time, 'sleep') as sleep, \
                patch.object(bulk_updates.time, 'time', return_value=100.0):
            bulk_updates.changed('Winter launch')
            fake.enqueue.assert_not_called()  # Nothing before commit: a rollback leaves no mark.
            for callback in callbacks * 3:
                callback()
            self.assertEqual(fake.enqueue.call_count, 1)  # Later changes ride on the queued refresh.
            bulk_updates.refresh('Winter launch')
            sleep.assert_not_called()
            self.assertFalse(cache.sismember(bulk_updates.DIRTY, 'Winter launch'))
            callbacks[0]()  # A change after the refresh took the mark gets its own refresh.
            self.assertEqual(fake.enqueue.call_count, 2)
            bulk_updates.refresh('Winter launch')
            sleep.assert_called_once_with(3.0)  # Inside PROGRESS_SECONDS: waits, then still publishes.
            bulk_updates.recover()
            self.assertEqual(fake.enqueue.call_count, 2)  # Nothing left marked.
        self.assertEqual((publish.call_count, recount.call_count), (2, 2))
        self.assertTrue(db.commit.called)  # The count after the wait reads a fresh snapshot.

    def test_reply_links_by_context_then_number_and_is_gated(self):
        db = Mock()
        db.sql.side_effect = [[_dict(name='row-1', campaign='Winter launch')], None]
        fake = SimpleNamespace(db=db)
        row = {'id': 'wamid.reply', 'from': '919876543210', 'provider_context': {'reply_to_message_id': 'wamid.one'}}
        with patch.object(bulk_updates, 'frappe', fake), patch.object(bulk_updates, 'changed') as changed, \
                patch.object(bulk_updates, 'reply_window_open', return_value=True):
            self.assertEqual(bulk_updates.link_reply(row), 'row-1')
        self.assertEqual(db.sql.call_args_list[0].args[1], 'wamid.one')
        self.assertIn('replied_at IS NULL', db.sql.call_args_list[1].args[0])
        changed.assert_called_once_with('Winter launch')
        db.sql.reset_mock(side_effect=True)
        db.sql.side_effect = [[]]
        with patch.object(bulk_updates, 'frappe', fake), patch.object(bulk_updates, 'reply_window_open', return_value=True):
            self.assertIsNone(bulk_updates.link_reply(dict(row, provider_context={})))
        self.assertEqual(db.sql.call_args_list[0].args[1], '919876543210')
        fallback = db.sql.call_args_list[0].args[0]
        self.assertIn("r.attempted=1 AND r.status IN ('Pending', 'Queued', 'Uncertain', 'Sent', 'Delivered', 'Read')", fallback)
        self.assertNotIn('provider_id', fallback)  # A reply may arrive before Hub reports the provider ID.
        with patch.object(bulk_updates, 'reply_window_open', return_value=False):
            self.assertIsNone(bulk_updates.link_reply(row))


class ProjectionRoutingTests(unittest.TestCase):
    def test_bulk_update_event_routes_to_batch_apply_and_fails_closed(self):
        from relay_core.automation import projection
        rows = [UpdateContractTests.row]
        event = _dict(name='event', account='site-a', projection_status='Pending', payload=json.dumps({'bulk_updates': rows}))
        fake = SimpleNamespace(db=Mock(), get_doc=Mock(return_value=event))
        with patch.object(projection, 'frappe', fake), patch('relay_core.bulk_updates.project_batch') as apply:
            projection.project('event')
        apply.assert_called_once_with(event, rows)
        with patch.object(projection, 'frappe', fake), patch.object(projection, 'set_status') as status, \
                patch('relay_core.bulk_updates.project_batch', side_effect=ValueError('other account')):
            projection.project('event')
        status.assert_called_once_with('event', 'Failed')


class FakeCache:
    def __init__(self):
        self.values, self.sets = {}, {}

    def get_value(self, key):
        return self.values.get(key)

    def set_value(self, key, value, expires_in_sec=None):
        self.values[key] = value

    def delete_value(self, key):
        self.values.pop(key, None)

    def sadd(self, key, *values):
        self.sets.setdefault(key, set()).update(values)

    def srem(self, key, *values):
        self.sets.get(key, set()).difference_update(values)

    def sismember(self, key, value):
        return value in self.sets.get(key, set())

    def make_key(self, key):
        return key

    def execute_command(self, command, key, value):
        assert command == 'SADD'
        added = value not in self.sets.get(key, set())
        self.sadd(key, value)
        return int(added)

    def smembers(self, key):
        return {value.encode() for value in self.sets.get(key, set())}

    def lock(self, *args, **kwargs):
        return MagicMock()


UTILS = SimpleNamespace(cint=frappe.utils.cint, flt=frappe.utils.flt, now_datetime=lambda: '2026-10-26 10:00:00')
FAILURE_MESSAGE = bulk_campaigns.whatsapp.failure_message


def manager_text(error):
    with patch.object(bulk_campaigns.whatsapp, 'frappe', SimpleNamespace(get_roles=lambda: ['Relay Communication Manager'])):
        return FAILURE_MESSAGE(error)


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.cache = FakeCache()
        self.db = Mock()
        self.db.get_value.return_value = 'Running'
        self.fake = SimpleNamespace(db=self.db, utils=UTILS, cache=self.cache, enqueue=Mock())
        self.enterContext(patch.object(bulk_campaigns, 'frappe', self.fake))
        self.timeline = self.enterContext(patch('relay_core.bulk_timeline.record'))
        self.reserve = self.enterContext(patch('relay_core.bulk_timeline.reserve', return_value=41))
        self.enterContext(patch('relay_core.bulk_updates.changed'))
        self.sleep = self.enterContext(patch.object(bulk_campaigns.time, 'sleep'))
        self.doc = _dict(name='Winter launch', template_name='notice', language='en_US', status='Running',
                         arguments=json.dumps({'template': POSITIONAL, 'fields': [{'key': 'body:1', 'component': 'body', 'name': None}]}))

    def rows(self, count, start=0):
        return [_dict(name=f'r{i}', request_key=f'bulk-k-{i}', destination='9198765432%02d' % (i % 100),
                      arguments=json.dumps({'values': {'body:1': 'Asha'}})) for i in range(start, start + count)]

    def hub(self, queued=60, states=None):
        hub = Mock()
        hub.call_tool.side_effect = lambda tool, args: {'queued': queued, 'messages_per_second': 100, 'deliveries': [
            {'id': str(i), 'key': m['key'], 'state': (states or {}).get(i, 'queued')} for i, m in enumerate(args['messages'])]}
        return hub

    def selects(self, batches):
        self.db.sql.side_effect = lambda query, *args, **kwargs: batches.pop(0) if query.lstrip().startswith('SELECT') else None

    def test_push_sends_fifty_per_call_with_stable_keys_and_records_the_timeline(self):
        self.selects([self.rows(50), self.rows(10, 50), []])
        hub = self.hub(states={1: 'rejected'})
        with patch.object(bulk_campaigns.whatsapp, 'client', return_value=hub):
            self.assertFalse(bulk_campaigns.push(self.doc, time.monotonic() + 30))
        calls = hub.call_tool.call_args_list
        self.assertEqual([len(c.args[1]['messages']) for c in calls], [50, 10])
        first = calls[0].args[1]['messages'][0]
        self.assertEqual(first['key'], 'bulk-k-0')
        self.assertEqual(first['message'], {'operation': 'templates.send', 'to': '919876543200', 'name': 'notice',
                         'language': 'en_US', 'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': 'Asha'}]}]})
        updates = [c for c in self.db.sql.call_args_list if c.args[0].lstrip().startswith('UPDATE')]
        attempted = [c.args[1][0] for c in updates if 'SET attempted=1' in c.args[0]]
        self.assertEqual([len(names) for names in attempted], [50, 10])
        self.assertEqual(len(updates) - len(attempted), 60)
        recorded = self.timeline.call_args_list[0].args[2]
        self.assertEqual(len(recorded), 49)  # The rejected row never reaches the timeline.
        self.assertNotIn('bulk-k-1', [row.request_key for row in recorded])

    def test_rows_are_attempted_and_committed_before_hub_sends_them(self):
        order = []
        self.selects([self.rows(2), []])
        self.db.commit.side_effect = lambda: order.append('commit')
        hub = self.hub()
        send = hub.call_tool.side_effect
        hub.call_tool.side_effect = lambda tool, args: order.append('hub') or send(tool, args)
        sql = self.db.sql.side_effect
        self.db.sql.side_effect = lambda query, *a, **k: (order.append('attempted') if 'attempted=1 WHERE' in query else None) or sql(query, *a, **k)
        with patch.object(bulk_campaigns.whatsapp, 'client', return_value=hub):
            bulk_campaigns.push(self.doc, time.monotonic() + 30)
        self.assertEqual(order[order.index('attempted'):order.index('hub') + 1], ['attempted', 'commit', 'hub'])

    def test_names_are_reserved_after_hub_admits_and_before_the_batch_locks_its_rows(self):
        order = []
        self.selects([self.rows(3), []])
        self.reserve.side_effect = lambda count: order.append(('reserve', count)) or 41
        sql = self.db.sql.side_effect
        self.db.sql.side_effect = lambda query, *a, **k: (order.append('admit') if 'SET status=%s' in query else None) or sql(query, *a, **k)
        self.timeline.side_effect = lambda *args: order.append(('record', args[3]))
        hub = self.hub()
        send = hub.call_tool.side_effect
        hub.call_tool.side_effect = lambda tool, args: order.append('hub') or send(tool, args)
        with patch.object(bulk_campaigns.whatsapp, 'client', return_value=hub):
            bulk_campaigns.push(self.doc, time.monotonic() + 30)
        self.assertEqual(order, ['hub', ('reserve', 3), 'admit', 'admit', 'admit', ('record', 41)])

    def test_a_later_accepted_batch_clears_the_retry_error(self):
        self.selects([self.rows(5), []])
        self.doc.last_error = 'Hub rejected this operation: account queue is full'
        with patch.object(bulk_campaigns.whatsapp, 'client', return_value=self.hub()):
            bulk_campaigns.push(self.doc, time.monotonic() + 30)
        self.db.set_value.assert_called_once_with('Relay Campaign', 'Winter launch', 'last_error', '', update_modified=False)

    def test_slice_ends_at_its_deadline_and_reports_rows_left(self):
        self.selects([self.rows(50)])
        with patch.object(bulk_campaigns.whatsapp, 'client', return_value=self.hub()), \
                patch.object(bulk_campaigns.time, 'monotonic', side_effect=[0, 100]):
            self.assertTrue(bulk_campaigns.push(self.doc, 30))

    def test_backpressure_waits_inside_the_slice_until_the_low_water_mark(self):
        self.selects([self.rows(50), self.rows(50, 50), []])
        clock = iter([1000.0, 1000.0, 1004.0, 1009.5, 1010.0, 1010.0, 1030.0])
        with patch.object(bulk_campaigns.whatsapp, 'client', return_value=self.hub(queued=1500)) as client, \
                patch.object(bulk_campaigns.time, 'time', side_effect=lambda: next(clock)):
            self.assertFalse(bulk_campaigns.push(self.doc, time.monotonic() + 30))
        self.assertEqual(client.return_value.call_tool.call_count, 2)  # No scheduler or Hub update needed.
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [1, 0.5])  # (1500 - 500) / 100 s, a second at a time.

    def test_hub_failure_shows_the_reason_backs_off_and_retries_the_same_rows_in_the_slice(self):
        self.selects([self.rows(1), self.rows(1), []])
        hub = Mock()
        error = HubError('Hub could not complete', detail='WhatsApp rejected this request (code 132001): Template missing')
        hub.call_tool.side_effect = [error, {'queued': 1, 'deliveries': [{'id': '7', 'key': 'bulk-k-0', 'state': 'queued'}]}]
        clock = iter([1000.0, 1000.0, 1006.0, 1006.0])
        with patch.object(bulk_campaigns.whatsapp, 'client', return_value=hub), \
                patch.object(bulk_campaigns.time, 'time', side_effect=lambda: next(clock, 1006.0)), \
                patch.object(bulk_campaigns.whatsapp, 'failure_message', side_effect=manager_text):
            self.assertFalse(bulk_campaigns.push(self.doc, time.monotonic() + 30))
        self.assertEqual(self.db.set_value.call_args_list[0].args[3],
                         'Hub rejected this operation: WhatsApp rejected this request (code 132001): Template missing')
        self.assertEqual(self.db.set_value.call_args_list[-1].args[3], '')  # The retry was accepted.
        self.assertEqual([len(c.args[1]['messages']) for c in hub.call_tool.call_args_list], [1, 1])
        self.assertNotIn(bulk_campaigns.RETRIES + 'Winter launch', self.cache.values)

    def test_retry_backs_off_to_a_minute(self):
        delays = []
        with patch.object(bulk_campaigns, 'wait', side_effect=lambda name, seconds: delays.append(seconds)):
            for _ in range(6):
                bulk_campaigns.retry_later(self.doc, 'Hub is unavailable')
        self.assertEqual(delays, [5, 10, 20, 40, 60, 60])
        self.assertEqual(self.doc.last_error, 'Hub is unavailable')

    def test_send_job_continues_under_the_other_job_id_and_cancels_after_a_cancel_mid_slice(self):
        self.fake.get_doc = Mock(return_value=self.doc)
        with patch.object(bulk_campaigns, 'push', return_value=True), patch.object(bulk_campaigns, 'cancel_remaining') as cancel:
            bulk_campaigns.send_job('Winter launch', step=3)
            cancel.assert_not_called()
        ids = [c.kwargs['job_id'] for c in self.fake.enqueue.call_args_list]
        self.assertEqual(ids, ['relay-bulk-send_job:Winter launch:0'])
        self.assertEqual(self.fake.enqueue.call_args.kwargs['step'], 4)
        self.fake.enqueue.reset_mock()
        self.db.get_value.return_value = 'Cancelling'  # The manager cancelled while this slice pushed.
        with patch.object(bulk_campaigns, 'push', return_value=False), \
                patch.object(bulk_campaigns, 'cancel_remaining', return_value=False) as cancel:
            bulk_campaigns.send_job('Winter launch')
        cancel.assert_called_once()
        self.fake.enqueue.assert_not_called()

    def test_admission_mapping_returns_the_rows_hub_holds(self):
        held = bulk_campaigns.admit(self.rows(3), [{'key': 'bulk-k-0', 'id': '7', 'state': 'queued'},
                                    {'key': 'bulk-k-1', 'id': '', 'state': 'rejected', 'error': 'valid recipient required'}])
        params = [c.args[1] for c in self.db.sql.call_args_list]
        self.assertEqual([(p[0], p[1]) for p in params], [('Queued', '7'), ('Failed', ''), ('Uncertain', '')])
        self.assertEqual(params[1][2], 'valid recipient required')
        self.assertEqual(held, {'bulk-k-0', 'bulk-k-2'})

    def test_cancel_pages_through_every_queued_row_and_resumes_after_a_deadline(self):
        pages = [[_dict(name=f'q{i:04d}', delivery_id=str(i), request_key=f'k{i}') for i in range(start, start + size)]
                 for start, size in ((0, 1000), (1000, 500))] + [[]]
        self.fake.get_all = Mock(side_effect=lambda *args, **kwargs: pages.pop(0))
        hub = Mock()
        hub.call_tool.side_effect = lambda tool, args: {'cancelled': int(args['cancel_id']) % 2 == 0}
        with patch.object(bulk_campaigns.whatsapp, 'client', return_value=hub), patch.object(bulk_campaigns, 'in_chunks'), \
                patch('relay_core.bulk_timeline.cancelled') as cancelled:
            self.assertFalse(bulk_campaigns.cancel_remaining(self.doc, time.monotonic() + 30))
        self.assertEqual(hub.call_tool.call_count, 1500)
        self.assertEqual(cancelled.call_count, 750)
        afters = [c.kwargs['filters']['name'][1] for c in self.fake.get_all.call_args_list]
        self.assertEqual(afters, ['', 'q0999', 'q1499'])
        self.assertEqual(self.db.set_value.call_args.args[2]['status'], 'Cancelled')
        pages[:] = [[_dict(name='q2000', delivery_id='2000', request_key='k')]]
        self.fake.get_all = Mock(side_effect=lambda *args, **kwargs: pages.pop(0))
        with patch.object(bulk_campaigns.whatsapp, 'client', return_value=hub), patch.object(bulk_campaigns, 'in_chunks'):
            self.assertTrue(bulk_campaigns.cancel_remaining(self.doc, time.monotonic() - 1))

    def test_cancel_refused_by_hub_stays_cancelling_with_the_reason_and_claims_nothing(self):
        self.fake.get_all = Mock(return_value=[_dict(name='q0001', delivery_id='1', request_key='k1')])
        hub = Mock()
        hub.call_tool.side_effect = HubError('Hub operation was rejected', detail='deliveries:cancel scope required')
        with patch.object(bulk_campaigns.whatsapp, 'client', return_value=hub), patch.object(bulk_campaigns, 'in_chunks'), \
                patch.object(bulk_campaigns.whatsapp, 'failure_message', side_effect=manager_text), \
                patch('relay_core.bulk_timeline.cancelled') as cancelled:
            self.assertTrue(bulk_campaigns.cancel_remaining(self.doc, time.monotonic() + 0.05))
        cancelled.assert_not_called()
        self.assertFalse([c for c in self.db.sql.call_args_list if "SET status='Cancelled'" in c.args[0]])
        self.assertNotIn({'status': 'Cancelled'}, [c.args[2] for c in self.db.set_value.call_args_list if isinstance(c.args[2], dict)])
        self.assertTrue(self.doc.last_error.startswith(bulk_campaigns.CANCEL_REFUSED))
        self.assertIn('deliveries:cancel scope required', self.doc.last_error)
        self.assertNotIn(bulk_campaigns.CANCEL_AFTER + 'Winter launch', self.cache.values)  # The refused row is tried again.

    def test_cancel_moves_past_a_row_hub_already_sends(self):
        pages = [[_dict(name='q0001', delivery_id='1', request_key='k1')], []]
        self.fake.get_all = Mock(side_effect=lambda *args, **kwargs: pages.pop(0))
        hub = Mock()
        hub.call_tool.side_effect = HubError('Hub operation was rejected', detail=bulk_campaigns.NOT_QUEUED)
        with patch.object(bulk_campaigns.whatsapp, 'client', return_value=hub), patch.object(bulk_campaigns, 'in_chunks'):
            self.assertFalse(bulk_campaigns.cancel_remaining(self.doc, time.monotonic() + 30))
        self.assertFalse([c for c in self.db.sql.call_args_list if "SET status='Cancelled'" in c.args[0]])
        self.assertEqual(self.db.set_value.call_args.args[2]['status'], 'Cancelled')

    def test_campaign_apis_deny_without_manager_access(self):
        for call in (lambda: bulk_campaigns.create('Winter launch Oct 2026', 'notice', 'en_US'),
                     lambda: bulk_campaigns.read('Winter launch Oct 2026'),
                     lambda: bulk_campaigns.control('Winter launch Oct 2026', 'start')):
            with patch.object(bulk_campaigns, 'require_access', side_effect=frappe.PermissionError):
                with self.assertRaises(frappe.PermissionError):
                    call()


class ControlTests(unittest.TestCase):
    def test_start_checks_the_template_before_taking_the_lock_and_rechecks_status_inside(self):
        order = []
        cache = SimpleNamespace(lock=MagicMock(side_effect=lambda *a, **k: order.append('lock') or MagicMock()), delete_value=Mock())
        fake = SimpleNamespace(db=Mock(exists=Mock(return_value=True)), cache=cache, utils=UTILS, enqueue=Mock(),
                               session=_dict(user='manager@example.invalid'), throw=Mock(side_effect=frappe.ValidationError))
        doc = _dict(name='Winter launch', status='Draft', channel='WA', template_name='notice', language='en', last_error='',
                    reply_window_hours=72)
        hub = Mock()
        with patch.object(bulk_campaigns, 'frappe', fake), patch.object(bulk_campaigns, 'require_access'), \
                patch.object(bulk_campaigns, 'bulk', return_value=doc) as bulk, patch.object(bulk_campaigns, 'whatsapp_channel'), \
                patch.object(bulk_campaigns.whatsapp, 'checked_client', side_effect=lambda: order.append('hub') or (hub, {})), \
                patch.object(bulk_campaigns, 'approved_template'), patch.object(bulk_campaigns, 'internal_save'), \
                patch.object(bulk_campaigns, 'read'), patch('relay_core.bulk_updates.open_reply_window'):
            bulk_campaigns.control('Winter launch', 'start')
            self.assertEqual(order, ['hub', 'lock'])
            self.assertEqual(bulk.call_count, 2)
            self.assertEqual(doc.status, 'Running')
            doc.update(status='Draft', last_error='Row 9 has an unreadable cell')
            with self.assertRaises(frappe.ValidationError):
                bulk_campaigns.control('Winter launch', 'start')
            self.assertIn('import', fake.throw.call_args.args[0])


    def test_resume_works_when_every_row_is_already_in_hub(self):
        fake = SimpleNamespace(db=Mock(exists=Mock(return_value=False)), cache=FakeCache(), utils=UTILS,
                               enqueue=Mock(), session=_dict(user='manager@example.invalid'), throw=Mock(side_effect=frappe.ValidationError))
        doc = _dict(name='Winter launch', status='Paused', channel='WA', template_name='notice', language='en', last_error='',
                    reply_window_hours=72, started_at='2026-10-26 09:00:00')
        with patch.object(bulk_campaigns, 'frappe', fake), patch.object(bulk_campaigns, 'require_access'), \
                patch.object(bulk_campaigns, 'bulk', return_value=doc), patch.object(bulk_campaigns, 'whatsapp_channel'), \
                patch.object(bulk_campaigns.whatsapp, 'checked_client', return_value=(Mock(), {})), \
                patch.object(bulk_campaigns, 'approved_template'), patch.object(bulk_campaigns, 'internal_save'), \
                patch.object(bulk_campaigns, 'read'), patch('relay_core.bulk_updates.open_reply_window'):
            bulk_campaigns.wait('Winter launch', 60)
            bulk_campaigns.control('Winter launch', 'resume')
            fake.throw.assert_not_called()
            self.assertNotIn(bulk_campaigns.WAIT + 'Winter launch', fake.cache.values)  # Tries Hub now.
            self.assertEqual(doc.status, 'Running')  # The slice finds nothing pending; recount completes it.
            self.assertEqual(fake.enqueue.call_args.kwargs['job_id'], 'relay-bulk-send_job:Winter launch:control')
            doc.status = 'Draft'
            with self.assertRaises(frappe.ValidationError):
                bulk_campaigns.control('Winter launch', 'start')
            self.assertIn('at least one valid row', fake.throw.call_args.args[0])


class ImportTests(unittest.TestCase):
    def test_import_marks_duplicates_and_opt_outs_and_inserts_in_chunks(self):
        fields = bulk_sheet.template_fields(POSITIONAL)
        doc = _dict(name='Winter launch', status='Importing', channel='WhatsApp-001', country='IN', source_file='/private/files/a.csv',
                    column_map=json.dumps({'phone': 'Mobile', 'fields': {'header:1': 'Name', 'body:1': 'Name', 'body:2': 'Offer'}, 'fixed': {}}),
                    arguments=json.dumps({'fields': fields}))
        rows = [(2, {'Mobile': '9876543210', 'Name': 'Asha', 'Offer': 'Ten'}), (3, {'Mobile': '+919876543210', 'Name': 'Asha', 'Offer': 'Ten'}),
                (4, {'Mobile': '98765', 'Name': 'Ravi', 'Offer': 'Ten'}), (5, {'Mobile': '9876543211', 'Name': 'Mani', 'Offer': ''}),
                (6, {'Mobile': '9876543212', 'Name': 'Opted', 'Offer': 'Ten'})]
        db = Mock()
        fake = SimpleNamespace(db=db, get_doc=Mock(return_value=doc), session=_dict(user='manager@example.invalid'),
                               utils=SimpleNamespace(now=lambda: '2026-10-25 10:00:00'))
        with patch.object(bulk_campaigns, 'frappe', fake), patch.object(bulk_campaigns, 'in_chunks'), \
                patch.object(bulk_campaigns, 'source_path', return_value='/tmp/a.csv'), \
                patch.object(bulk_campaigns.bulk_sheet, 'read_rows', return_value=iter(rows)), \
                patch.object(bulk_campaigns, 'endpoint_facts', return_value=({'919876543210': 'Contact Asha'}, {'919876543212'})), \
                patch.object(bulk_campaigns, 'internal_save'), patch('relay_core.bulk_updates.changed') as changed:
            bulk_campaigns.import_job('Winter launch')
        values = db.bulk_insert.call_args.args[2]
        self.assertEqual([(v[10], v[14]) for v in values], [('Pending', ''), ('Skipped', 'Duplicate number'),
                         ('Skipped', 'Invalid phone number'), ('Skipped', 'Missing Body value 2'), ('Skipped', 'Opted out')])
        self.assertEqual(values[0][7], 'Contact Asha')
        self.assertEqual(values[0][0], bulk_campaigns.recipient_key('Winter launch', 2))
        self.assertEqual((doc.status, doc.last_error), ('Draft', ''))
        changed.assert_called_once_with('Winter launch')

    def test_failed_import_removes_partial_rows_after_rollback(self):
        doc = _dict(name='Winter launch', status='Importing', channel='WA', country='IN', source_file='/private/files/a.csv',
                    column_map=json.dumps({'phone': 'Mobile', 'fields': {}, 'fixed': {}}), arguments=json.dumps({'fields': []}))
        order = []
        db = Mock(rollback=Mock(side_effect=lambda: order.append('rollback')))
        fake = SimpleNamespace(db=db, get_doc=Mock(return_value=doc))

        def rows(path):
            yield 2, {'Mobile': '9876543210'}
            raise ValueError('A campaign supports at most 100000 rows')
        with patch.object(bulk_campaigns, 'frappe', fake), \
                patch.object(bulk_campaigns, 'remove_unsent', side_effect=lambda name: order.append('remove')), \
                patch.object(bulk_campaigns, 'source_path', return_value='/tmp/a.csv'), \
                patch.object(bulk_campaigns.bulk_sheet, 'read_rows', side_effect=rows), \
                patch.object(bulk_campaigns, 'internal_save'), patch('relay_core.bulk_updates.changed'):
            bulk_campaigns.import_job('Winter launch')
        self.assertEqual(order, ['remove', 'rollback', 'remove'])
        self.assertEqual((doc.status, doc.last_error), ('Draft', 'A campaign supports at most 100000 rows'))

    def test_opt_out_outlives_the_contact_link(self):
        number = '919876543210'
        key = hashlib.sha256(('WA:' + number).encode()).hexdigest()

        def get_all(doctype, **kwargs):
            if doctype == 'Relay Contact Endpoint':
                self.assertNotIn('verified', kwargs['filters'])
                return [_dict(name='E-OLD', endpoint_key=key, relay_contact='RELAY-CON-A', verified=0)]
            if doctype == 'Relay Channel Preference':
                return ['E-OLD']
            raise AssertionError(doctype)
        with patch.object(bulk_campaigns, 'frappe', SimpleNamespace(get_all=Mock(side_effect=get_all))):
            contacts, opted_out = bulk_campaigns.endpoint_facts('WA', [number])
        self.assertEqual((contacts, opted_out), ({}, {number}))


class TimelineTests(unittest.TestCase):
    def test_admitted_rows_with_a_relay_contact_become_one_rendered_batch(self):
        from relay_core import bulk_timeline
        doc = _dict(name='Winter launch', channel='WA', template_name='notice', language='en_US')
        template = dict(POSITIONAL, components=[*POSITIONAL['components'], {'type': 'FOOTER', 'text': 'Reply STOP to opt out'},
                        {'type': 'BUTTONS', 'buttons': [{'type': 'QUICK_REPLY', 'text': 'Stop'}]}])
        components = [{'type': 'header', 'parameters': [{'type': 'text', 'text': 'Asha'}]},
                      {'type': 'body', 'parameters': [{'type': 'text', 'text': 'Asha'}, {'type': 'text', 'text': 'Ten'}]}]
        rows = [_dict(request_key=f'bulk-k-{i}', destination=f'91987654321{i}', components=components) for i in range(3)]
        db = Mock()
        fake = SimpleNamespace(db=db, session=_dict(user='manager@example.invalid'), _dict=_dict, publish_realtime=Mock(),
                               get_all=Mock(return_value=[]),
                               utils=SimpleNamespace(now_datetime=lambda: '2026-10-26 10:00:00'),
                               realtime=SimpleNamespace(get_doctype_room=lambda doctype: 'doctype:' + doctype))
        order = []
        db.sql.side_effect = lambda query, values: order.append('lock contacts')
        fake.get_all.side_effect = lambda *args, **kwargs: order.append('read') or []
        with patch.object(bulk_timeline, 'frappe', fake), \
                patch('relay_core.whatsapp_receipts.lock_endpoints', return_value={'919876543210': 'RELAY-CON-A', '919876543212': 'RELAY-CON-B'}), \
                patch('relay_core.inbox.message_created') as activity:
            bulk_timeline.record(doc, {'template': template}, rows, 41)
        self.assertEqual(order, ['lock contacts', 'read'])  # Snapshot isolation refuses a lock taken after a read.
        self.assertIn('FOR UPDATE', db.sql.call_args.args[0])
        self.assertEqual(sorted(db.sql.call_args.args[1][0]), ['RELAY-CON-A', 'RELAY-CON-B'])
        values = db.bulk_insert.call_args.args[2]
        self.assertTrue(db.bulk_insert.call_args.kwargs['ignore_duplicates'])
        self.assertEqual([(v[0], v[6], v[16]) for v in values], [('RELAY-MSG-0000000041', 'RELAY-CON-A', 'bulk-k-0'),
                                                                 ('RELAY-MSG-0000000042', 'RELAY-CON-B', 'bulk-k-2')])
        data = json.loads(values[0][12])
        self.assertEqual(values[0][10], 'Ten and Asha')
        self.assertEqual((data['campaign'], data['template']['header'], data['template']['footer'], data['template']['buttons']),
                         ('Winter launch', 'Hello Asha', 'Reply STOP to opt out', ['Stop']))
        self.assertEqual(activity.call_count, 2)
        fake.publish_realtime.assert_called_once_with('relay_changed', {'kind': 'messages'}, room='doctype:Relay Message', after_commit=True)

    def test_names_are_reserved_in_a_transaction_of_their_own(self):
        from relay_core import bulk_timeline
        order = []
        db = Mock()
        db.commit.side_effect = lambda: order.append('commit')
        db.sql.side_effect = lambda query, values: order.append(('add', values))
        with patch.object(bulk_timeline, 'frappe', SimpleNamespace(db=db)), \
                patch.object(bulk_timeline, 'getseries', side_effect=lambda key, digits: order.append('lock') or '0000000041'):
            self.assertEqual(bulk_timeline.reserve(50), 41)
        self.assertEqual(order, ['commit', 'lock', ('add', (49, 'RELAY-MSG-')), 'commit'])

    def test_bulk_updates_move_timeline_messages_forward_with_quote_keys(self):
        from relay_core import bulk_timeline
        from relay_core.message_updates import provider_key
        db = Mock()
        messages = [_dict(name='MSG-A', source_key='a', channel='WA', sender_endpoint='919876543210'),
                    _dict(name='MSG-B', source_key='b', channel='WA', sender_endpoint='919876543211')]
        fake = SimpleNamespace(db=db, get_all=Mock(return_value=messages), publish_realtime=Mock(),
                               realtime=SimpleNamespace(get_doctype_room=lambda doctype: 'doctype:' + doctype))
        with patch.object(bulk_timeline, 'frappe', fake):
            bulk_timeline.apply([{'key': 'a', 'status': 'Read', 'message_id': 'wamid.a', 'reason': ''},
                                 {'key': 'b', 'status': 'Cancelled', 'message_id': '', 'reason': ''},
                                 {'key': 'c', 'status': 'Queued', 'message_id': '', 'reason': ''}])
        first, second = [call.args[1] for call in db.sql.call_args_list]
        self.assertEqual((first['status'], first['id'], first['key'], first['lower']),
                         ('Read', 'wamid.a', provider_key('WA', '919876543210', 'wamid.a'), ('Pending', 'Sent', 'Failed', 'Delivered')))
        self.assertEqual((second['status'], second['error'], second['lower']), ('Failed', 'Cancelled before sending', ('Pending', 'Sent')))
        fake.publish_realtime.assert_called_once()


if __name__ == '__main__':
    unittest.main()
