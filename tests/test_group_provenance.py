import json
from types import SimpleNamespace
import unittest
from relay_core.automation.provenance import integer, telegram_message, telegram_route, whatsapp_group_route


class ProvenanceTests(unittest.TestCase):
    def event(self):
        return {'provider_id': '123', 'sender': '-1001', 'body': 'hello', 'payload': {'update_id': 123,
            'message': {'message_id': 4, 'message_thread_id': 8, 'chat': {'id': -1001, 'type': 'supergroup'},
                        'from': {'id': 42, 'is_bot': False}, 'text': 'hello'}}}

    def test_group_route_keeps_destination_topic_and_original_reply(self):
        context = telegram_message(self.event())
        doc = SimpleNamespace(sender_endpoint='-1001', provider_context=json.dumps(context))
        self.assertEqual(telegram_route(doc, 'reply'), {'chat_id': -1001, 'text': 'reply', 'reply_to': 4, 'message_thread_id': 8})
        self.assertEqual(context['participant_id'], 42)

    def test_group_and_private_sign_mismatch_rejected(self):
        event = self.event(); event['payload']['message']['chat']['type'] = 'private'
        with self.assertRaises(ValueError): telegram_message(event)
        doc = SimpleNamespace(sender_endpoint='-1001', provider_context={'provider': 'Telegram', 'chat_id': -1001, 'chat_type': 'private', 'message_id': 4})
        with self.assertRaises(ValueError): telegram_route(doc, 'reply')

    def test_group_missing_provenance_or_changed_destination_rejected(self):
        doc = SimpleNamespace(sender_endpoint='-1001', provider_context=None)
        with self.assertRaises(ValueError): telegram_route(doc, 'reply')
        doc.provider_context = telegram_message(self.event()); doc.sender_endpoint = '-1002'
        with self.assertRaises(ValueError): telegram_route(doc, 'reply')

    def test_invalid_and_boundary_identifiers_rejected(self):
        for value in (0, True, False, 2**52, -(2**52), '123', None):
            with self.subTest(value=value), self.assertRaises(ValueError): integer(value)

    def test_anonymous_group_admin_preserves_sender_chat_identity(self):
        event = self.event(); message = event['payload']['message']
        message['from']['is_bot'] = True; message['sender_chat'] = {'id': -1001}
        self.assertEqual(telegram_message(event)['sender_chat_id'], -1001)

    def test_normalized_route_and_body_must_match_authenticated_update(self):
        for field, value in [('provider_id', '124'), ('sender', '-1002'), ('body', 'changed')]:
            event = self.event(); event[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): telegram_message(event)

    def test_whatsapp_group_never_routes_to_participant(self):
        doc = SimpleNamespace(sender_endpoint='group-one', provider_id='wamid.1',
            provider_context={'provider': 'WhatsApp', 'group_id': 'group-one', 'participant_id': '919000000001'})
        self.assertEqual(whatsapp_group_route(doc, 'reply'), {'id': 'group-one', 'body': 'reply', 'reply_to': 'wamid.1'})
        doc.sender_endpoint = '919000000001'
        with self.assertRaises(ValueError): whatsapp_group_route(doc, 'reply')
