"""Replies leave from the number the customer wrote to last; staff may pick another; the Hub hears which one."""
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from frappe import _dict
from channel_fakes import FakeSite
from relay_core import channel_statuses, hub_channels, messaging, whatsapp_presence

SHOP = {'name': 'Shop', 'channel': 'WhatsApp', 'account': 'site-a', 'hub_channel': 'site-a', 'enabled': 1, 'label': 'Shop',
        'address': '+91 1', 'title': 'Shop'}
SUPPORT = dict(SHOP, name='Support', hub_channel='wa-2', label='Support', address='+91 2', title='Support')
OTHER = dict(SHOP, name='Other', account='site-b', hub_channel='wa-9')


def message(name, channel, direction='Incoming', contact='C1', creation=0):
    return {'name': name, 'channel': channel, 'direction': direction, 'relay_contact': contact, 'creation': creation}


def fake_site(messages=(), channels=(SHOP, SUPPORT), **tables):
    endpoints = [{'channel': name, 'relay_contact': 'C1', 'verified': 1} for name in ('Shop', 'Support')]
    return FakeSite(Relay_Channel=list(channels), Relay_Message=list(messages), Relay_Contact_Endpoint=endpoints, **tables)


class Patched(unittest.TestCase):
    def patched(self, site):
        stack = ExitStack()
        for module in (messaging, hub_channels):
            stack.enter_context(patch.object(module, 'frappe', site.frappe))
        stack.enter_context(patch('relay_core.settings.value', return_value='site-a'))
        stack.enter_context(patch.object(messaging, 'connection_value', return_value='site-a'))
        stack.enter_context(patch.object(messaging, 'readable_contact'))
        stack.enter_context(patch.object(messaging, 'request_hash', side_effect=lambda key: 'hash-' + key))
        stack.enter_context(patch.object(messaging, 'validate_reference'))
        stack.enter_context(patch.object(messaging, 'readable_source', side_effect=lambda name: (
            site.rows('Relay Message', {'name': name})[0], None, {})))
        return stack


class SendNumbersTests(Patched):
    def numbers(self, site):
        with self.patched(site), patch.object(messaging, 'require_access'), patch(
                'relay_core.service_window.status', side_effect=lambda contact, channel: {'open': channel == 'Support', 'remaining_seconds': 60}):
            return messaging.send_numbers('C1')

    def test_numbers_show_chats_windows_and_the_newest_incoming_number(self):
        site = fake_site([message('M1', 'Shop', creation=1), message('M2', 'Support', creation=2),
                          message('M3', 'Shop', 'Outgoing', creation=3)])
        result = self.numbers(site)
        self.assertEqual(result['default'], 'Support')
        self.assertEqual([(row['channel'], row['label'], row['address'], row['has_chat'], row['window']['open']) for row in result['items']],
                         [('Shop', 'Shop', '+91 1', True, False), ('Support', 'Support', '+91 2', True, True)])

    def test_a_number_without_a_chat_is_template_only_and_other_sites_are_hidden(self):
        site = fake_site([message('M1', 'Shop', creation=1)], channels=(SHOP, SUPPORT, OTHER))
        result = self.numbers(site)
        self.assertEqual(result['default'], 'Shop')
        self.assertEqual([(row['channel'], row['has_chat'], row['window']['open']) for row in result['items']],
                         [('Shop', True, False), ('Support', False, False)])

    def test_without_incoming_messages_the_site_default_or_none_is_used(self):
        site = fake_site([message('M1', 'Shop', 'Outgoing', creation=1)], channels=(SHOP, dict(SUPPORT, is_default=1)))
        self.assertEqual(self.numbers(site)['default'], 'Support')
        self.assertIsNone(self.numbers(fake_site())['default'])

    def test_a_contact_the_user_cannot_read_is_denied(self):
        with self.patched(fake_site()), patch.object(messaging, 'require_access'):
            messaging.readable_contact.side_effect = PermissionError
            with self.assertRaises(PermissionError):
                messaging.send_numbers('C1')


