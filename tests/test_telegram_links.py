"""One-time Telegram deep links save a verified chat for a user or a contact, once, on the bot they were made for."""
import time
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, parse_qs

from frappe import _dict
from relay_core import telegram_links as links

CHANNELS = {'Acme bot': 'site-a', 'Sales bot': 'site-a'}


class FakeCache:
    def __init__(self):
        self.values, self.ttl = {}, {}

    def set_value(self, key, value, expires_in_sec=None):
        self.values[key], self.ttl[key] = value, expires_in_sec

    def get_value(self, key, expires=False):
        return self.values.get(key)

    def delete_value(self, key):
        self.values.pop(key, None)

    def lock(self, *args, **kwargs):
        return nullcontext()


class TelegramLinkTests(unittest.TestCase):
    def setUp(self):
        self.cache, self.account = FakeCache(), 'site-a'
        self.fake = SimpleNamespace(cache=self.cache, session=SimpleNamespace(user='alex@example.com'),
                                    db=SimpleNamespace(get_value=lambda doctype, name, field: CHANNELS.get(name)),
                                    publish_realtime=Mock())
        self.enterContext(patch.object(links, 'frappe', self.fake))
        self.enterContext(patch.object(links, 'connection_value', lambda key: self.account))
        self.enroll = self.enterContext(patch('relay_core.contact_lifecycle.enroll', return_value=_dict(name='CE-1')))
        self.changed = self.enterContext(patch('relay_core.realtime.contact_changed'))
        self.enterContext(patch('relay_core.hub_channels.choose', side_effect=lambda medium, names, contact, requested: requested or 'Acme bot'))
        self.enterContext(patch('relay_core.channel_setup.relay_channel',
                                side_effect=lambda name, provider: _dict(name=name, hub_channel='tg-' + name, label=name)))
        self.enterContext(patch('relay_core.channel_setup.hub_call', return_value={'username': 'acme_textiles_bot', 'token_saved': True}))

    def code(self, contact='RELAY-CON-1', channel=None):
        result = links.new_link(contact, channel)
        self.assertEqual(urlsplit(result['url']).netloc, 't.me')
        self.assertEqual(urlsplit(result['url']).path, '/acme_textiles_bot')
        return parse_qs(urlsplit(result['url']).query)['start'][0]

    def start(self, code, channel='Acme bot', chat='4242', **context):
        row = {'from': chat, 'type': 'text', 'text': {'body': f'/start {code}'}, 'message_data': {'kind': 'text', 'text': f'/start {code}'}}
        context = {'chat_type': 'private', 'participant_id': int(chat), **context}
        return links.redeem(channel, row, context), row

    def test_link_keeps_only_the_hash_of_the_code_for_fifteen_minutes(self):
        code = self.code()
        key = links.CACHE + links.digest(code)
        self.assertEqual(list(self.cache.values), [key])
        self.assertNotIn(code, repr(self.cache.values))
        self.assertEqual(self.cache.ttl[key], 15 * 60)
        self.assertEqual(self.cache.values[key]['user'], 'alex@example.com')

    def test_valid_code_saves_the_verified_chat_and_hides_the_code(self):
        linked, row = self.start(self.code())
        self.assertEqual(linked, 'RELAY-CON-1')
        self.enroll.assert_called_once_with('RELAY-CON-1', 'Acme bot', 'Telegram', '4242')
        self.assertEqual(row['text'], {'body': '/start'})
        self.assertEqual(row['message_data'], {'kind': 'text', 'text': '/start'})
        self.fake.publish_realtime.assert_called_once_with('relay_changed', {'kind': 'telegram_link', 'linked': 1},
                                                           user='alex@example.com', after_commit=True)
        self.changed.assert_called_once_with('RELAY-CON-1', 'contacts')

    def test_expired_code_links_nothing(self):
        code = self.code()
        with patch.object(links.time, 'time', return_value=time.time() + links.CODE_SECONDS + 1):
            self.assertIsNone(self.start(code)[0])
        self.enroll.assert_not_called()

    def test_code_works_only_once(self):
        code = self.code()
        self.assertEqual(self.start(code)[0], 'RELAY-CON-1')
        self.assertIsNone(self.start(code, chat='5151')[0])
        self.enroll.assert_called_once()

    def test_code_of_another_site_links_nothing(self):
        code = self.code()
        self.account = 'site-b'
        self.assertIsNone(self.start(code)[0])
        self.enroll.assert_not_called()
        self.assertEqual(self.cache.values, {}, 'A refused code is spent')

    def test_code_made_for_another_bot_links_nothing(self):
        code = self.code(channel='Sales bot')
        self.assertIsNone(self.start(code, channel='Acme bot')[0])
        self.enroll.assert_not_called()
        self.assertEqual(self.cache.values, {}, 'A refused code is spent')

    def test_existing_binding_of_the_chat_is_never_replaced(self):
        self.enroll.return_value = None
        self.assertIsNone(self.start(self.code())[0])
        self.fake.publish_realtime.assert_called_once_with('relay_changed', {'kind': 'telegram_link', 'linked': 0},
                                                           user='alex@example.com', after_commit=True)
        self.changed.assert_not_called()

    def test_only_a_private_chat_of_the_sender_can_use_a_code(self):
        for context in ({'chat_type': 'group'}, {'sender_chat_id': -100}, {'participant_id': 9999}):
            with self.subTest(context=context):
                code = self.code()
                linked, row = self.start(code, **context)
                self.assertIsNone(linked)
                self.assertIn(code, row['text']['body'])
        self.enroll.assert_not_called()

    def test_other_texts_are_not_codes(self):
        for body in ('/start', '/start short', 'hello /start ' + 'a' * 32, '/start ' + 'a' * 33):
            with self.subTest(body=body):
                self.assertIsNone(links.start_code({'from': '4242', 'type': 'text', 'text': {'body': body}},
                                                   {'chat_type': 'private', 'participant_id': 4242}))

    def test_bot_without_a_username_gives_no_link(self):
        with patch('relay_core.channel_setup.hub_call', return_value={'username': ''}), \
                patch('relay_core.channel_setup.fail', side_effect=LookupError):
            with self.assertRaises(LookupError):
                links.new_link('RELAY-CON-1')
        self.assertEqual(self.cache.values, {})


if __name__ == '__main__':
    unittest.main()
