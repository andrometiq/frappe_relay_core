"""Imported WhatsApp Core history behaves like native messages; only billing leaves it out."""
import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe import _dict
from relay_core import attachments, billing, messaging, service_window

NOW = datetime.datetime(2026, 10, 27, 18, 0)


def imported(sent_at, **values):
    """An imported row: inserted now, sent at its original time."""
    return _dict(dict(name='RELAY-MSG-0000000009', sent_at=sent_at, creation=NOW, legacy_source='old-1'), **values)


class WindowTests(unittest.TestCase):
    def status(self, rows):
        query = Mock()
        query.run.return_value = rows
        with patch.object(service_window, 'page_query', return_value=query) as page, \
                patch.object(frappe.utils, 'now_datetime', return_value=NOW), \
                patch.object(frappe.utils, 'get_system_timezone', return_value='Asia/Kolkata'):
            return service_window.status('CON-1', 'CH-WA', '919000000001'), page.call_args.args[1]

    def test_an_imported_incoming_message_opens_the_window_from_its_real_time(self):
        result, filters = self.status([imported(NOW - datetime.timedelta(hours=2))])
        self.assertTrue(result['open'])
        self.assertEqual(result['expires_at'], NOW + datetime.timedelta(hours=22))
        self.assertNotIn('legacy_source', filters)
        self.assertEqual(result['expires_at_iso'], '2026-10-28T16:00:00+05:30')

    def test_old_imported_history_shows_when_the_window_closed(self):
        result, _ = self.status([imported(NOW - datetime.timedelta(days=6))])
        self.assertFalse(result['open'])
        self.assertEqual(result['expires_at'], NOW - datetime.timedelta(days=5))

    def test_without_incoming_history_there_is_no_deadline(self):
        result, _ = self.status([])
        self.assertIsNone(result['expires_at_iso'])
        self.assertFalse(result['open'])


class ReplyTests(unittest.TestCase):
    def prepare(self, kind, data, provider_id):
        source = _dict(name='RELAY-MSG-0000000009', sender_endpoint='919000000001', provider_id=provider_id)
        return messaging.prepare(source, _dict(channel='WhatsApp'), {'provider': 'WhatsApp', 'historical': True}, kind, data)

    def test_a_reply_to_an_imported_message_quotes_its_whatsapp_id(self):
        _, arguments, _ = self.prepare('text', {'text': 'Hello'}, 'wamid.OLD')
        self.assertEqual(arguments['reply_to'], 'wamid.OLD')

    def test_without_a_whatsapp_id_the_reply_goes_without_a_quote(self):
        _, arguments, _ = self.prepare('text', {'text': 'Hello'}, '')
        self.assertEqual((arguments['operation'], arguments['body']), ('messages.send', 'Hello'))
        self.assertNotIn('reply_to', arguments)
        with self.assertRaises(ValueError):
            self.prepare('reaction', {'emoji': '👍'}, '')


def throw(message, exception=frappe.ValidationError):
    raise exception(message)


class ArchivedMediaTests(unittest.TestCase):
    def read(self, exists):
        source = _dict(name='RELAY-MSG-0000000009', relay_contact='CON-1', channel='CH-WA', legacy_source='old-1',
                       message_data='{"attachment": "F1", "attachment_source": "RELAY-MSG-0000000009"}',
                       check_permission=Mock(), get=lambda key, default=None: source_values.get(key, default))
        source_values = dict(source)
        file = _dict(name='F1', file_name='bill.pdf', file_url='/private/files/bill.pdf', is_private=1,
                     attached_to_doctype='Relay Message', attached_to_name=source.name, check_permission=Mock(),
                     get_full_path=lambda: __file__ if exists else '/missing/private/files/bill.pdf')
        documents = {'Relay Message': source, 'Relay Channel': _dict(check_permission=Mock()), 'File': file}
        with patch.object(attachments.frappe, 'get_doc', side_effect=lambda doctype, name: documents[doctype]), \
                patch('relay_core.permissions.require_access'), patch('relay_core.permissions.readable_contact'), \
                patch.object(attachments.messaging, 'validate_reference'), patch.object(attachments.frappe, 'throw', throw):
            return attachments.archived_attachment(source.name)

    def test_imported_media_opens_after_permission_checks(self):
        response = self.read(True)
        self.assertEqual((response.mimetype, response.headers['Content-Disposition']), ('application/pdf', 'inline; filename="bill.pdf"'))

    def test_media_that_was_not_copied_fails_with_a_clear_error(self):
        with self.assertRaises(frappe.DoesNotExistError):
            self.read(False)


class BillingTests(unittest.TestCase):
    def test_imported_template_messages_are_not_new_spend(self):
        with patch.object(billing.frappe, 'db', SimpleNamespace(sql=Mock(return_value=[]))) as db:
            billing.template_counts(['CH-WA'], 2026)
        self.assertIn('legacy_source IS NULL', db.sql.call_args.args[0])