class ReplyChannelTests(Patched):
    def test_customer_who_wrote_to_a_then_b_gets_the_reply_via_b(self):
        site = fake_site([message('M1', 'Shop', creation=1), message('M2', 'Support', creation=2),
                          message('M3', 'Shop', 'Outgoing', creation=3)])
        with self.patched(site):
            self.assertEqual(messaging.reply_source('M3', 'text', 'k1', 'auto', 1), ('M2', 0))
            self.assertEqual(messaging.reply_channel('C1')['channel'], 'Support')

    def test_a_reply_to_the_newest_incoming_message_keeps_its_quote(self):
        site = fake_site([message('M1', 'Shop', creation=1), message('M2', 'Support', creation=2)])
        with self.patched(site):
            self.assertEqual(messaging.reply_source('M2', 'text', 'k1', 'auto', 1), ('M2', 1))

    def test_staff_pick_is_honoured_and_legacy_calls_keep_their_source(self):
        site = fake_site([message('M1', 'Shop', creation=1), message('M2', 'Support', creation=2)])
        with self.patched(site):
            self.assertEqual(messaging.reply_source('M2', 'text', 'k1', 'Shop', 1), ('M1', 0))
            self.assertEqual(messaging.reply_source('M1', 'text', 'k1', None, 1), ('M1', 1))

    def test_a_foreign_or_unused_channel_is_denied(self):
        site = fake_site([message('M1', 'Shop', creation=1), message('X1', 'Other', contact='C2', creation=2)],
                         channels=(SHOP, SUPPORT, OTHER))
        with self.patched(site):
            for via in ('Other', 'Support'):
                with self.subTest(via=via), self.assertRaises(ValueError):
                    messaging.reply_source('M1', 'text', 'k1', via, 1)
            with self.assertRaises(ValueError):
                messaging.reply_source('M1', 'reaction', 'k1', 'Support', 1)

    def test_a_retry_keeps_the_source_of_its_first_try(self):
        site = fake_site([message('M1', 'Shop', creation=1), message('M2', 'Support', creation=2)],
                         Relay_Message_Action=[{'request_key': 'hash-k1', 'source_message': 'M1'}])
        with self.patched(site):
            self.assertEqual(messaging.reply_source('M1', 'text', 'k1', 'auto', 1), ('M1', 1))

    def test_send_resolves_the_source_before_sending(self):
        with patch.object(messaging, 'reply_source', return_value=('M2', 0)) as pick, \
                patch.object(messaging, 'send_one', return_value={'action': 'A'}) as send_one, \
                patch.object(messaging, 'channel_sources', return_value=[]), \
                patch.object(messaging, 'request_hash', return_value='hash'):
            messaging.send('M1', 'text', {'text': 'Hi'}, 'k1', 1, via='auto')
        pick.assert_called_once_with('M1', 'text', 'k1', 'auto', 1)
        send_one.assert_called_once_with('M2', 'text', {'text': 'Hi'}, 'k1', 0)


class ChooseTests(Patched):
    def choose(self, site, **arguments):
        with self.patched(site):
            return hub_channels.choose('WhatsApp', **arguments)

    def test_order_is_pick_latest_incoming_team_site_default_only(self):
        both = [message('M1', 'Support', creation=1)]
        self.assertEqual(self.choose(fake_site(both), contact='C1', requested='Shop'), 'Shop')
        self.assertEqual(self.choose(fake_site(both), contact='C1'), 'Support')
        team = fake_site(Relay_Conversation_Assignment=[{'relay_contact': 'C1', 'team': 'T'}],
                         Relay_Team=[{'name': 'T', 'default_whatsapp_channel': 'Support'}])
        self.assertEqual(self.choose(team, contact='C1'), 'Support')
        default = fake_site(channels=(SHOP, dict(SUPPORT, is_default=1)))
        self.assertEqual(self.choose(default), 'Support')
        self.assertEqual(self.choose(fake_site(channels=(SHOP,))), 'Shop')

    def test_no_choice_or_a_foreign_pick_fails_loudly(self):
        with self.assertRaises(ValueError):
            self.choose(fake_site())
        with self.assertRaises(ValueError):
            self.choose(fake_site(channels=(SHOP, SUPPORT, OTHER)), requested='Other')
        with self.assertRaises(ValueError):
            self.choose(fake_site(), names=['Shop'], requested='Support')


class HubArgumentTests(unittest.TestCase):
    def arguments(self, channels, channel):
        site = FakeSite(Relay_Channel=list(channels))
        with patch.object(hub_channels, 'frappe', site.frappe):
            return hub_channels.hub_arguments(channel, {'to': '1'})

    def test_the_key_is_named_only_when_the_site_has_a_choice(self):
        self.assertEqual(self.arguments([SHOP], 'Shop'), {'to': '1'})
        self.assertEqual(self.arguments([SHOP, SUPPORT], 'Support'), {'to': '1', 'channel': 'wa-2'})
        self.assertEqual(self.arguments([SHOP, SUPPORT], _dict(SHOP)), {'to': '1', 'channel': 'site-a'})
        self.assertEqual(self.arguments([SHOP, dict(SUPPORT, hub_channel=None)], 'Support'), {'to': '1'})

    def test_read_receipt_goes_from_the_receiving_number(self):
        hub = Mock()
        with patch('relay_core.whatsapp.client', return_value=hub), \
                patch.object(hub_channels, 'hub_arguments', side_effect=lambda channel, args: dict(args, channel=channel)):
            whatsapp_presence.send('wamid.1', typing=True, channel='Support')
        hub.execute.assert_called_once_with({'operation': 'messages.read', 'message_id': 'wamid.1', 'typing': True,
                                             'channel': 'Support'})


