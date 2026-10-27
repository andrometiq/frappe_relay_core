"""Hub events name their receiving channel; payloads without a channel key keep the single-channel rule."""
import hashlib
import hmac
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe import _dict
from channel_fakes import FakeSite
from relay_core import channel_statuses, hub_channels, inbound
from relay_core.automation import projection

SECRET = 's' * 64
SHOP = {'channel': 'WhatsApp', 'account': 'site-a', 'hub_channel': 'site-a', 'enabled': 1, 'name': 'Shop'}
SUPPORT = dict(SHOP, hub_channel='wa-2', name='Support')


def signed(payload):
    raw = json.dumps(payload).encode()
    now = str(int(time.time()))
    return raw, now, hmac.new(SECRET.encode(), now.encode() + b'.' + raw, hashlib.sha256).hexdigest()


def text(number):
    return {'entry': [{'changes': [{'field': 'messages', 'value': {
        'metadata': {'phone_number_id': number}, 'messages': [
            {'id': 'wamid.' + number, 'from': '919999999999', 'type': 'text', 'text': {'body': 'Hello'}}]}}]}]}


def status(position, key=None):
    row = {'event_id': 7, 'position': position, 'message_id': f'wamid.{position}', 'recipient': '919999999999',
           'status': 'delivered', 'timestamp': 1}
    return dict(row, channel_key=key, to='+91 90000 0000' + str(position)) if key else row


class ReceiveTests(unittest.TestCase):
    def receive(self, method, payload):
        raw, stamp, signature = signed(payload)
        fake = SimpleNamespace(get_roles=lambda user: ['Relay Hub Service'], session=_dict(user='service'),
                               request=Mock(get_data=Mock(return_value=raw), headers={
                                   'X-Relay-Timestamp': stamp, 'X-Relay-Signature': signature}),
                               db=Mock(), publish_realtime=Mock(), throw=Mock(side_effect=ValueError),
                               PermissionError=PermissionError, QueryDeadlockError=RuntimeError)
        fake.db.get_value.return_value = None
        fake.db.exists.return_value = False
        settings = {'relay_callback_secret': SECRET, 'relay_hub_account': 'site-a'}
        with patch.object(inbound, 'frappe', fake), patch.object(inbound, 'connection_value', settings.get), \
                patch.object(inbound, 'insert_event', return_value=_dict(flags=_dict())) as insert:
            getattr(inbound, method)()
        return [call.args[0] for call in insert.call_args_list]

    def test_events_store_their_channel_key_and_legacy_events_store_none(self):
        rows = self.receive('receive', {'account': 'site-a', 'channel_key': 'site-a', 'events': [
            {'id': 1, 'channel_key': 'wa-2', 'to': '+91 90000 00002', 'payload': text('2')},
            {'id': 2, 'payload': text('1')}]})
        self.assertEqual([row['hub_channel'] for row in rows], ['wa-2', 'site-a'])
        legacy = self.receive('receive', {'account': 'site-a', 'events': [{'id': 3, 'payload': text('1')}]})
        self.assertIsNone(legacy[0]['hub_channel'])

    def test_a_status_batch_of_two_numbers_becomes_one_event_per_number(self):
        payload = {'account': 'site-a', 'statuses': [status(1, 'site-a'), status(2, 'wa-2'), status(3, 'site-a')]}
        rows = self.receive('receive_statuses', payload)
        self.assertEqual([row['hub_channel'] for row in rows], ['site-a', 'wa-2'])
        self.assertTrue(all(row['event_key'].startswith('statuses:') for row in rows))
        self.assertEqual(len({row['event_key'] for row in rows}), 2)
        first = json.loads(rows[0]['payload'])['entry'][0]['changes'][0]['value']['statuses']
        self.assertEqual([row['id'] for row in first], ['wamid.1', 'wamid.3'])

    def test_a_legacy_status_batch_keeps_its_original_event_key(self):
        payload = {'account': 'site-a', 'statuses': [status(1)]}
        rows = self.receive('receive_statuses', payload)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual((rows[0]['event_key'], rows[0]['hub_channel']), ('statuses:' + digest, None))

    def test_channel_status_and_bulk_batches_accept_the_channel_key(self):
        row = {'id': 1, 'delivery_id': 4, 'request_key': 'key', 'operation': 'whatsapp.execute', 'state': 'cancelled',
               'receipt': {}, 'occurred_at': '2026-10-27T00:00:00Z', 'channel_key': 'wa-2', 'to': '+91'}
        rows = self.receive('receive_channel_statuses', {'account': 'site-a', 'channel_key': 'wa-2', 'statuses': [row]})
        self.assertEqual(rows[0]['hub_channel'], 'wa-2')
        update = {'id': 1, 'key': 'bulk-1', 'state': 'submitted', 'message_id': 'wamid.1', 'status': 'sent',
                  'updated_at': '2026-10-27T00:00:00Z', 'channel_key': 'wa-2', 'to': '+91'}
        rows = self.receive('receive_bulk_updates', {'account': 'site-a', 'channel_key': 'wa-2', 'updates': [update]})
        self.assertEqual(rows[0]['hub_channel'], 'wa-2')

    def test_an_invalid_channel_key_is_rejected(self):
        for payload in ({'account': 'site-a', 'channel_key': 'bad key', 'events': [{'id': 1, 'payload': text('1')}]},
                        {'account': 'site-a', 'events': [{'id': 1, 'channel_key': 5, 'payload': text('1')}]},
                        {'account': 'site-a', 'statuses': [status(1, 'bad/key')]}):
            raw, stamp, signature = signed(payload)
            validate = inbound.validate_status_callback if 'statuses' in payload else inbound.validate_callback
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate(raw, stamp, signature, SECRET, 'site-a')


