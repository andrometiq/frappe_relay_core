"""Relay Contact Endpoint indexes: channel filters read (channel, relay_contact); a chat's own endpoints read relay_contact alone."""
import unittest
from unittest.mock import MagicMock, patch

from relay_core.relay_core.doctype.relay_contact_endpoint import relay_contact_endpoint


class EndpointIndexTests(unittest.TestCase):
    def test_the_doctype_update_installs_both_indexes_and_can_run_again(self):
        fake = MagicMock()
        with patch.object(relay_contact_endpoint, 'frappe', fake):
            relay_contact_endpoint.on_doctype_update()
            relay_contact_endpoint.on_doctype_update()
        calls = [call.args for call in fake.db.add_index.call_args_list]
        self.assertEqual(calls[:2], [('Relay Contact Endpoint', ['channel', 'relay_contact'], 'relay_channel_contacts'),
                                     ('Relay Contact Endpoint', ['relay_contact'], 'relay_endpoint_contact')])
        self.assertEqual(calls[2:], calls[:2], 'Frappe add_index skips an index that exists, so a second migrate changes nothing')
