"""Hub account capabilities are cached briefly; the site binding is checked on every use."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from relay_core import whatsapp


class Cache:
    def __init__(self):
        self.values = {}

    def get_value(self, key): return self.values.get(key)
    def set_value(self, key, value, expires_in_sec=None): self.values[key] = (value, expires_in_sec)[0]
    def delete_keys(self, prefix): self.values = {k: v for k, v in self.values.items() if not k.startswith(prefix)}


class HubCapabilitiesCacheTests(unittest.TestCase):
    def setUp(self):
        self.hub = Mock()
        self.hub.execute.return_value = {'site': 'https://relay.example', 'templates': True}
        self.cache = Cache()
        self.url = 'https://relay.example/'
        self.frappe = SimpleNamespace(cache=self.cache, throw=Mock(side_effect=PermissionError), get_all=Mock(return_value=[]),
            utils=SimpleNamespace(get_url=lambda: self.url))
        self.settings = {'relay_hub_url': 'https://hub.example/mcp', 'relay_hub_account': 'acme'}
        for item in (patch.object(whatsapp, 'frappe', self.frappe), patch.object(whatsapp, 'client', return_value=self.hub),
                     patch.object(whatsapp, 'connection_value', side_effect=self.settings.get)):
            item.start()
            self.addCleanup(item.stop)

    def test_repeat_reads_use_one_hub_call(self):
        self.assertEqual(whatsapp.checked_client()[1]['templates'], True)
        self.assertEqual(whatsapp.checked_client()[1]['templates'], True)
        self.hub.execute.assert_called_once_with({'operation': 'capabilities'})

    def test_another_account_or_a_settings_save_reads_the_hub_again(self):
        whatsapp.checked_client()
        self.settings['relay_hub_account'] = 'other'
        whatsapp.checked_client()
        whatsapp.clear_hub_capabilities()
        whatsapp.checked_client()
        self.assertEqual(self.hub.execute.call_count, 3)

    def test_cached_capabilities_still_reject_another_site(self):
        whatsapp.checked_client()
        self.url = 'https://other.example'
        with self.assertRaises(PermissionError):
            whatsapp.checked_client()
        self.hub.execute.assert_called_once()

    def test_a_background_url_without_the_request_scheme_and_port_is_the_same_site(self):
        self.url = 'http://relay.example'
        self.hub.execute.return_value = {'site': 'https://relay.example:8443', 'templates': True}
        self.assertTrue(whatsapp.checked_client()[1]['templates'])

    def test_a_site_with_several_numbers_names_its_default_number(self):
        self.frappe.get_all.return_value = ['Acme Traders-002']
        with patch('relay_core.hub_channels.hub_arguments', side_effect=lambda name, arguments: dict(arguments, channel='wa-' + name)) as arguments:
            whatsapp.checked_client()
        arguments.assert_called_once_with('Acme Traders-002', {'operation': 'capabilities'})
        self.hub.execute.assert_called_once_with({'operation': 'capabilities', 'channel': 'wa-Acme Traders-002'})
        self.assertEqual(self.frappe.get_all.call_args.kwargs['order_by'], 'is_default desc, creation asc')

    def test_a_failed_hub_read_is_not_cached(self):
        self.hub.execute.side_effect = [RuntimeError('down'), {'site': 'https://relay.example'}]
        with self.assertRaises(RuntimeError):
            whatsapp.checked_client()
        self.assertEqual(whatsapp.checked_client()[1]['site'], 'https://relay.example')


if __name__ == '__main__':
    unittest.main()
