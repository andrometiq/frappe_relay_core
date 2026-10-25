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
from unittest.mock import Mock, patch
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

    def test_project_batch_uses_sql_guards_and_refreshes_each_campaign_once(self):
        db = Mock()
        fake = SimpleNamespace(db=db, get_all=Mock(return_value=['Winter launch']))
        rows = [dict(UpdateContractTests.row, key='b'), dict(UpdateContractTests.row, id=2, key='a', state='rejected',
                status='', message_id='', error={'code': 132001, 'title': 'Template missing'})]
        with patch.object(bulk_updates, 'frappe', fake), patch.object(bulk_updates, 'changed') as changed, \
                patch.object(bulk_updates, 'connection_value', return_value='site-a'):
            bulk_updates.project_batch(_dict(name='event', account='site-a'), rows)
            with self.assertRaises(ValueError):
                bulk_updates.project_batch(_dict(name='event', account='other'), rows)
        params = [call.args[1] for call in db.sql.call_args_list]
        self.assertEqual([p['key'] for p in params], ['a', 'b'])
        self.assertEqual((params[0]['status'], params[0]['code'], params[0]['failed']), ('Failed', 132001, True))
        self.assertEqual(params[1]['lower'], ('Pending', 'Queued', 'Uncertain', 'Cancelled', 'Sent', 'Failed'))
        changed.assert_called_once_with('Winter launch')

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


class SenderTests(unittest.TestCase):
    def rows(self, count, start=0):
        return [_dict(name=f'r{i}', request_key=f'bulk-k-{i}', destination='9198765432%02d' % (i % 100),
                      arguments=json.dumps({'values': {'body:1': 'Asha'}})) for i in range(start, start + count)]

    def test_push_sends_fifty_per_call_with_stable_keys_and_stops_when_done(self):
        doc = _dict(name='Winter launch', template_name='notice', language='en_US',
                    arguments=json.dumps({'fields': [{'key': 'body:1', 'component': 'body', 'name': None}]}))
        db = Mock()
        db.get_value.return_value = 'Running'
        db.sql.side_effect = lambda query, *args, **kwargs: self.batches.pop(0) if query.lstrip().startswith('SELECT') else None
        self.batches = [self.rows(50), self.rows(10, 50), []]
        hub = Mock()
        hub.call_tool.side_effect = lambda tool, args: {'deliveries': [{'id': str(i), 'key': m['key'], 'state': 'queued'}
                                                                       for i, m in enumerate(args['messages'])], 'queued': 60}
        with patch.object(bulk_campaigns, 'frappe', SimpleNamespace(db=db, utils=frappe.utils)), \
                patch.object(bulk_campaigns.whatsapp, 'client', return_value=hub), \
                patch('relay_core.bulk_updates.changed'):
            bulk_campaigns.push(doc, time.monotonic() + 30)
        calls = hub.call_tool.call_args_list
        self.assertEqual([len(c.args[1]['messages']) for c in calls], [50, 10])
        first = calls[0].args[1]['messages'][0]
        self.assertEqual(first['key'], 'bulk-k-0')
        self.assertEqual(first['message'], {'operation': 'templates.send', 'to': '919876543200', 'name': 'notice',
                         'language': 'en_US', 'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': 'Asha'}]}]})
        updates = [c for c in db.sql.call_args_list if c.args[0].lstrip().startswith('UPDATE')]
        self.assertEqual(len(updates), 60)
        self.assertEqual(updates[0].args[1][0], 'Queued')

    def test_hub_failure_records_issue_and_keeps_rows_pending(self):
        doc = _dict(name='Winter launch', template_name='notice', language='en_US', arguments=json.dumps({'fields': []}))
        db = Mock()
        db.get_value.return_value = 'Running'
        db.sql.return_value = self.rows(1)
        hub = Mock()
        hub.call_tool.side_effect = HubError('Hub could not complete', detail='WhatsApp rejected this request (code 132001): Template missing')
        roles = SimpleNamespace(get_roles=lambda: ['Relay Communication Manager'])
        with patch.object(bulk_campaigns, 'frappe', SimpleNamespace(db=db, utils=frappe.utils)), \
                patch.object(bulk_campaigns.whatsapp, 'client', return_value=hub), patch.object(bulk_campaigns.whatsapp, 'frappe', roles):
            bulk_campaigns.push(doc, time.monotonic() + 30)
        db.set_value.assert_called_once()
        self.assertEqual(db.set_value.call_args.args[3],
                         'Hub rejected this operation: WhatsApp rejected this request (code 132001): Template missing')
        self.assertFalse([c for c in db.sql.call_args_list if c.args[0].lstrip().startswith('UPDATE')])

    def test_admission_mapping_and_backpressure(self):
        db = Mock()
        rows = self.rows(3)
        with patch.object(bulk_campaigns, 'frappe', SimpleNamespace(db=db)):
            bulk_campaigns.admit(rows, [{'key': 'bulk-k-0', 'id': '7', 'state': 'queued'},
                                        {'key': 'bulk-k-1', 'id': '', 'state': 'rejected', 'error': 'valid recipient required'}])
        params = [c.args[1] for c in db.sql.call_args_list]
        self.assertEqual([(p[0], p[1]) for p in params], [('Queued', '7'), ('Failed', ''), ('Uncertain', '')])
        self.assertEqual(params[1][2], 'valid recipient required')
        with patch.object(bulk_campaigns.time, 'sleep') as sleep:
            bulk_campaigns.pause({'queued': 100})
            sleep.assert_not_called()
            bulk_campaigns.pause({'queued': 750, 'messages_per_second': 100})
            sleep.assert_called_once_with(5.0)

    def test_campaign_apis_deny_without_manager_access(self):
        for call in (lambda: bulk_campaigns.create('Winter launch Oct 2026', 'notice', 'en_US'),
                     lambda: bulk_campaigns.read('Winter launch Oct 2026'),
                     lambda: bulk_campaigns.control('Winter launch Oct 2026', 'start')):
            with patch.object(bulk_campaigns, 'require_access', side_effect=frappe.PermissionError):
                with self.assertRaises(frappe.PermissionError):
                    call()


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


if __name__ == '__main__':
    unittest.main()