class StartChannelTests(unittest.TestCase):
    def endpoint(self, channel, channels=(SHOP, SUPPORT, dict(SHOP, name='Bot', channel='Telegram', hub_channel='bot'))):
        import hashlib
        from relay_core import contact_lifecycle, conversation_start
        key = lambda name, value: hashlib.sha256((name + ':' + value).encode()).hexdigest()
        site = FakeSite(Relay_Channel=list(channels), Relay_Contact_Endpoint=[
            {'name': 'E1', 'channel': 'Shop', 'endpoint': '919999999999', 'relay_contact': 'C1', 'verified': 1,
             'endpoint_key': key('Shop', '919999999999')}],
            on_insert={'Relay Contact Endpoint': lambda row: row.update(endpoint_key=key(row['channel'], row['endpoint']))})
        with patch.object(conversation_start, 'frappe', site.frappe), patch.object(contact_lifecycle, 'frappe', site.frappe), \
                patch('frappe.get_all', site.get_all), patch.object(conversation_start, 'readable_contact'), \
                patch.object(conversation_start, 'connection_value', return_value='site-a'):
            return conversation_start.channel_endpoint('C1', 'E1', channel), site

    def test_staff_can_start_from_another_number_of_the_same_type(self):
        self.assertEqual(self.endpoint(None)[0], 'E1')
        name, site = self.endpoint('Support')
        self.assertEqual(site.rows('Relay Contact Endpoint', {'name': name})[0].channel, 'Support')

    def test_another_type_or_a_foreign_channel_is_denied(self):
        for channel in ('Bot', 'Other'):
            with self.subTest(channel=channel), self.assertRaises(PermissionError):
                self.endpoint(channel, channels=(SHOP, SUPPORT, OTHER, dict(SHOP, name='Bot', channel='Telegram', hub_channel='bot')))


class ReceiptTests(unittest.TestCase):
    def test_a_receipt_applies_to_its_send_after_the_channel_is_switched_off(self):
        off = dict(SUPPORT, enabled=0)
        self.assertFalse(hub_channels.is_current(_dict(off), 'site-a'))
        token = hub_channels.applying_receipt.set(True)
        try:
            self.assertTrue(hub_channels.is_current(_dict(off), 'site-a'))
        finally:
            hub_channels.applying_receipt.reset(token)
        site = FakeSite(Relay_Channel=[SHOP, off])
        with patch.object(hub_channels, 'frappe', site.frappe), patch('relay_core.channel_sync.queue_sync'):
            self.assertIsNone(hub_channels.event_channel('site-a', 'WhatsApp', 'wa-2'))
            self.assertEqual(hub_channels.event_channel('site-a', 'WhatsApp', 'wa-2', receipts=True), 'Support')

    def test_channel_statuses_resolve_the_target_as_a_receipt(self):
        action = _dict(name='action', status='Dispatching', result='{}', owner='agent@example.invalid',
                       payload='{"content":{"kind":"text","text":"Hi"}}', check_permission=Mock())
        fake = Mock(PermissionError=PermissionError, DoesNotExistError=LookupError, ValidationError=TypeError,
                    QueryDeadlockError=RuntimeError, session=_dict(user='Administrator'))
        fake.db.get_value.side_effect = lambda doctype, *args, **kwargs: 'action' if doctype == 'Relay Message Action' else 1
        fake.get_doc.return_value = action
        seen = []
        def target(_):
            seen.append(hub_channels.applying_receipt.get())
            return _dict(), _dict(channel='WhatsApp', account='site-a', hub_channel='wa-2', enabled=0), {}
        row = {'id': 2, 'request_key': 'key', 'operation': 'whatsapp.execute', 'state': 'submitted',
               'receipt': {'message_id': 'wamid.1'}}
        with patch.object(channel_statuses, 'frappe', fake), patch.object(channel_statuses, 'connection_value', return_value='site-a'), \
                patch.object(channel_statuses.messaging, 'action_target', side_effect=target), \
                patch.object(channel_statuses.messaging, 'finish') as finish, patch('relay_core.realtime.incoming_changed'):
            channel_statuses.project_batch(_dict(name='event', account='site-a', hub_channel='wa-2'), [row])
        self.assertEqual(seen, [True])
        finish.assert_called_once()
        self.assertFalse(hub_channels.applying_receipt.get())


class TelegramChannelTests(unittest.TestCase):
    def test_a_chat_sends_only_from_its_own_bot(self):
        from relay_core import telegram
        import frappe as real_frappe
        def throw(message, exc=real_frappe.ValidationError):
            raise exc(message)
        with patch.object(telegram, 'require_access'), patch.object(telegram, 'group_binding', return_value=('C1', 'Bot')), \
                patch.object(telegram.frappe, 'throw', throw), \
                patch('relay_core.telegram_delivery.send_group', return_value={'accepted': 1}) as send_group:
            telegram.send(-1001, 'Hi', channel='Bot')
            self.assertEqual(send_group.call_args.args[1], 'Bot')
            with self.assertRaises(real_frappe.PermissionError):
                telegram.send(-1001, 'Hi', channel='Other bot')
        send_group.assert_called_once()


if __name__ == '__main__':
    unittest.main()
