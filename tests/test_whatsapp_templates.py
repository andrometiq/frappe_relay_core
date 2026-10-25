"""Scheduled template sync, request audit and rejection reasons with a mocked Hub."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from frappe import _dict
from relay_core import whatsapp_templates
from relay_core.hub import HubError


class Store:
    """In-memory Relay WhatsApp Template rows behind the frappe calls the module uses."""
    def __init__(self):
        self.rows, self.requests = {}, []
        self.frappe = SimpleNamespace(db=Mock(), get_doc=self.get_doc, get_all=self.get_all,
            publish_realtime=Mock(), realtime=SimpleNamespace(get_doctype_room=lambda doctype: doctype),
            log_error=Mock(), ValidationError=type('ValidationError', (Exception,), {}))
        self.frappe.db.exists.return_value = True
        self.frappe.db.get_value.side_effect = self.get_value

    def get_value(self, doctype, filters, field, for_update=False):
        if doctype == 'Relay WhatsApp Template':
            return filters['record_key'] if filters['record_key'] in self.rows else None

    def get_doc(self, doctype, name=None):
        return _dict(doctype) if isinstance(doctype, dict) else self.rows[name]

    def get_all(self, doctype, filters=None, pluck=None, fields=None):
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
            patch('relay_core.whatsapp.checked_client', return_value=(self.hub, {'templates': True}))]
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

    def test_overlay_keeps_live_status_and_adds_local_reason(self):
        self.store.frappe.get_all = lambda *args, **kwargs: [_dict(template_id='101', reason='INVALID_FORMAT')]
        result = whatsapp_templates.overlay({'data': [dict(ROW, status='REJECTED')]})
        self.assertEqual((result['data'][0]['status'], result['data'][0]['rejected_reason']), ('REJECTED', 'INVALID_FORMAT'))


if __name__ == '__main__':
    unittest.main()
