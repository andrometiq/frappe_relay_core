"""Received WhatsApp media is kept as a private File as soon as it arrives."""
import base64
from functools import partial
import json
from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import frappe
from relay_core import attachments, received_media
from relay_core.automation.service import message_hash
from relay_core.hub import HubClient, HubError
from site_file_limit import use_relay_file_limit

NOW = datetime(2026, 11, 12, 10, 0, 0)
WEBP = b'RIFF\x10\x00\x00\x00WEBPVP8 fixture'


def setUpModule():
    use_relay_file_limit()


class Doc(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


def message(kind='image', direction='Incoming', provider='WhatsApp', sent_at='2026-11-11 10:00:00', **data):
    media = {'id': '555', 'mime_type': 'image/jpeg'} if kind != 'sticker' else {'id': '556', 'mime_type': 'image/webp'}
    return Doc(name='RELAY-MSG-0000000101', direction=direction, message_type=kind, legacy_source=None,
        channel='RELAY-CH-1', sent_at=sent_at, creation=sent_at, content='Photo',
        provider_context=json.dumps({'provider': provider}),
        message_data=json.dumps({'kind': kind, 'media': media, **data}))


class OnMessageTests(unittest.TestCase):
    def setUp(self):
        self.callbacks = []
        self.frappe = SimpleNamespace(db=SimpleNamespace(after_commit=SimpleNamespace(add=self.callbacks.append)), enqueue=Mock())
        fixture = patch.object(received_media, 'frappe', self.frappe)
        fixture.start(); self.addCleanup(fixture.stop)

    def test_received_whatsapp_media_is_queued_once_after_commit(self):
        received_media.on_message(message())
        self.frappe.enqueue.assert_not_called()
        self.callbacks[0]()
        self.frappe.enqueue.assert_called_once_with('relay_core.received_media.store', message='RELAY-MSG-0000000101',
            queue='long', timeout=300, job_id='relay-media-store:RELAY-MSG-0000000101', deduplicate=True)

    def test_other_messages_are_not_queued(self):
        legacy = message(); legacy.legacy_source = 'legacy-1'
        oversized = message(); oversized.message_data = json.dumps({'kind': 'video', 'media': {'id': '9', 'file_size': 50 * 1024 * 1024}})
        for doc in (message(provider='Telegram'), message(direction='Outgoing'), message(kind='text'), legacy, oversized,
                    message(attachment='FILE-1', attachment_source='RELAY-MSG-0000000101'), message(media_store_skipped='too large')):
            received_media.on_message(doc)
        self.assertEqual(self.callbacks, [])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.source = message()
        self.hub = Mock()
        self.hub.media = partial(HubClient.media, self.hub)
        self.hub.call_tool.return_value = {'content_base64': base64.b64encode(b'jpeg bytes').decode(), 'content_type': 'image/jpeg'}
        self.saved = []
        def save_attachment(filename, raw, name):
            self.saved.append((filename, raw, name)); return SimpleNamespace(name='FILE-NEW')
        self.db = SimpleNamespace(commit=Mock(), get_value=Mock(side_effect=lambda doctype, name, field, **kw: self.source.message_data if field == 'message_data' else name),
                                  set_value=Mock())
        self.logger = Mock()
        boundary = SimpleNamespace(db=self.db, get_doc=lambda doctype, name: self.source if doctype == 'Relay Message' else SimpleNamespace(channel='WhatsApp', hub_channel=None),
                                   logger=lambda name: self.logger, ValidationError=frappe.ValidationError)
        def reject(text, error=ValueError): raise error(text)
        for fixture in (patch.object(received_media, 'frappe', boundary), patch.object(received_media.locks, 'lock', return_value=nullcontext()),
                        patch.object(received_media, 'save_attachment', side_effect=save_attachment),
                        patch.object(attachments, 'frappe', SimpleNamespace(throw=reject)),
                        patch.object(attachments, 'now_datetime', return_value=NOW), patch.object(received_media, 'now_datetime', return_value=NOW),
                        patch.object(attachments.whatsapp, 'client', return_value=self.hub)):
            fixture.start(); self.addCleanup(fixture.stop)

    def test_media_is_downloaded_once_and_recorded_where_read_looks_first(self):
        self.assertEqual(received_media.store(self.source.name), 'stored')
        self.hub.call_tool.assert_called_once_with('whatsapp.attachment', {'media_id': '555'})
        self.assertEqual(self.saved, [('whatsapp-image.jpg', b'jpeg bytes', 'RELAY-MSG-0000000101')])
        name, field, value = self.db.set_value.call_args.args[1:]
        self.assertEqual(json.loads(value)['attachment'], 'FILE-NEW')
        self.assertEqual(json.loads(value)['attachment_source'], 'RELAY-MSG-0000000101')

    def test_sticker_uses_the_sticker_tool_and_is_checked(self):
        self.source = message(kind='sticker')
        self.hub.call_tool.return_value = {'content_base64': base64.b64encode(WEBP).decode(), 'content_type': 'image/webp'}
        received_media.store(self.source.name)
        self.hub.call_tool.assert_called_once_with('whatsapp.media', {'media_id': '556'})
        self.assertEqual(self.saved[0][:2], ('sticker.webp', WEBP))
        self.saved.clear()
        self.hub.call_tool.return_value = {'content_base64': base64.b64encode(b'not webp').decode(), 'content_type': 'image/webp'}
        self.assertEqual(received_media.store(self.source.name), 'failed')
        self.assertEqual(self.saved, [])

    def test_a_kept_copy_or_expired_media_is_not_downloaded_again(self):
        self.source = message(attachment='FILE-OLD', attachment_source='RELAY-MSG-0000000101')
        self.assertEqual(received_media.store(self.source.name), 'skipped')
        self.source = message(sent_at='2026-11-04 10:00:00')
        self.assertEqual(received_media.store(self.source.name), 'expired')
        self.hub.call_tool.assert_not_called()

    def test_expired_media_is_tried_on_request_and_marked_when_meta_dropped_it(self):
        self.source = message(sent_at='2026-11-04 10:00:00')
        self.assertEqual(received_media.store(self.source.name, try_expired=True), 'stored')
        self.hub.call_tool.side_effect = HubError('rejected', {'provider': 'Hub', 'error': {'check': 'provider_metadata'}})
        self.assertEqual(received_media.store(self.source.name, try_expired=True), 'expired')
        self.assertEqual(self.skipped()[-1], 'Media no longer available from WhatsApp')


    def test_a_copy_kept_meanwhile_is_not_replaced(self):
        kept = json.dumps({'kind': 'image', 'media': {'id': '555'}, 'attachment': 'FILE-OTHER'})
        self.db.get_value.side_effect = lambda doctype, name, field, **kw: kept if field == 'message_data' else name
        self.assertEqual(received_media.store(self.source.name), 'skipped')
        self.assertEqual(self.saved, [])

    def skipped(self):
        return [json.loads(call.args[3]).get('media_store_skipped') for call in self.db.set_value.call_args_list]

    def test_a_busy_or_failed_hub_is_logged_and_left_for_recover(self):
        for check in ('capacity', 'provider_metadata'):
            self.hub.call_tool.side_effect = HubError('rejected', {'provider': 'Hub', 'error': {'check': check}})
            self.assertEqual(received_media.store(self.source.name), 'failed')
        self.assertIn('Try again', self.logger.warning.call_args.args[0])
        self.assertEqual((self.saved, self.skipped()), ([], []))

    def test_media_that_can_never_be_kept_is_marked_and_not_downloaded_again(self):
        self.hub.call_tool.return_value = {'content_base64': base64.b64encode(b'x' * (10 * 1024 * 1024 + 1)).decode(), 'content_type': 'video/mp4'}
        self.assertEqual(received_media.store(self.source.name), 'failed')
        self.hub.call_tool.side_effect = HubError('rejected', {'provider': 'Hub', 'error': {'check': 'ownership'}})
        self.assertEqual(received_media.store(self.source.name), 'failed')
        self.assertEqual(self.saved, [])
        self.assertEqual([reason.split()[0] for reason in self.skipped()], ['The', 'Media'])
        self.source.message_data = self.db.set_value.call_args.args[3]
        self.hub.call_tool.reset_mock()
        self.assertEqual(received_media.store(self.source.name), 'skipped')
        self.hub.call_tool.assert_not_called()

    def test_a_copy_kept_meanwhile_is_not_marked_skipped(self):
        self.db.get_value.side_effect = lambda doctype, name, field, **kw: json.dumps({'media': {'id': '555'}, 'attachment': 'FILE-OTHER'}) if field == 'message_data' else name
        received_media.skip(self.source.name, 'too large')
        self.db.set_value.assert_not_called()

    def test_file_names_keep_the_sender_name_and_a_matching_extension(self):
        self.assertEqual(received_media.file_name('Price list.pdf', 'application/pdf', 'document'), 'Price list.pdf')
        self.assertEqual(received_media.file_name('../notes', 'application/pdf', 'document'), '.._notes.pdf')
        self.assertEqual(received_media.file_name(None, 'audio/ogg', 'audio'), 'whatsapp-audio.ogg')
        self.assertEqual(received_media.file_name(None, 'application/x-unknown', 'document'), 'whatsapp-document')


class MissingTests(unittest.TestCase):
    def setUp(self):
        self.rows = [message(), message(sent_at='2026-11-01 10:00:00'), message(attachment='FILE-1')]
        for number, row in enumerate(self.rows): row.name = f'RELAY-MSG-000000020{number}'
        def get_all(doctype, limit_start=0, limit_page_length=None, **kw):
            return ['RELAY-CH-1'] if doctype == 'Relay Channel' else self.rows[limit_start:limit_start + limit_page_length]
        self.frappe = SimpleNamespace(get_all=Mock(side_effect=get_all), enqueue=Mock(), logger=Mock(),
                                      db=SimpleNamespace(rollback=Mock()))
        for fixture in (patch.object(received_media, 'frappe', self.frappe), patch.object(received_media, 'now_datetime', return_value=NOW),
                        patch.object(attachments, 'now_datetime', return_value=NOW)):
            fixture.start(); self.addCleanup(fixture.stop)

    def test_lists_only_media_meta_still_keeps_and_filters_in_sql(self):
        self.assertEqual(received_media.get_missing(7), ['RELAY-MSG-0000000200'])
        filters = self.frappe.get_all.call_args.kwargs['filters']
        self.assertIn(['legacy_source', 'is', 'not set'], filters)
        self.assertIn(['creation', '>=', datetime(2026, 11, 5, 10, 0, 0)], filters)
        self.assertIn(['message_data', 'not like', '%"attachment"%'], filters)
        self.assertIn(['message_data', 'not like', '%"media_store_skipped"%'], filters)
        self.assertEqual(self.frappe.get_all.call_args.kwargs['limit_page_length'], received_media.BATCH)
        self.assertEqual(received_media.get_missing(30, include_expired=True), ['RELAY-MSG-0000000200', 'RELAY-MSG-0000000201'])

    def test_pages_past_rows_that_cannot_be_queued_until_a_batch_is_found(self):
        self.rows = [message(sent_at='2026-11-01 10:00:00') for _ in range(4)] + [message() for _ in range(3)]
        for number, row in enumerate(self.rows): row.name = f'RELAY-MSG-000000030{number}'
        with patch.object(received_media, 'BATCH', 2):
            self.assertEqual(received_media.get_missing(7, limit=2), ['RELAY-MSG-0000000304', 'RELAY-MSG-0000000305'])
            self.assertEqual(received_media.get_missing(7, limit=None), [f'RELAY-MSG-000000030{number}' for number in (4, 5, 6)])
        self.assertEqual([call.kwargs['limit_start'] for call in self.frappe.get_all.call_args_list[1:4]], [0, 2, 4])

    def test_recover_queues_each_missing_copy_of_meta_window(self):
        received_media.recover()
        self.frappe.enqueue.assert_called_once()
        self.assertEqual(self.frappe.enqueue.call_args.kwargs['job_id'], 'relay-media-store:RELAY-MSG-0000000200')

    def test_backfill_dry_run_counts_candidates_without_downloading(self):
        with patch.object(received_media, 'store') as store:
            self.assertEqual(received_media.backfill(days=30, dry_run=1), {'candidates': 2})
        store.assert_not_called()

    def test_backfill_tries_each_message_once_and_counts_outcomes(self):
        outcomes = iter(['stored', RuntimeError('database gone')])
        def store(name, try_expired):
            self.assertTrue(try_expired)
            outcome = next(outcomes)
            if isinstance(outcome, Exception): raise outcome
            return outcome
        with patch.object(received_media, 'store', side_effect=store):
            counts = received_media.backfill(days=30)
        self.assertEqual(counts, {'stored': 1, 'expired': 0, 'failed': 1, 'skipped': 0})
        self.frappe.db.rollback.assert_called_once()
        logged = [call.args[0] for call in self.frappe.logger.return_value.info.call_args_list]
        self.assertIn('Received media backfill RELAY-MSG-0000000200: stored', logged)
        self.assertIn('Received media backfill RELAY-MSG-0000000201: failed', logged)
        self.frappe.enqueue.assert_not_called()


class EditTests(unittest.TestCase):
    def test_an_edit_of_the_same_media_keeps_its_copy(self):
        previous = message(attachment='FILE-1', attachment_source='RELAY-MSG-0000000101').message_data
        edited = {'kind': 'image', 'media': {'id': '555'}, 'caption': 'Updated caption'}
        self.assertEqual(received_media.with_kept_copy(previous, edited), dict(edited, attachment='FILE-1', attachment_source='RELAY-MSG-0000000101'))
        other = {'kind': 'image', 'media': {'id': '999'}}
        self.assertEqual(received_media.with_kept_copy(previous, other), other)
        self.assertEqual(received_media.with_kept_copy(previous, {'kind': 'revoked'}), {'kind': 'revoked'})


class MessageHashTests(unittest.TestCase):
    def test_a_kept_copy_does_not_make_queued_work_stale(self):
        source, kept = message(), message(attachment='FILE-1', attachment_source='RELAY-MSG-0000000101')
        self.assertEqual(message_hash(source), message_hash(kept))
        self.assertEqual(message_hash(source), message_hash(message(media_store_skipped='too large')))
        self.assertNotEqual(message_hash(source), message_hash(message(caption='changed')))


if __name__ == '__main__':
    unittest.main()
