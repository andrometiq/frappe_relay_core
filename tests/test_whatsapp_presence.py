"""WhatsApp read receipts and typing indicators: selection, settings, leases and Hub payloads."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core import whatsapp_presence
from relay_core.hub import HubError


def setUpModule():
    """Every user in these tests holds a Relay writer role."""
    writer = patch('relay_core.permissions.can_write', return_value=True)
    writer.start()
    unittest.addModuleCleanup(writer.stop)


class Lease:
    def __init__(self):
        self.keys = {}

    def make_key(self, key):
        return 'site|' + key

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return False
        self.keys[key] = ex
        return True


def row(name, context=None, provider_id=None):
    context = {'provider': 'WhatsApp', 'message_id': provider_id or 'wamid.' + name} if context is None else context
    return _dict(name=name, provider_id=provider_id or 'wamid.' + name, provider_context=json.dumps(context), channel='WA')


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'send_whatsapp_read_receipts': 1, 'send_whatsapp_typing': 1}
        self.rows = [row('MSG-3'), row('MSG-2')]
        self.cache = Lease()
        self.frappe = Mock()
        self.frappe.cache = self.cache
        self.frappe.get_cached_doc.return_value = _dict(self.settings)
        self.frappe.get_all.side_effect = lambda doctype, **kwargs: ['CH-WA'] if doctype == 'Relay Channel' else self.rows
        self.frappe.utils = SimpleNamespace(add_days=lambda value, days: ('days', days), now_datetime=lambda: 'now')
        patcher = patch.object(whatsapp_presence, 'frappe', self.frappe)
        patcher.start()
        self.addCleanup(patcher.stop)
        account = patch.object(whatsapp_presence, 'connection_value', return_value='hub-account')
        account.start()
        self.addCleanup(account.stop)
        latest = patch.object(whatsapp_presence, 'latest', side_effect=lambda *args, **kwargs: self.rows)
        self.latest = latest.start()
        self.addCleanup(latest.stop)

    def test_read_receipt_queues_the_newest_recent_direct_message_once(self):
        self.assertTrue(whatsapp_presence.mark_read('CON-1', ['MSG-2', 'MSG-3']))
        self.assertFalse(whatsapp_presence.mark_read('CON-1', ['MSG-2', 'MSG-3']))
        self.frappe.enqueue.assert_called_once_with('relay_core.whatsapp_presence.send', queue='short',
            job_id='relay-whatsapp-read:MSG-3', deduplicate=True, message_id='wamid.MSG-3', typing=False, channel='WA')
        self.assertEqual(self.cache.keys, {'site|relay-whatsapp-read:CON-1:MSG-3': 5})
        filters = self.latest.call_args.args[0]
        self.assertEqual(filters['name'], ['in', ['MSG-2', 'MSG-3']])
        self.assertEqual((filters['channel'], filters['direction']), (['in', ['CH-WA']], 'Incoming'))
        # Imported history qualifies by its real message time, like a live message.
        self.assertNotIn('legacy_source', filters)
        self.assertEqual(self.latest.call_args.kwargs, {'since': ('days', -30), 'limit': 20})
        self.frappe.get_all.assert_any_call('Relay Channel', filters={'channel': 'WhatsApp', 'account': 'hub-account'}, pluck='name')

    def test_a_user_without_a_relay_writer_role_leaves_no_trace_for_the_customer(self):
        with patch('relay_core.permissions.can_write', return_value=False):
            self.assertFalse(whatsapp_presence.mark_read('CON-1', ['MSG-3']))
            self.assertFalse(whatsapp_presence.typing('CON-1', 'CH-WA'))
        self.frappe.enqueue.assert_not_called()
        self.assertEqual(self.cache.keys, {})

    def test_a_newer_message_gets_its_own_receipt_inside_the_lease(self):
        whatsapp_presence.mark_read('CON-1', ['MSG-3'])
        self.rows = [row('MSG-4')]
        self.assertTrue(whatsapp_presence.mark_read('CON-1', ['MSG-4']))
        self.assertEqual(self.frappe.enqueue.call_count, 2)

    def test_groups_other_providers_and_missing_channels_send_nothing(self):
        self.rows = [row('MSG-9', {'provider': 'WhatsApp', 'group_id': 'G1'}), row('MSG-8', {'provider': 'Telegram'})]
        self.assertFalse(whatsapp_presence.mark_read('CON-1', ['MSG-8', 'MSG-9']))
        self.rows = [row('MSG-9', {'provider': 'WhatsApp', 'group_id': 'G1'}), row('MSG-7')]
        self.assertTrue(whatsapp_presence.mark_read('CON-1', ['MSG-7', 'MSG-9']))
        self.assertEqual(self.frappe.enqueue.call_args.kwargs['message_id'], 'wamid.MSG-7')
        self.frappe.get_all.side_effect = lambda doctype, **kwargs: []
        self.assertIsNone(whatsapp_presence.newest_incoming('CON-1', ['MSG-7']))

    def test_settings_switch_each_signal_off(self):
        self.frappe.get_cached_doc.return_value = _dict(send_whatsapp_read_receipts=0, send_whatsapp_typing=0)
        self.assertFalse(whatsapp_presence.mark_read('CON-1', ['MSG-3']))
        self.assertFalse(whatsapp_presence.typing('CON-1', 'CH-WA'))
        self.frappe.get_all.assert_not_called()
        self.frappe.enqueue.assert_not_called()

    def test_typing_uses_the_source_channel_and_a_four_second_contact_lease(self):
        self.assertTrue(whatsapp_presence.typing('CON-1', 'CH-WA'))
        self.assertFalse(whatsapp_presence.typing('CON-1', 'CH-WA'))
        self.frappe.enqueue.assert_called_once_with('relay_core.whatsapp_presence.send', queue='short',
            job_id='relay-whatsapp-read:MSG-3:typing', deduplicate=True, message_id='wamid.MSG-3', typing=True, channel='WA')
        self.assertEqual(self.cache.keys, {'site|relay-whatsapp-typing:CON-1': 4})
        filters = self.latest.call_args.args[0]
        self.assertEqual(filters['channel'], ['in', ['CH-WA']])
        self.assertNotIn('name', filters)

    def test_direct_channel_accepts_only_one_to_one_whatsapp(self):
        whatsapp = SimpleNamespace(channel='WhatsApp', name='CH-WA')
        self.assertEqual(whatsapp_presence.direct_channel(whatsapp, {'provider': 'WhatsApp'}), 'CH-WA')
        self.assertIsNone(whatsapp_presence.direct_channel(whatsapp, {'provider': 'WhatsApp', 'group_id': 'G1'}))
        self.assertIsNone(whatsapp_presence.direct_channel(SimpleNamespace(channel='Telegram', name='CH-TG'), {'provider': 'Telegram'}))


class SendTests(unittest.TestCase):
    def test_send_posts_one_direct_read_and_swallows_hub_rejections(self):
        hub = Mock()
        with patch('relay_core.whatsapp.client', return_value=hub):
            whatsapp_presence.send('wamid.A')
            whatsapp_presence.send('wamid.B', typing=True)
            hub.execute.side_effect = HubError('expired message')
            whatsapp_presence.send('wamid.C')
            hub.execute.side_effect = RuntimeError('bug')
            with self.assertRaises(RuntimeError):
                whatsapp_presence.send('wamid.D')
        self.assertEqual([call.args[0] for call in hub.execute.call_args_list[:2]], [
            {'operation': 'messages.read', 'message_id': 'wamid.A'},
            {'operation': 'messages.read', 'message_id': 'wamid.B', 'typing': True}])


class AutoSeenOffTests(unittest.TestCase):
    """Auto seen off: reading and typing leave no trace; an operator reply sends the blue ticks."""

    def setUp(self):
        PresenceTests.setUp(self)
        self.frappe.get_cached_doc.return_value = _dict(send_whatsapp_read_receipts=0, send_whatsapp_typing=1)
        self.source = _dict(name='MSG-3', relay_contact='CON-1')
        self.channel = SimpleNamespace(channel='WhatsApp', name='CH-WA')

    def test_reading_and_typing_send_nothing(self):
        self.assertFalse(whatsapp_presence.mark_read('CON-1', ['MSG-3']))
        self.assertFalse(whatsapp_presence.typing('CON-1', 'CH-WA'))
        self.frappe.enqueue.assert_not_called()

    def test_a_reply_marks_the_newest_incoming_message_read_once(self):
        self.assertTrue(whatsapp_presence.mark_replied(self.source, self.channel, {'provider': 'WhatsApp'}))
        self.assertFalse(whatsapp_presence.mark_replied(self.source, self.channel, {'provider': 'WhatsApp'}))
        self.frappe.enqueue.assert_called_once_with('relay_core.whatsapp_presence.send', queue='short',
            job_id='relay-whatsapp-read:MSG-3', deduplicate=True, message_id='wamid.MSG-3', typing=False, channel='WA')
        self.assertEqual(self.latest.call_args.args[0]['channel'], ['in', ['CH-WA']])

    def test_a_reply_sends_nothing_for_groups_readers_or_with_auto_seen_on(self):
        self.assertFalse(whatsapp_presence.mark_replied(self.source, self.channel, {'provider': 'WhatsApp', 'group_id': 'G1'}))
        with patch('relay_core.permissions.can_write', return_value=False):
            self.assertFalse(whatsapp_presence.mark_replied(self.source, self.channel, {'provider': 'WhatsApp'}))
        self.frappe.get_cached_doc.return_value = _dict(send_whatsapp_read_receipts=1, send_whatsapp_typing=1)
        self.assertFalse(whatsapp_presence.mark_replied(self.source, self.channel, {'provider': 'WhatsApp'}))
        self.frappe.enqueue.assert_not_called()


class ReplyReceiptHookTests(unittest.TestCase):
    """Only an operator reply through messaging.send_one asks for the reply receipt."""

    def run_send(self, run=None):
        from relay_core import messaging
        source, channel, context = _dict(name='MSG-3', relay_contact='CON-1'), SimpleNamespace(channel='WhatsApp', name='CH-WA'), {'provider': 'WhatsApp'}
        fake = Mock()
        fake.db.get_value.return_value = None
        fake.session.user = 'operator'
        fake.ValidationError, fake.PermissionError, fake.DoesNotExistError = ValueError, PermissionError, LookupError
        token = messaging.outgoing_run.set(run)
        self.addCleanup(messaging.outgoing_run.reset, token)
        with patch.object(messaging, 'frappe', fake), \
                patch.object(messaging, 'readable_source', side_effect=[(source, channel, context), ValueError('stop')]), \
                patch.object(messaging, 'prepare', return_value=('whatsapp.execute', {}, {'text': 'Hi'})), \
                patch.object(messaging, 'delivery_snapshot'), patch.object(messaging, 'require_reply_window'), \
                patch.object(messaging, 'internal_save'), patch('relay_core.tickets.manual_takeover'), \
                patch('relay_core.whatsapp_presence.mark_replied') as replied:
            messaging.send_one('MSG-3', 'text', {'text': 'Hi'}, 'key')
        return replied, (source, channel, context)

    def test_an_operator_reply_asks_for_the_receipt(self):
        replied, arguments = self.run_send()
        replied.assert_called_once_with(*arguments)

    def test_an_automation_reply_does_not(self):
        replied, _ = self.run_send(run='RUN-1')
        replied.assert_not_called()


if __name__ == '__main__':
    unittest.main()
