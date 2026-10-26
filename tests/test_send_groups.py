"""One composed message sent to several channels shares one send group."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core import messaging, whatsapp_receipts


class SendGroupTests(unittest.TestCase):
    def send(self, channels=None):
        sent = []
        def send_one(*args):
            sent.append(args)
            return {'action': 'action-' + str(len(sent)), 'status': 'Submitted', 'message': 'message-' + str(len(sent))}
        with patch.object(messaging, 'send_one', side_effect=send_one), \
             patch.object(messaging, 'channel_sources', return_value=channels or []), \
             patch.object(messaging.frappe, 'session', _dict(user='agent')):
            return messaging.send('MSG-1', 'text', {'text': 'Hi'}, 'key', 1, channels), sent

    def test_one_channel_send_keeps_its_result_and_has_no_group(self):
        result, sent = self.send()
        self.assertEqual(result, {'action': 'action-1', 'status': 'Submitted', 'message': 'message-1'})
        self.assertEqual(sent, [('MSG-1', 'text', {'text': 'Hi'}, 'key', 1)])

    def test_every_channel_copy_shares_one_group_and_has_its_own_request_key(self):
        result, sent = self.send(['MSG-TG'])
        group = result['send_group']
        self.assertEqual(len(group), 32)
        self.assertEqual(sent[0], ('MSG-1', 'text', {'text': 'Hi'}, 'key', 1, group))
        self.assertEqual(sent[1][:3] + sent[1][4:], ('MSG-TG', 'text', {'text': 'Hi'}, 0, group))
        self.assertRegex(sent[1][3], r'^[a-f0-9]{40}$')
        self.assertEqual(result['message'], 'message-1')
        self.assertEqual([row['message'] for row in result['sends']], ['message-1', 'message-2'])
        self.assertEqual(self.send(['MSG-TG'])[0]['send_group'], group)


class ChannelSourceTests(unittest.TestCase):
    def sources(self, names, kind='text', providers=None, newest='MSG-TG'):
        source = _dict(name='MSG-1', channel='CH-WA', relay_contact='CON-1')
        providers = providers or {'CH-TG': 'Telegram'}
        def get_value(doctype, filters, field, **kwargs):
            return providers.get(filters) if doctype == 'Relay Channel' else newest
        enabled = [SimpleNamespace(name='WhatsApp'), SimpleNamespace(name='Telegram')]
        with patch.object(messaging, 'readable_source', return_value=(source, None, {})), \
             patch.object(messaging.channels, 'enabled', return_value=enabled), \
             patch.object(messaging.frappe, 'db', Mock(get_value=Mock(side_effect=get_value))) as db:
            return messaging.channel_sources('MSG-1', kind, names), db.get_value

    def test_extra_channel_uses_the_newest_message_of_the_same_person(self):
        found, lookup = self.sources(json.dumps(['CH-WA', 'CH-TG']))
        self.assertEqual(found, ['MSG-TG'])
        lookup.assert_called_with('Relay Message', {'relay_contact': 'CON-1', 'channel': 'CH-TG'}, 'name',
            order_by='creation desc')

    def test_no_channels_or_only_the_source_channel_sends_once(self):
        self.assertEqual(messaging.channel_sources('MSG-1', 'text', None), [])
        self.assertEqual(self.sources(['CH-WA'], kind='reaction')[0], [])

    def test_unsafe_fan_out_is_refused(self):
        for names, kind, providers, newest in (
                (['CH-TG'], 'reaction', None, 'MSG-TG'),
                (['CH-TG'], 'photo', None, 'MSG-TG'),
                (['CH-EM'], 'text', {'CH-EM': 'Email'}, 'MSG-EM'),
                (['CH-TG'], 'text', None, None),
                (['CH-TG', 'CH-TG'], 'text', None, 'MSG-TG'),
                ('not-a-list', 'text', None, 'MSG-TG'),
                ([{'name': 'CH-TG'}], 'text', None, 'MSG-TG')):
            with self.subTest(names=names, kind=kind), self.assertRaises(ValueError):
                self.sources(names, kind, providers, newest)


class SendGroupStorageTests(unittest.TestCase):
    def test_outgoing_message_keeps_the_send_group_of_its_action(self):
        payload = {'business': ['Customer', 'C-1'], 'arguments': {}, 'send_group': 'group'}
        action = _dict(name='action', status='Queued', operation='text', request_key='key',
            payload=json.dumps(payload), reload=Mock())
        source = _dict(relay_contact='contact', channel='channel', sender_endpoint='15550000001')
        created = []
        def get_doc(values):
            doc = _dict(values, name='outgoing'); doc.insert = Mock(return_value=doc); created.append(doc); return doc
        fake = SimpleNamespace(db=Mock(), get_doc=get_doc)
        with patch.object(messaging, 'frappe', fake), patch.object(messaging, 'internal_save'), \
             patch.object(whatsapp_receipts, 'lock_endpoints'), patch.object(whatsapp_receipts, 'apply_pending'):
            messaging.finish(action, source, _dict(channel='WhatsApp', name='channel'), {'provider': 'WhatsApp'},
                {'kind': 'text', 'text': 'Hello'}, {'messages': [{'id': 'provider'}]})
        self.assertEqual(created[0].send_group, 'group')


if __name__ == '__main__':
    unittest.main()