class EventChannelTests(unittest.TestCase):
    def resolve(self, rows, key):
        site = FakeSite(Relay_Channel=rows)
        with patch.object(hub_channels, 'frappe', site.frappe), \
                patch('relay_core.channel_sync.queue_sync') as queued:
            return hub_channels.event_channel('site-a', 'WhatsApp', key), queued.called

    def test_two_numbers_resolve_to_two_channels(self):
        self.assertEqual(self.resolve([SHOP, SUPPORT], 'site-a'), ('Shop', False))
        self.assertEqual(self.resolve([SHOP, SUPPORT], 'wa-2'), ('Support', False))

    def test_old_payload_without_key_goes_to_the_only_channel(self):
        self.assertEqual(self.resolve([SHOP], None), ('Shop', False))
        self.assertEqual(self.resolve([SHOP, SUPPORT], None), (None, False))

    def test_unknown_key_never_falls_back_to_another_number(self):
        self.assertEqual(self.resolve([SHOP], 'wa-3'), (None, True))
        self.assertEqual(self.resolve([dict(SHOP, hub_channel=None)], 'wa-3'), ('Shop', False))
        self.assertEqual(self.resolve([SHOP, dict(SUPPORT, enabled=0)], 'wa-2'), (None, True))


class ProjectionChannelTests(unittest.TestCase):
    def project(self, payload, channel):
        event = _dict(name='event', account='site-a', hub_channel='wa-2', projection_status='Pending',
                      payload=json.dumps(payload), hub_event_id='5')
        fake = Mock()
        fake.get_doc.return_value = event
        with patch.object(projection, 'frappe', fake), patch.object(projection, 'set_status') as state, \
                patch('relay_core.hub_channels.event_channel', return_value=channel) as resolve, \
                patch('relay_core.whatsapp_templates.project', return_value=True) as templates:
            projection.project('event')
        resolve.assert_called_once_with('site-a', 'WhatsApp', 'wa-2', receipts=False)
        return state.call_args.args[1], templates.called

    def test_an_unresolved_message_event_waits_in_triage(self):
        self.assertEqual(self.project(text('2'), None), ('Uncategorized', False))

    def test_template_updates_project_without_a_number(self):
        payload = {'entry': [{'id': '111', 'changes': [{'field': 'message_template_status_update', 'value': {
            'message_template_id': 1, 'event': 'APPROVED'}}]}]}
        self.assertEqual(self.project(payload, None), ('Projected', True))


class StatusChannelTests(unittest.TestCase):
    def test_a_receipt_from_another_number_is_not_applied(self):
        action = _dict(name='action', status='Dispatching', result='{}', owner='agent@example.invalid',
                       check_permission=Mock())
        fake = Mock(PermissionError=PermissionError, DoesNotExistError=LookupError, ValidationError=TypeError,
                    QueryDeadlockError=RuntimeError, session=_dict(user='Administrator'))
        fake.db.get_value.side_effect = lambda doctype, *args, **kwargs: 'action' if doctype == 'Relay Message Action' else 1
        fake.get_doc.return_value = action
        channel = _dict(channel='WhatsApp', account='site-a', hub_channel='site-a')
        row = {'id': 2, 'request_key': 'key', 'operation': 'whatsapp.execute', 'state': 'submitted',
               'receipt': {'message_id': 'wamid.1'}, 'channel_key': 'wa-2'}
        with patch.object(channel_statuses, 'frappe', fake), \
                patch.object(channel_statuses, 'connection_value', return_value='site-a'), \
                patch.object(channel_statuses.messaging, 'action_target', return_value=(_dict(), channel, {})), \
                patch.object(channel_statuses.messaging, 'finish') as finish, patch('relay_core.realtime.incoming_changed'):
            channel_statuses.project_batch(_dict(name='event', account='site-a', hub_channel=None), [row])
        finish.assert_not_called()
        fake.db.rollback.assert_called_once_with(save_point='relay_status_row')
        fake.db.set_value.assert_called_with('Relay Hub Event', 'event', 'projection_status', 'Uncategorized')


if __name__ == '__main__':
    unittest.main()
