"""Scheduled template sync, request audit and rejection reasons with a mocked Hub."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from frappe import _dict
from relay_core import whatsapp_templates
from relay_core.hub import HubError


class Cache:
    """Redis hash and value calls the module uses, in memory."""
    def __init__(self):
        self.values = {}

    def hset(self, name, key, value): self.values.setdefault(name, {})[key] = value
    def hget(self, name, key): return self.values.get(name, {}).get(key)
    def set_value(self, name, value): self.values[name] = value
    def get_value(self, name): return self.values.get(name)
    def delete_value(self, name): self.values.pop(name, None)
    def delete_keys(self, prefix): self.values = {k: v for k, v in self.values.items() if not k.startswith(prefix)}


class Store:
    """In-memory Relay WhatsApp Template rows behind the frappe calls the module uses."""
    def __init__(self):
        self.rows, self.requests = {}, []
        self.channels = [_dict(name='WA', waba_id='')]
        self.frappe = SimpleNamespace(db=Mock(), get_doc=self.get_doc, get_all=self.get_all, _dict=_dict,
            publish_realtime=Mock(), realtime=SimpleNamespace(get_doctype_room=lambda doctype: doctype),
            log_error=Mock(), ValidationError=type('ValidationError', (Exception,), {}), cache=Cache(),
            utils=SimpleNamespace(now=lambda: '2026-10-26 09:00:00'))
        self.frappe.db.exists.return_value = True
        self.frappe.db.get_value.side_effect = self.get_value

    def get_value(self, doctype, filters, field, for_update=False):
        if doctype == 'Relay WhatsApp Template':
            return filters['record_key'] if filters['record_key'] in self.rows else None

    def get_doc(self, doctype, name=None):
        return _dict(doctype) if isinstance(doctype, dict) else self.rows[name]

    def get_all(self, doctype, filters=None, pluck=None, fields=None, **kwargs):
        if doctype == 'Relay Channel':
            return [row for row in self.channels if filters.get('name') in (None, row.name)][:1]
        rows = [row for row in self.rows.values() if row.account == filters['account']
                and row.status != 'DELETED' and row.template_id not in (filters.get('template_id') or ['', []])[1]]
        return [row[pluck] for row in rows]

    def save(self, doc, new=False):
        if doc.doctype == 'Relay WhatsApp Template Request':
            self.requests.append(doc)
        else:
            doc.name = doc.record_key
            self.rows[doc.name] = doc


def page(rows, after=None):
    return {'data': rows, 'paging': {'cursors': {'after': after}, 'has_more': bool(after)}}


ROW = {'id': '101', 'name': 'order_update', 'language': 'en_US', 'category': 'UTILITY', 'status': 'PENDING'}


class TemplateSyncTests(unittest.TestCase):
    def setUp(self):
        self.store, self.hub = Store(), Mock()
        self.patches = [patch.object(whatsapp_templates, 'frappe', self.store.frappe),
            patch.object(whatsapp_templates, 'internal_save', side_effect=self.store.save),
            patch.object(whatsapp_templates, 'connection_value', return_value='essdee'),
            patch('relay_core.whatsapp.checked_client', return_value=(self.hub, {'templates': True})),
            patch.object(whatsapp_templates, 'waba_channels', return_value=[_dict(name='WA', waba_id='')]),
            patch('relay_core.hub_channels.hub_arguments', side_effect=lambda channel, arguments: arguments)]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in self.patches: item.stop()

    def statuses(self):
        return {row.template_name: row.status for row in self.store.rows.values()}

    def test_changed_rows_are_stored_and_published_once(self):
        self.hub.execute.return_value = page([ROW, dict(ROW, id='102', name='payment_due', status='REJECTED',
            rejected_reason='INVALID_FORMAT', quality_score={'score': 'GREEN'})])
        self.assertTrue(whatsapp_templates.sync())
        self.assertEqual(self.statuses(), {'order_update': 'PENDING', 'payment_due': 'REJECTED'})
        rejected = next(row for row in self.store.rows.values() if row.template_id == '102')
        self.assertEqual((rejected.reason, rejected.quality, rejected.hub_event_id), ('INVALID_FORMAT', 'GREEN', '0'))
        self.store.frappe.publish_realtime.assert_called_once()

    def test_unchanged_list_writes_and_publishes_nothing(self):
        self.hub.execute.return_value = page([ROW])
        whatsapp_templates.sync()
        self.store.frappe.publish_realtime.reset_mock()
        with patch.object(whatsapp_templates, 'internal_save') as save:
            self.assertFalse(whatsapp_templates.sync())
        save.assert_not_called()
        self.store.frappe.publish_realtime.assert_not_called()

    def test_status_change_and_complete_list_marks_missing_deleted(self):
        self.hub.execute.return_value = page([ROW, dict(ROW, id='102', name='payment_due')])
        whatsapp_templates.sync()
        self.hub.execute.return_value = page([dict(ROW, status='APPROVED')])
        self.assertTrue(whatsapp_templates.sync())
        self.assertEqual(self.statuses(), {'order_update': 'APPROVED', 'payment_due': 'DELETED'})

    def test_pages_follow_cursor_and_stay_bounded(self):
        self.hub.execute.side_effect = [page([dict(ROW, id=str(200 + index), name='t' + 'x' * index)], after='c' + str(index))
                                        for index in range(whatsapp_templates.SYNC_PAGES)]
        whatsapp_templates.sync()
        self.assertEqual(self.hub.execute.call_count, whatsapp_templates.SYNC_PAGES)
        self.assertEqual(self.hub.execute.call_args_list[1].args[0], {'operation': 'templates.list', 'after': 'c0'})
        self.assertNotIn('DELETED', self.statuses().values())  # A truncated list never infers deletion.

    def test_requested_sync_publishes_even_without_changes_and_on_failure(self):
        self.hub.execute.return_value = page([ROW])
        whatsapp_templates.sync()
        self.store.frappe.publish_realtime.reset_mock()
        self.assertFalse(whatsapp_templates.sync(notify=True))
        self.store.frappe.publish_realtime.assert_called_once()
        self.hub.execute.side_effect = HubError('down')
        self.assertFalse(whatsapp_templates.sync(notify=True))
        self.assertEqual(self.store.frappe.publish_realtime.call_count, 2)

    def test_hub_error_is_logged_without_writes(self):
        self.hub.execute.side_effect = HubError('rejected', detail='templates are not enabled for this account')
        self.assertFalse(whatsapp_templates.sync())
        self.store.frappe.log_error.assert_called_once_with('Relay WhatsApp template sync failed', 'templates are not enabled for this account')
        self.assertEqual(self.store.rows, {})

    def test_disabled_channel_or_templates_skip_the_hub(self):
        self.store.frappe.db.exists.return_value = False
        self.assertFalse(whatsapp_templates.sync())
        self.store.frappe.db.exists.return_value = True
        with patch('relay_core.whatsapp.checked_client', return_value=(self.hub, {'templates': False})):
            self.assertFalse(whatsapp_templates.sync())
        self.hub.execute.assert_not_called()

    def test_invalid_hub_row_fails_loudly(self):
        self.hub.execute.return_value = page([dict(ROW, id='not-a-number')])
        with self.assertRaises(ValueError): whatsapp_templates.sync()

    def test_request_audit_omits_uploaded_bytes(self):
        whatsapp_templates.record_request('templates.media_upload', {'media_type': 'image', 'filename': 'sample.png',
            'content_base64': 'AAAA'}, error='unsupported attachment MIME type')
        request = self.store.requests[0]
        self.assertEqual((request.status, request.error), ('Failed', 'unsupported attachment MIME type'))
        self.assertEqual(json.loads(request.request), {'media_type': 'image', 'filename': 'sample.png', 'content_bytes': 3})

    def test_created_template_is_pending_locally_and_delete_marks_it(self):
        arguments = {'name': 'order_update', 'language': 'en_US', 'category': 'UTILITY'}
        whatsapp_templates.apply_request('templates.create', arguments, {'id': '101', 'status': 'PENDING'})
        self.assertEqual(self.statuses(), {'order_update': 'PENDING'})
        self.store.frappe.get_all = lambda doctype, filters, pluck: [key for key, row in self.store.rows.items()
            if row.template_name == filters['template_name'] and row.template_id == filters['template_id']]
        whatsapp_templates.apply_request('templates.delete', {'name': 'order_update', 'id': '101'}, {'success': True})
        self.assertEqual(self.statuses(), {'order_update': 'DELETED'})

    def test_status_webhook_keeps_meta_reason_text(self):
        value = {'message_template_id': 101, 'message_template_name': 'order_update', 'message_template_language': 'en_US',
                 'event': 'REJECTED', 'reason': 'INVALID_FORMAT', 'other_info': {'title': 'Format issue',
                 'description': "Variables can't be at the start or end of the template."}}
        whatsapp_templates.project({'entry': [{'changes': [{'field': 'message_template_status_update', 'value': value}]}]},
                                   _dict(account='essdee', hub_event_id='9'))
        row = next(iter(self.store.rows.values()))
        self.assertEqual(row.reason, "INVALID_FORMAT · Format issue · Variables can't be at the start or end of the template.")

    def test_quality_webhook_updates_quality_and_keeps_status(self):
        def deliver(field, value, event_id):
            payload = {'entry': [{'id': '222', 'changes': [{'field': field, 'value': value}]}]}
            self.assertTrue(whatsapp_templates.template_event(payload))
            return whatsapp_templates.project(payload, _dict(account='essdee', hub_event_id=event_id))
        identity = {'message_template_id': 101, 'message_template_name': 'order_update', 'message_template_language': 'en_US'}
        self.assertFalse(deliver('message_template_quality_update', dict(identity, new_quality_score='RED'), '8'))
        self.assertEqual(self.store.rows, {})
        deliver('message_template_status_update', dict(identity, event='APPROVED'), '9')
        deliver('message_template_quality_update', dict(identity, previous_quality_score='GREEN', new_quality_score='YELLOW'), '10')
        row = next(iter(self.store.rows.values()))
        self.assertEqual((row.status, row.quality, row.waba_id), ('APPROVED', 'YELLOW', '222'))
        with self.assertRaises(ValueError):
            deliver('message_template_quality_update', dict(identity, new_quality_score='BLUE'), '11')

    def test_overlay_keeps_live_status_and_adds_local_reason(self):
        self.store.frappe.get_all = lambda *args, **kwargs: [_dict(template_id='101', reason='INVALID_FORMAT')]
        result = whatsapp_templates.overlay({'data': [dict(ROW, status='REJECTED')]})
        self.assertEqual((result['data'][0]['status'], result['data'][0]['rejected_reason']), ('REJECTED', 'INVALID_FORMAT'))


MARKETING = {'name': 'relay_test_marketing', 'language': 'en', 'parameter_format': 'POSITIONAL', 'components': [
    {'type': 'HEADER', 'format': 'TEXT', 'text': 'Hello {{1}}'},
    {'type': 'BODY', 'text': 'Hi {{1}}, our {{2}} collection is now available. {{3}}'},
    {'type': 'FOOTER', 'text': 'Essdee Knitting Mills'},
    {'type': 'BUTTONS', 'buttons': [{'type': 'QUICK_REPLY', 'text': 'Send catalogue'}, {'type': 'URL', 'text': 'Open shop', 'url': 'https://example.invalid/{{1}}'}]}]}
SENT = [{'type': 'header', 'parameters': [{'type': 'text', 'text': 'Ravi'}]},
        {'type': 'body', 'parameters': [{'type': 'text', 'text': 'Ravi'}, {'type': 'text', 'text': 'Winter'},
                                        {'type': 'currency', 'currency': {'fallback_value': 'Rs 499'}}]},
        {'type': 'button', 'sub_type': 'url', 'index': '1', 'parameters': [{'type': 'text', 'text': 'winter'}]}]


class TemplateRenderTests(unittest.TestCase):
    def setUp(self):
        self.store, self.hub = Store(), Mock()
        self.patches = [patch.object(whatsapp_templates, 'frappe', self.store.frappe),
            patch.object(whatsapp_templates, 'internal_save', side_effect=self.store.save),
            patch.object(whatsapp_templates, 'connection_value', return_value='essdee'),
            patch('relay_core.whatsapp.checked_client', return_value=(self.hub, {'templates': True})),
            patch.object(whatsapp_templates, 'waba_channels', return_value=[_dict(name='WA', waba_id='')]),
            patch('relay_core.hub_channels.hub_arguments', side_effect=lambda channel, arguments: arguments)]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in self.patches: item.stop()

    def test_positional_values_fill_header_body_and_buttons(self):
        rendered = whatsapp_templates.render(MARKETING, SENT)
        self.assertEqual(rendered, {'header': 'Hello Ravi', 'body': 'Hi Ravi, our Winter collection is now available. Rs 499',
                                    'footer': 'Essdee Knitting Mills', 'buttons': ['Send catalogue', 'Open shop']})

    def test_named_values_and_missing_values_keep_placeholders(self):
        template = {'components': [{'type': 'BODY', 'text': 'Hi {{customer_name}}, order {{order_number}}'}]}
        sent = [{'type': 'body', 'parameters': [{'type': 'text', 'text': 'Asha', 'parameter_name': 'customer_name'}]}]
        self.assertEqual(whatsapp_templates.render(template, sent), {'body': 'Hi Asha, order {{order_number}}'})

    def test_media_header_is_not_rendered_as_text(self):
        template = {'components': [{'type': 'HEADER', 'format': 'IMAGE'}, {'type': 'BODY', 'text': 'New stock'}]}
        self.assertEqual(whatsapp_templates.render(template, []), {'body': 'New stock'})

    def test_copy_code_button_without_text_gets_its_meta_label(self):
        buttons = [{'type': 'QUICK_REPLY', 'text': 'Stop'}, {'type': 'COPY_CODE', 'example': 'SAVE20'}]
        template = {'components': [{'type': 'BODY', 'text': 'Offer'}, {'type': 'BUTTONS', 'buttons': buttons}]}
        self.assertEqual(whatsapp_templates.render(template, [])['buttons'], ['Stop', 'Copy offer code'])

    def test_sync_caches_definitions_so_sends_skip_the_hub(self):
        self.hub.execute.return_value = page([dict(ROW, **MARKETING, id='103', status='APPROVED')])
        whatsapp_templates.sync()
        self.hub.execute.reset_mock()
        content = whatsapp_templates.message_content({'name': 'relay_test_marketing', 'language': 'en', 'components': SENT, 'to': '9190'})
        self.hub.execute.assert_not_called()
        self.assertEqual(content['text'], 'Hi Ravi, our Winter collection is now available. Rs 499')
        self.assertEqual(content['template'], {'name': 'relay_test_marketing', 'language': 'en', 'components': SENT,
            'header': 'Hello Ravi', 'footer': 'Essdee Knitting Mills', 'buttons': ['Send catalogue', 'Open shop']})

    def test_cache_miss_scans_the_hub_once_and_unknown_template_falls_back_to_name(self):
        self.hub.execute.return_value = page([dict(ROW, **MARKETING, id='103', status='APPROVED')])
        content = whatsapp_templates.message_content({'name': 'relay_test_marketing', 'language': 'en', 'components': SENT})
        self.assertEqual((self.hub.execute.call_count, content['template']['header']), (1, 'Hello Ravi'))
        missing = whatsapp_templates.message_content({'name': 'retired_offer', 'language': 'en'})
        self.assertEqual(missing, {'kind': 'text', 'text': 'Template: retired_offer', 'template': {'name': 'retired_offer', 'language': 'en'}})

    def test_document_header_file_name_is_kept_with_the_message(self):
        header = {'type': 'header', 'parameters': [{'type': 'document', 'document': {'id': '9001', 'filename': 'Order_ORD-1.pdf'}}]}
        content = whatsapp_templates.message_content({'name': 'retired_offer', 'language': 'en', 'components': [header]}, template={'components': []})
        self.assertEqual(content['template']['document'], {'file_name': 'Order_ORD-1.pdf'})

    def test_hub_failure_does_not_block_the_send(self):
        self.hub.execute.side_effect = HubError('down')
        self.assertEqual(whatsapp_templates.message_content({'name': 'relay_test_marketing', 'language': 'en'})['text'],
                         'Template: relay_test_marketing')

    def test_template_edit_drops_cached_content(self):
        self.store.frappe.cache.hset(whatsapp_templates.DEFINITIONS + 'essdee', 'relay_test_marketing|en', MARKETING)
        whatsapp_templates.apply_request('templates.update', {'id': '103'}, {'success': True})
        self.assertIsNone(self.store.frappe.cache.hget(whatsapp_templates.DEFINITIONS + 'essdee', 'relay_test_marketing|en'))

    def test_sync_status_reports_last_successful_sync(self):
        with patch('relay_core.permissions.require_access'):
            self.assertEqual(whatsapp_templates.sync_status(), {'synced_at': None, 'templates': 0})
            self.hub.execute.return_value = page([ROW])
            whatsapp_templates.sync()
            self.assertEqual(whatsapp_templates.sync_status(), {'synced_at': '2026-10-26 09:00:00', 'templates': 1})
            self.hub.execute.side_effect = HubError('down')
            whatsapp_templates.sync()
            self.assertEqual(whatsapp_templates.sync_status()['synced_at'], '2026-10-26 09:00:00')


    def test_send_without_a_channel_renders_the_default_channel_waba(self):
        self.store.channels = [_dict(name='WA-B', waba_id='666')]
        whatsapp_templates.remember('essdee', [dict(MARKETING, id='103')], '555')
        whatsapp_templates.remember('essdee', [dict(ROW, id='201', name='relay_test_marketing', language='en',
            components=[{'type': 'BODY', 'text': 'Other WABA'}])], '666')
        self.assertEqual(whatsapp_templates.definition('relay_test_marketing', 'en')['id'], '201')
        self.store.channels.append(_dict(name='WA-A', waba_id='555'))
        self.assertEqual(whatsapp_templates.definition('relay_test_marketing', 'en', 'WA-A')['id'], '103')
        self.hub.execute.assert_not_called()

    def test_cache_miss_scans_the_default_channel(self):
        self.store.channels = [_dict(name='WA-B', waba_id='666')]
        self.hub.execute.return_value = page([dict(ROW, **MARKETING, id='103', status='APPROVED')])
        with patch('relay_core.hub_channels.hub_arguments', side_effect=lambda channel, arguments: dict(arguments, channel=channel)):
            self.assertEqual(whatsapp_templates.definition('relay_test_marketing', 'en')['id'], '103')
        self.assertEqual(self.hub.execute.call_args.args[0]['channel'], 'WA-B')
        self.assertIsNotNone(self.store.frappe.cache.hget(whatsapp_templates.DEFINITIONS + 'essdee:666', 'relay_test_marketing|en'))

    def test_single_send_stores_the_rendered_body_as_message_text(self):
        from relay_core import conversation_start, messaging
        self.store.frappe.cache.hset(whatsapp_templates.DEFINITIONS + 'essdee', 'relay_test_marketing|en', MARKETING)
        content = conversation_start.whatsapp_content({'operation': 'templates.send', 'to': '9190',
            'name': 'relay_test_marketing', 'language': 'en', 'components': SENT})
        self.assertEqual(messaging.preview(content), 'Hi Ravi, our Winter collection is now available. Rs 499')
        self.assertEqual(content['template']['buttons'], ['Send catalogue', 'Open shop'])
        with self.assertRaises(ValueError):
            conversation_start.whatsapp_content({'operation': 'templates.send', 'name': ''})


class LocalTemplateListTests(unittest.TestCase):
    """The Templates tab reads the local copy; a stale copy queues one background Hub sync."""
    def setUp(self):
        self.cache = Cache()
        self.cache.hgetall = lambda name: {key.encode(): value for key, value in self.cache.values.get(name, {}).items()}
        self.locks = set()
        self.cache.make_key = lambda key: key
        self.cache.set = lambda key, value, nx=False, ex=None: not (key in self.locks or self.locks.add(key))
        self.rows = [_dict(template_id='103', template_name='relay_test_marketing', language='en', category='MARKETING',
                           status='APPROVED', quality='GREEN', reason=None)]
        self.frappe = SimpleNamespace(cache=self.cache, enqueue=Mock(), publish_realtime=Mock(),
            realtime=SimpleNamespace(get_doctype_room=lambda doctype: doctype),
            get_all=Mock(side_effect=lambda doctype, **kwargs: self.rows),
            utils=SimpleNamespace(now=lambda: '2026-10-26 09:10:00',
                time_diff_in_seconds=lambda later, earlier: 600 if earlier == '2026-10-26 09:00:00' else 10))
        self.patches = [patch.object(whatsapp_templates, 'frappe', self.frappe),
            patch.object(whatsapp_templates, 'connection_value', return_value='essdee'),
            patch('relay_core.permissions.require_access')]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in self.patches: item.stop()

    def test_local_rows_are_the_listed_hub_rows_with_newer_local_status(self):
        self.cache.hset(whatsapp_templates.DEFINITIONS + 'essdee', 'relay_test_marketing|en', dict(MARKETING, id='103',
            status='PENDING', category='MARKETING', message_send_ttl_seconds=300))
        self.cache.set_value(whatsapp_templates.SYNCED + 'essdee', {'synced_at': '2026-10-26 09:09:50', 'templates': 1})
        result = whatsapp_templates.directory()
        self.assertEqual(result['data'], [{'id': '103', 'name': 'relay_test_marketing', 'language': 'en', 'category': 'MARKETING',
            'status': 'APPROVED', 'quality_score': {'score': 'GREEN'}, 'parameter_format': 'POSITIONAL',
            'components': MARKETING['components'], 'message_send_ttl_seconds': 300}])
        self.assertEqual(result['sync'], {'synced_at': '2026-10-26 09:09:50', 'templates': 1, 'syncing': False})
        self.frappe.enqueue.assert_not_called()
        self.assertEqual(self.frappe.get_all.call_args.kwargs['filters'], {'account': 'essdee', 'status': ['!=', 'DELETED']})

    def test_content_synced_for_a_waba_reaches_the_unfiltered_directory(self):
        self.rows[0].waba_id = '555'
        whatsapp_templates.remember('essdee', [dict(MARKETING, id='103')], '555')
        self.cache.set_value(whatsapp_templates.SYNCED + 'essdee', {'synced_at': '2026-10-26 09:09:50', 'templates': 1})
        data = whatsapp_templates.directory()['data']
        self.assertEqual(data[0]['components'], MARKETING['components'])

    def test_same_template_name_in_two_wabas_keeps_each_waba_content(self):
        other = [{'type': 'BODY', 'text': 'Other WABA'}]
        self.rows = [_dict(self.rows[0], waba_id='555'), _dict(self.rows[0], template_id='201', waba_id='666')]
        whatsapp_templates.remember('essdee', [dict(MARKETING, id='103')], '555')
        whatsapp_templates.remember('essdee', [dict(MARKETING, id='201', components=other)], '666')
        self.cache.set_value(whatsapp_templates.SYNCED + 'essdee', {'synced_at': '2026-10-26 09:09:50', 'templates': 2})
        data = whatsapp_templates.directory()['data']
        self.assertEqual([(row['id'], row['components']) for row in data], [('103', MARKETING['components']), ('201', other)])

    def test_stale_or_incomplete_copy_queues_one_sync_per_minute(self):
        self.cache.set_value(whatsapp_templates.SYNCED + 'essdee', {'synced_at': '2026-10-26 09:00:00', 'templates': 1})
        self.assertTrue(whatsapp_templates.directory()['sync']['syncing'])
        self.assertFalse(whatsapp_templates.directory()['sync']['syncing'], 'A second open within a minute does not queue again')
        self.frappe.enqueue.assert_called_once_with('relay_core.whatsapp_templates.sync', queue='short', timeout=300, notify=True)
        self.locks.clear()
        self.cache.set_value(whatsapp_templates.SYNCED + 'essdee', {'synced_at': '2026-10-26 09:09:50', 'templates': 1})
        self.assertTrue(whatsapp_templates.directory()['sync']['syncing'], 'Rows without cached content need a sync')

    def test_without_an_account_nothing_is_queued(self):
        self.rows = []
        with patch.object(whatsapp_templates, 'connection_value', return_value=None):
            self.assertEqual(whatsapp_templates.directory(), {'data': [], 'sync': {'synced_at': None, 'templates': 0, 'syncing': False}})
        self.frappe.enqueue.assert_not_called()


if __name__ == '__main__':
    unittest.main()
