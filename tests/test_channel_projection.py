"""Provider-neutral input validation before any conversation writes."""
import importlib.util
import json
import pathlib
import sys
import types
import unittest
from unittest.mock import patch


class ChannelProjectionTests(unittest.TestCase):
    def setUp(self):
        path = pathlib.Path(__file__).parents[1] / 'relay_core/automation/projection.py'
        spec = importlib.util.spec_from_file_location('channel_projection_under_test', path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe': types.ModuleType('frappe')}):
            spec.loader.exec_module(self.module)

    def test_normalized_inbound_preserves_endpoint_and_provider_id(self):
        for channel, sender in [('Telegram', '-100123456'), ('Email', 'person@example.test')]:
            with self.subTest(channel=channel):
                rows = self.module.extract_messages(dict(channel=channel, direction='inbound',
                    provider_id='provider-1', sender=sender, body='Hello'))
                self.assertEqual([{key:row[key] for key in ('id','from','type','text')} for row in rows], [{'id': 'provider-1', 'from': sender,
                    'type': 'text', 'text': {'body': 'Hello'}}])

    def test_outbound_does_not_become_incoming(self):
        self.assertEqual(self.module.extract_messages({'channel': 'Email', 'direction': 'outbound'}), [])

    def test_invalid_identities_rejected_before_writes(self):
        for changes in [{'provider_id': ''}, {'sender': None}, {'body': {}}, {'sender': 'x'*201}]:
            payload = dict(channel='Telegram', direction='inbound', provider_id='1', sender='2', body='Hi')
            payload.update(changes)
            with self.assertRaises(ValueError):
                self.module.extract_messages(payload)


class InteractiveMessageTests(unittest.TestCase):
    def test_form_reply_retains_fields_without_exposing_correlation_token(self):
        from relay_core.message_types import normalize
        result=normalize('interactive',{'nfm_reply':{'body':'Feedback received','response_json':'{"flow_token":"secret","rating":5,"details":{"helpful":true}}'}},provider='WhatsApp')
        self.assertEqual(result['text'],'Feedback received')
        self.assertEqual(result['form_response'],{'rating':5,'details':{'helpful':True}})
        self.assertNotIn('secret',str(result))

    def test_invalid_form_replies_are_rejected(self):
        from relay_core.message_types import normalize
        for raw in ('[]','not json','x'*12001):
            with self.assertRaises(ValueError):normalize('interactive',{'nfm_reply':{'response_json':raw}},provider='WhatsApp')

class WhatsAppInboundTypesTests(unittest.TestCase):
    setUp = ChannelProjectionTests.setUp

    def extract(self, kind, detail, **extra):
        message = {'id': 'wamid.fixture', 'from': '919999999999', 'from_user_id': 'business-scoped-user',
                   'type': kind, kind: detail, **extra}
        return self.module.extract_messages({'entry': [{'changes': [{'value': {'messages': [message]}}]}]})

    def test_media_preserves_metadata_and_ignores_download_urls(self):
        from relay_core.message_types import preview
        for kind in ('image', 'audio', 'video', 'document', 'sticker'):
            detail = {'id': '123', 'mime_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                      'filename': 'Local fixture.docx', 'file_size': 12345, 'caption': 'Local test caption',
                      'url': 'https://private.invalid/signed', 'sha256': 'opaque-digest'}
            row, = self.extract(kind, detail)
            self.assertEqual(row['type'], kind)
            self.assertEqual(row['from'], '919999999999')
            self.assertEqual(row['from_user_id'], 'business-scoped-user')
            data = row['message_data']
            self.assertEqual(data, {'kind': kind, 'media': {key: detail[key] for key in ('id', 'mime_type', 'filename', 'file_size')}, 'caption': 'Local test caption'})
            self.assertEqual(preview(data), 'Local test caption')
        row, = self.extract('document', {'id': '123', 'filename': 'Local fixture.docx'})
        self.assertEqual(preview(row['message_data']), 'Local fixture.docx')

    def test_common_inbound_types(self):
        cases = [
            ('text', {'body': 'Hello'}, 'text'),
            ('location', {'latitude': 12.9, 'longitude': 80.2, 'name': 'Local fixture'}, 'location'),
            ('contacts', [{'name': {'formatted_name': 'Local fixture'}, 'phones': [{'phone': '+919999999999'}]}], 'contacts'),
            ('button', {'text': 'Yes', 'payload': 'yes'}, 'text'),
            ('interactive', {'button_reply': {'id': 'yes', 'title': 'Yes'}}, 'text'),
            ('interactive', {'list_reply': {'id': 'item', 'title': 'Item'}}, 'text'),
            ('interactive', {'nfm_reply': {'body': 'Form submitted', 'response_json': '{"rating":5}'}}, 'text'),
            ('interactive', {'call_permission_reply': {'response': 'accept'}}, 'text'),
            ('interactive', {'type': 'unknown_reply'}, 'unsupported'),
            ('order', {'catalog_id': '123'}, 'order'),
            ('system', {'body': 'Number changed'}, 'system'),
            ('unsupported', {'raw_type': 'poll_creation'}, 'unsupported'),
            ('future_type', {}, 'unsupported'),
        ]
        for kind, detail, normalized in cases:
            with self.subTest(kind=kind, detail=detail):
                row, = self.extract(kind, detail)
                self.assertEqual(row['message_data']['kind'], normalized)
        self.assertEqual(self.extract('reaction', {'message_id': 'wamid.original', 'emoji': '👍'}), [])


class WhatsAppWebhookShapeTests(unittest.TestCase):
    """Payload shapes copied from live Relay Hub events and Meta's webhook reference."""
    setUp = ChannelProjectionTests.setUp

    def row(self, message):
        message = {'id': 'wamid.shape', 'timestamp': '1792948421', **message}
        return self.module.extract_messages({'entry': [{'changes': [{'value': {'messages': [message]}}]}]})

    def test_live_poll_shows_meta_reason(self):
        from relay_core.message_types import preview
        row, = self.row({'from': '919000000001', 'from_user_id': 'IN.fixture', 'type': 'unsupported',
            'errors': [{'code': 131051, 'error_data': {'details': 'Message type is currently not supported.'},
                        'message': 'Message type unknown', 'title': 'Message type unknown'}],
            'unsupported': {'raw_type': 'poll_creation', 'type': 'poll_creation'}})
        data = row['message_data']
        self.assertEqual(data['unsupported'], {'type': 'poll_creation', 'code': 131051, 'title': 'Message type unknown',
            'details': 'Message type is currently not supported.',
            'reason': 'Poll messages are not supported by WhatsApp Business'})
        self.assertEqual(preview(data), 'Poll messages are not supported by WhatsApp Business')

    def test_unavailable_and_unknown_unsupported_types(self):
        from relay_core.message_types import preview
        row, = self.row({'from': '919000000001', 'type': 'unsupported', 'unsupported': {'type': 'edit'},
            'errors': [{'code': 131060, 'title': 'This message is currently unavailable.'}]})
        self.assertEqual(preview(row['message_data']), 'This message is currently unavailable.')
        row, = self.row({'from': '919000000001', 'type': 'unsupported', 'unsupported': {'type': 'group_invite'}})
        self.assertEqual(preview(row['message_data']), 'Group invite messages are not supported by WhatsApp Business')
        row, = self.row({'from': '919000000001', 'type': 'brand_new_type', 'brand_new_type': {}})
        self.assertEqual(preview(row['message_data']), 'Brand new type messages are not supported by WhatsApp Business')

    def test_live_voice_note_and_unnamed_contact_card(self):
        from relay_core.message_types import preview
        row, = self.row({'from': '919000000001', 'type': 'audio', 'audio': {'id': '1680364653657585',
            'mime_type': 'audio/ogg; codecs=opus', 'sha256': 'digest', 'url': 'https://lookaside.invalid/x', 'voice': True}})
        self.assertEqual(row['message_data'], {'kind': 'audio', 'media': {'id': '1680364653657585',
            'mime_type': 'audio/ogg; codecs=opus', 'voice': True}})
        self.assertEqual(preview(row['message_data']), 'Voice message')
        # Live event failed before: WhatsApp sends no name for an unsaved contact.
        row, = self.row({'from': '919000000001', 'type': 'contacts', 'contacts': [{'origin': 'other', 'vcard': 'QkVHSU46VkNBUkQ=',
            'phones': [{'phone': '+91 90000 00002', 'type': 'MOBILE', 'wa_id': '919000000002'}]}]})
        card, = row['message_data']['contacts']
        self.assertEqual(card['name'], {'formatted_name': '+91 90000 00002'})
        self.assertEqual(card['phones'], [{'phone': '+91 90000 00002', 'type': 'MOBILE', 'wa_id': '919000000002'}])

    def test_order_location_sticker_and_list_reply(self):
        from relay_core.message_types import preview
        row, = self.row({'from': '16505551234', 'type': 'order', 'order': {'catalog_id': '194836987003835', 'text': 'Love these!',
            'product_items': [{'product_retailer_id': 'di9ozbzfi4', 'quantity': 2, 'item_price': 30, 'currency': 'USD'},
                              {'product_retailer_id': 'nqryix03ez', 'quantity': 1, 'item_price': 25, 'currency': 'USD'}]}})
        self.assertEqual(row['message_data']['order']['items'][0], {'product_retailer_id': 'di9ozbzfi4', 'currency': 'USD', 'quantity': 2, 'item_price': 30})
        self.assertEqual(preview(row['message_data']), 'Order: 2 items · Love these!')
        with self.assertRaises(ValueError):
            self.row({'from': '16505551234', 'type': 'order', 'order': {'product_items': [{'quantity': float('nan')}]}})
        row, = self.row({'from': '16505551234', 'type': 'location', 'location': {'address': '1 Hacker Way', 'latitude': 37.48,
            'longitude': -122.14, 'name': 'Head office', 'url': 'https://maps.invalid'}})
        self.assertEqual(row['message_data']['location'], {'latitude': 37.48, 'longitude': -122.14, 'name': 'Head office', 'address': '1 Hacker Way'})
        row, = self.row({'from': '16505551234', 'type': 'sticker', 'sticker': {'mime_type': 'image/webp', 'id': '1', 'animated': True, 'sha256': 'x', 'url': 'https://x.invalid'}})
        self.assertEqual(row['message_data'], {'kind': 'sticker', 'media': {'id': '1', 'mime_type': 'image/webp', 'animated': True}})
        row, = self.row({'from': '16505551234', 'type': 'interactive', 'interactive': {'type': 'list_reply',
            'list_reply': {'id': 'priority_express', 'title': 'Priority Mail Express', 'description': 'Next Day to 2 Days'}}})
        self.assertEqual(row['message_data']['text'], 'Priority Mail Express')

    def test_system_messages_are_notes_on_the_old_identity(self):
        from relay_core.message_types import preview
        row, = self.row({'from': '16505551234', 'type': 'system', 'system': {'body': 'User Sheena Nelson changed from 16505551234 to 12195555358',
            'wa_id': '12195555358', 'type': 'user_changed_number', 'user_id': 'US.1', 'previous_user_id': 'US.0'}})
        self.assertEqual(row['from'], '16505551234')
        self.assertEqual(row['message_data']['system']['wa_id'], '12195555358')
        self.assertEqual(preview(row['message_data']), 'User Sheena Nelson changed from 16505551234 to 12195555358')
        # A username user's identity change has no phone number at all.
        row, = self.row({'type': 'system', 'system': {'body': 'User changed from US.0 to US.1', 'type': 'user_changed_user_id',
            'user_id': 'US.1', 'previous_user_id': 'US.0'}})
        self.assertEqual(row['from'], 'US.0')
        row, = self.row({'from': '16505551234', 'type': 'request_welcome'})
        self.assertEqual(row['message_data'], {'kind': 'system', 'system': {'type': 'request_welcome'}})
        self.assertEqual(preview(row['message_data']), 'Customer opened the chat')

    def test_ad_referral_is_kept_without_provider_urls(self):
        row, = self.row({'from': '16505551234', 'type': 'text', 'text': {'body': 'Hi'}, 'referral': {'source_url': 'https://fb.me/x',
            'source_id': '120226305854810726', 'source_type': 'ad', 'body': 'Summer Succulents are here!', 'headline': 'Chat with us',
            'media_type': 'image', 'image_url': 'https://scontent.invalid/i', 'ctwa_clid': 'click', 'welcome_message': {'text': 'Hi there!'}}})
        self.assertEqual(row['message_data']['referral'], {'source_type': 'ad', 'source_id': '120226305854810726', 'headline': 'Chat with us',
            'body': 'Summer Succulents are here!', 'media_type': 'image', 'ctwa_clid': 'click', 'welcome_message': 'Hi there!'})
        self.assertNotIn('https://', json.dumps(row['message_data']))

    def test_edit_revoke_and_reaction_are_updates_not_turns(self):
        for message in ({'from': '1', 'type': 'reaction', 'reaction': {'message_id': 'wamid.a', 'emoji': ''}},
                        {'from': '1', 'type': 'edit', 'edit': {'original_message_id': 'wamid.a', 'message': {'type': 'text', 'text': {'body': 'Fixed'}}}},
                        {'from': '1', 'type': 'revoke', 'revoke': {'original_message_id': 'wamid.a'}}):
            self.assertEqual(self.row(message), [])

    def test_missing_identity_is_rejected(self):
        with self.assertRaises(ValueError):
            self.row({'type': 'text', 'text': {'body': 'Hi'}})
