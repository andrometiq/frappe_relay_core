"""WhatsApp Business app numbers: copied chats, phone contacts and phone-sent echoes become Relay rows once."""
import json
import unittest
from unittest.mock import Mock, patch

from channel_fakes import FakeSite
from relay_core.automation import projection
from relay_core.onboarding import coexistence, signup

BUSINESS = '919000000120'
METADATA = {'display_phone_number': '+91 90000 00120', 'phone_number_id': '120'}


def payload(field, value):
    return {'object': 'whatsapp_business_account', 'entry': [{'id': '230', 'changes': [
        {'field': field, 'value': dict({'messaging_product': 'whatsapp', 'metadata': METADATA}, **value)}]}]}


def message(identifier, sender, body, status='READ'):
    return {'from': sender, 'id': identifier, 'timestamp': '1761980000', 'type': 'text', 'text': {'body': body},
            'history_context': {'status': status}}


def history(phase, progress, threads):
    return payload('history', {'history': [{'metadata': {'phase': phase, 'chunk_order': 1, 'progress': progress},
                                            'threads': threads}]})


class CoexistenceTests(unittest.TestCase):
    def setUp(self):
        self.site = FakeSite(Relay_Channel=[{'name': 'Acme-001', 'channel': 'WhatsApp', 'hub_channel': 'wa-120'}],
                             Relay_WhatsApp_Signup=[{'name': 'sus_1', 'hub_channel': 'wa-120', 'history_progress': 0}])
        self.contacts = {'919000000001': 'RELAY-CON-1', '919000000002': 'RELAY-CON-2'}
        self.contact_for = Mock(side_effect=lambda channel, number, name=None: self.contacts.get(number))
        for item in (patch.object(coexistence, 'frappe', self.site.frappe), patch.object(coexistence, 'contact_for', self.contact_for),
                     patch.object(coexistence, 'provider_time', lambda payload, row: row.get('timestamp')),
                     patch.object(signup, 'publish')):
            item.start()
            self.addCleanup(item.stop)

    def project(self, value):
        return coexistence.project_changes(value, 'Acme-001')

    def messages(self):
        return self.site.rows('Relay Message')

    def test_copied_chats_keep_direction_and_skip_automation(self):
        self.assertTrue(self.project(history(0, 30, [{'id': '919000000001', 'messages': [
            message('wamid.1', '919000000001', 'Hi'), message('wamid.2', BUSINESS, 'Hello, how can we help?', 'DELIVERED')]}])))
        incoming, outgoing = self.messages()
        self.assertEqual((incoming.direction, incoming.status, incoming.content, incoming.relay_contact),
                         ('Incoming', 'Read', 'Hi', 'RELAY-CON-1'))
        self.assertEqual((outgoing.direction, outgoing.status, outgoing.sender_endpoint), ('Outgoing', 'Delivered', '919000000001'))
        self.assertEqual({row.legacy_source for row in (incoming, outgoing)}, {'WhatsApp Business app'})
        self.assertEqual(json.loads(incoming.message_data)['source'], 'business_app')
        self.assertTrue(json.loads(incoming.provider_context)['historical'])
        signup_row, = self.site.rows('Relay WhatsApp Signup')
        self.assertEqual((signup_row.history_status, signup_row.history_progress), ('Importing', 30))

    def test_a_repeated_chunk_inserts_nothing_and_progress_reaches_done(self):
        chunk = [{'id': '919000000001', 'messages': [message('wamid.1', '919000000001', 'Hi')]}]
        self.project(history(0, 30, chunk))
        self.project(history(2, 100, chunk))
        self.project(history(1, 70, []))
        self.assertEqual(len(self.messages()), 1)
        signup_row, = self.site.rows('Relay WhatsApp Signup')
        self.assertEqual((signup_row.history_status, signup_row.history_progress), ('Done', 100))

    def test_an_unknown_person_or_bad_rows_are_skipped(self):
        self.project(history(0, 10, [{'id': '919000000009', 'messages': [message('wamid.9', '919000000009', 'Hi')]},
                                     {'id': 'not a number', 'messages': [message('wamid.8', 'x', 'Hi')]},
                                     {'id': '919000000001', 'messages': ['junk', {'id': 7}]}]))
        self.assertEqual(self.messages(), [])

    def test_a_declined_history_share_is_recorded(self):
        self.project(payload('history', {'history': [{'errors': [{'code': 2593109, 'title': 'History sharing declined'}]}]}))
        signup_row, = self.site.rows('Relay WhatsApp Signup')
        self.assertEqual(signup_row.history_status, 'Declined')
        self.assertEqual(self.messages(), [])

    def test_phone_contacts_become_relay_contacts(self):
        self.project(payload('smb_app_state_sync', {'state_sync': [
            {'type': 'contact', 'action': 'add', 'contact': {'full_name': 'Ravi Kumar', 'phone_number': '+91 90000 00002'}},
            {'type': 'contact', 'action': 'remove', 'contact': {'phone_number': '919000000001'}},
            {'type': 'other', 'action': 'add'}]}))
        self.contact_for.assert_called_once_with('Acme-001', '919000000002', 'Ravi Kumar')
        self.assertEqual(self.site.rows('Relay WhatsApp Signup')[0].contacts_status, 'Done')

    def test_phone_sent_messages_show_as_sent_messages(self):
        self.project(payload('smb_message_echoes', {'message_echoes': [
            {'from': BUSINESS, 'to': '919000000002', 'id': 'wamid.e1', 'timestamp': '1761980001', 'type': 'text',
             'text': {'body': 'Sent from the phone'}}]}))
        echo, = self.messages()
        self.assertEqual((echo.direction, echo.status, echo.relay_contact, echo.legacy_source),
                         ('Outgoing', 'Sent', 'RELAY-CON-2', None))
        self.assertNotIn('historical', json.loads(echo.provider_context))

    def test_other_payloads_are_not_coexistence(self):
        self.assertFalse(self.project(payload('messages', {'messages': []})))


class ProjectionHookTests(unittest.TestCase):
    def test_a_history_event_is_projected_through_the_coexistence_import(self):
        event = Mock(payload=json.dumps(dict(history(0, 30, []), channel='WhatsApp')), projection_status='Pending',
                     account='acme', event_key='acme:7')
        event.get = lambda key, default=None: {'event_key': 'acme:7', 'hub_channel': 'wa-120', 'routing_decisions': None}.get(key, default)
        fake = Mock()
        fake.get_doc.return_value = event
        with patch.object(projection, 'frappe', fake), \
                patch('relay_core.hub_channels.event_channel', return_value='Acme-001'), \
                patch('relay_core.whatsapp_templates.project', return_value=False), \
                patch.object(projection, 'apply_updates', return_value=None), \
                patch('relay_core.call_records.ingest', return_value=False), \
                patch('relay_core.ai_features.is_enabled', return_value=False), \
                patch('relay_core.realtime.changed'), \
                patch.object(coexistence, 'project_changes', return_value=True) as copied:
            projection.project('RELAY-EVT-7')
        copied.assert_called_once()
        fake.db.set_value.assert_any_call('Relay Hub Event', 'RELAY-EVT-7', 'projection_status', 'Projected')


if __name__ == '__main__':
    unittest.main()
