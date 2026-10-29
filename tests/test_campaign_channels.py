"""A campaign sends from one chosen number; templates are listed and synced once per WABA."""
import unittest
from unittest.mock import Mock, patch

from frappe import _dict
from channel_fakes import FakeSite
from relay_core import bulk_campaigns, hub_channels, whatsapp_templates

SHOP = {'name': 'Shop', 'channel': 'WhatsApp', 'account': 'site-a', 'hub_channel': 'site-a', 'enabled': 1, 'waba_id': '111'}
SUPPORT = dict(SHOP, name='Support', hub_channel='wa-2')
EXPORT = dict(SHOP, name='Export', hub_channel='wa-3', waba_id='222')


class CampaignChannelTests(unittest.TestCase):
    def test_region_comes_from_the_sending_company(self):
        fake = Mock()
        fake.db.get_value.side_effect = ['Essdee UK', 'United Kingdom']
        with patch.object(bulk_campaigns, 'frappe', fake), \
                patch.object(bulk_campaigns, 'default_region', return_value='IN') as fallback:
            self.assertEqual(bulk_campaigns.channel_region('Support'), 'GB')
        self.assertEqual([call.args for call in fake.db.get_value.call_args_list],
                         [('Relay Channel', 'Support', 'company'), ('Company', 'Essdee UK', 'country')])
        fallback.assert_not_called()

    def test_region_falls_back_when_company_country_is_unavailable(self):
        for values in ([None], ['Essdee', None], ['Essdee', 'Unknown country']):
            with self.subTest(values=values), patch.object(bulk_campaigns, 'frappe') as fake, \
                    patch.object(bulk_campaigns, 'default_region', return_value='IN'):
                fake.db.get_value.side_effect = values
                self.assertEqual(bulk_campaigns.channel_region('Support'), 'IN')

    def channel(self, channels, requested=None):
        site = FakeSite(Relay_Channel=list(channels))
        with patch.object(bulk_campaigns, 'frappe', site.frappe), patch.object(hub_channels, 'frappe', site.frappe), \
                patch.object(bulk_campaigns, 'connection_value', return_value='site-a'), \
                patch('relay_core.settings.value', return_value='site-a'):
            return bulk_campaigns.campaign_channel(requested)

    def test_a_site_with_two_numbers_needs_the_campaign_number(self):
        self.assertEqual(self.channel([SHOP]), 'Shop')
        self.assertEqual(self.channel([SHOP, SUPPORT], 'Support'), 'Support')
        with self.assertRaises(ValueError):
            self.channel([SHOP, SUPPORT])
        with self.assertRaises(ValueError):
            self.channel([SHOP, dict(SUPPORT, account='site-b')], 'Support')

    def test_the_template_check_and_bulk_send_name_the_campaign_number(self):
        hub = Mock()
        hub.execute.return_value = {'data': [{'name': 'offer', 'language': 'en', 'status': 'APPROVED'}]}
        with patch.object(bulk_campaigns, 'hub_arguments', side_effect=lambda channel, args: dict(args, channel=channel)), \
                patch('relay_core.whatsapp_templates.overlay', side_effect=lambda page: page):
            bulk_campaigns.approved_template(hub, 'offer', 'en', 'Support')
        self.assertEqual(hub.execute.call_args.args[0], {'operation': 'templates.list', 'channel': 'Support'})


class TemplateWabaTests(unittest.TestCase):
    def sync(self, channels, templates, existing=()):
        site = FakeSite(Relay_Channel=list(channels), Relay_WhatsApp_Template=list(existing))
        hub = Mock()
        hub.execute.side_effect = lambda args: {'data': templates[args.get('channel', 'site-a')], 'paging': {}}
        site.frappe.cache = Mock()
        site.frappe.utils = Mock(now=lambda: 'now')
        site.frappe.log_error = Mock()
        site.frappe.publish_realtime = Mock()
        site.frappe.realtime = Mock()
        def save(doc, new=False):
            doc.save()
        with patch.object(whatsapp_templates, 'frappe', site.frappe), patch.object(hub_channels, 'frappe', site.frappe), \
                patch.object(whatsapp_templates, 'connection_value', return_value='site-a'), \
                patch.object(whatsapp_templates, 'internal_save', side_effect=save), \
                patch.object(whatsapp_templates, 'lock_account'), \
                patch('relay_core.whatsapp.checked_client', return_value=(hub, {'templates': True})):
            whatsapp_templates.sync()
        return site, hub

    def test_two_numbers_of_one_waba_sync_once(self):
        site, hub = self.sync([SHOP, SUPPORT], {'site-a': [{'id': '1', 'name': 'offer', 'language': 'en', 'status': 'APPROVED'}]})
        self.assertEqual(hub.execute.call_count, 1)
        self.assertEqual([(row.template_id, row.waba_id) for row in site.rows('Relay WhatsApp Template')], [('1', '111')])

    def test_each_waba_lists_its_own_templates_and_deletes_only_its_own(self):
        old = {'record_key': 'k-old', 'account': 'site-a', 'template_id': '9', 'waba_id': '222', 'status': 'APPROVED'}
        site, hub = self.sync([SHOP, SUPPORT, EXPORT], {
            'site-a': [{'id': '1', 'name': 'offer', 'language': 'en', 'status': 'APPROVED'}],
            'wa-3': [{'id': '2', 'name': 'export', 'language': 'en', 'status': 'APPROVED'}]}, [old])
        self.assertEqual(hub.execute.call_count, 2)
        rows = {row.template_id: (row.waba_id, row.status) for row in site.rows('Relay WhatsApp Template')}
        self.assertEqual(rows, {'9': ('222', 'DELETED'), '1': ('111', 'APPROVED'), '2': ('222', 'APPROVED')})

    def test_a_template_event_records_its_waba(self):
        doc = _dict(hub_event_id='4')
        fake = Mock()
        fake.db.get_value.return_value = 'record'
        fake.get_doc.return_value = doc
        payload = {'entry': [{'id': '222', 'changes': [{'field': 'message_template_status_update', 'value': {
            'message_template_id': 7, 'message_template_name': 'export', 'message_template_language': 'en',
            'event': 'APPROVED'}}]}]}
        with patch.object(whatsapp_templates, 'frappe', fake), patch.object(whatsapp_templates, 'internal_save'):
            whatsapp_templates.project(payload, _dict(account='site-a', hub_event_id='5'))
        self.assertEqual((doc.waba_id, doc.status), ('222', 'APPROVED'))


if __name__ == '__main__':
    unittest.main()
