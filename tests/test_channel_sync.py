"""Relay Channels follow the Hub's channel list; a legacy Hub leaves the single channel as it is."""
import unittest
from unittest.mock import Mock, patch

from channel_fakes import DuplicateEntryError, FakeSite
from relay_core import channel_sync
from relay_core.automation import projection
from relay_core.hub import HubError

LEGACY = {'channel': 'WhatsApp', 'account': 'site-a', 'hub_channel': 'site-a', 'enabled': 1, 'title': 'Shop',
          'company': 'Essdee', 'triage_owner': 'owner@example.invalid'}


def listed(*rows):
    return {'channels': [dict({'provider': 'WhatsApp', 'enabled': True}, **row) for row in rows]}


class ChannelSyncTests(unittest.TestCase):
    def run_sync(self, site, result):
        hub = Mock()
        hub.call_tool.side_effect = result if isinstance(result, Exception) else None
        hub.call_tool.return_value = result
        settings = {'relay_hub_account': 'site-a', 'relay_hub_url': 'http://127.0.0.1/mcp', 'relay_hub_token': 't'}
        with patch.object(channel_sync, 'frappe', site.frappe), \
                patch.object(channel_sync, 'connection_value', settings.get), \
                patch('relay_core.whatsapp.client', return_value=hub):
            return channel_sync.sync(), hub

    def test_listed_channels_update_the_legacy_row_and_add_the_second_number(self):
        site = FakeSite(Relay_Channel=[LEGACY])
        result, hub = self.run_sync(site, listed(
            {'key': 'site-a', 'label': 'Shop', 'display_number': '+91 90000 00001', 'waba_id': '111'},
            {'key': 'wa-2', 'label': 'Support', 'display_number': '+91 90000 00002', 'waba_id': '111'}))
        hub.call_tool.assert_called_once_with('channels.list', {})
        self.assertEqual(result, {'synced': True, 'channels': 2, 'added': 1, 'changed': 1, 'disabled': 0})
        legacy, second = site.rows('Relay Channel')
        self.assertEqual((legacy.address, legacy.waba_id, legacy.title, legacy.is_default), ('+91 90000 00001', '111', 'Shop', 1))
        self.assertEqual((second.hub_channel, second.label, second.enabled, second.title), ('wa-2', 'Support', 1, 'Support'))
        self.assertEqual((second.company, second.triage_owner), ('Essdee', 'owner@example.invalid'))
        self.assertFalse(second.get('is_default'))

    def test_a_channel_the_hub_no_longer_lists_is_disabled_and_kept(self):
        site = FakeSite(Relay_Channel=[LEGACY, dict(LEGACY, hub_channel='wa-2', title='Old')])
        result, _ = self.run_sync(site, listed({'key': 'site-a', 'label': 'Shop'}))
        self.assertEqual(result['disabled'], 1)
        self.assertEqual([row.enabled for row in site.rows('Relay Channel')], [1, 0])

    def test_rerun_without_hub_changes_writes_nothing(self):
        site = FakeSite(Relay_Channel=[LEGACY])
        rows = listed({'key': 'site-a', 'label': 'Shop', 'display_number': '1', 'waba_id': '111'})
        self.run_sync(site, rows)
        result, _ = self.run_sync(site, rows)
        self.assertEqual((result['added'], result['changed'], result['disabled']), (0, 0, 0))

    def test_legacy_hub_without_channel_list_keeps_the_single_channel(self):
        site = FakeSite(Relay_Channel=[LEGACY])
        result, _ = self.run_sync(site, HubError('Hub rejected the MCP operation'))
        self.assertFalse(result['synced'])
        self.assertEqual(site.rows('Relay Channel'), [dict(LEGACY, name=site.rows('Relay Channel')[0].name,
                                                            creation=site.rows('Relay Channel')[0].creation)])

    def test_invalid_hub_rows_change_nothing(self):
        for row in ({'key': 'bad key'}, {'key': 'k', 'provider': 'SMS'}, {'key': 'k', 'waba_id': 'x1'}):
            with self.subTest(row=row):
                site = FakeSite(Relay_Channel=[LEGACY])
                result, _ = self.run_sync(site, listed(row))
                self.assertFalse(result['synced'])
                self.assertEqual(len(site.rows('Relay Channel')), 1)

    def test_unconfigured_site_does_not_call_the_hub(self):
        with patch.object(channel_sync, 'connection_value', return_value=None), \
                patch('relay_core.whatsapp.client') as client:
            self.assertEqual(channel_sync.sync(), {'synced': False})
        client.assert_not_called()

    def test_relay_channels_event_queues_one_sync(self):
        event = Mock(payload='{"object":"relay_channels","changed":true}', projection_status='Pending')
        fake = Mock()
        fake.get_doc.return_value = event
        with patch.object(projection, 'frappe', fake), patch.object(projection, 'set_status') as status, \
                patch.object(channel_sync, 'queue_sync') as queued:
            projection.project('RELAY-EVT-1')
        queued.assert_called_once_with()
        status.assert_called_once_with('RELAY-EVT-1', 'Projected')
        fake.get_all.assert_not_called()


class RelayChannelDocTests(unittest.TestCase):
    def doc(self, **values):
        from relay_core.relay_core.doctype.relay_channel.relay_channel import RelayChannel
        doc = RelayChannel.__new__(RelayChannel)
        doc.__dict__.update({**LEGACY, 'name': 'new', 'label': '', 'is_default': 0, **values})
        return doc

    def test_a_hub_channel_key_belongs_to_one_channel_of_its_type(self):
        from relay_core.relay_core.doctype.relay_channel import relay_channel
        site = FakeSite(Relay_Channel=[LEGACY])
        with patch.object(relay_channel, 'frappe', site.frappe):
            with self.assertRaises(DuplicateEntryError):
                self.doc().validate()
            self.doc(channel='Telegram').validate()

    def test_a_new_default_clears_the_old_default_of_its_type(self):
        from relay_core.relay_core.doctype.relay_channel import relay_channel
        site = FakeSite(Relay_Channel=[dict(LEGACY, is_default=1), dict(LEGACY, channel='Telegram', is_default=1)])
        with patch.object(relay_channel, 'frappe', site.frappe):
            self.doc(is_default=1, hub_channel='wa-2').on_update()
        self.assertEqual([row.is_default for row in site.rows('Relay Channel')], [0, 1])


if __name__ == '__main__':
    unittest.main()
