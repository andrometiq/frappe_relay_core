"""WhatsApp form (Meta Flow) errors: a failed read says it could not load; only a failed change has an unknown outcome."""
import unittest
from unittest.mock import Mock, patch

import frappe
from relay_core import meta_flows
from relay_core.hub import HubError


def throw(message, exc=frappe.ValidationError):
    raise exc(message)


class FlowErrorTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('frappe.throw', side_effect=throw))
        self.enterContext(patch.object(meta_flows, 'require_access'))
        self.enterContext(patch.object(meta_flows, 'choose'))
        self.enterContext(patch.object(meta_flows, 'hub_arguments', side_effect=lambda channel, arguments: arguments))
        self.hub = Mock()
        self.hub.execute.side_effect = HubError('Hub operation was rejected')
        self.enterContext(patch.object(meta_flows, 'checked_client', return_value=(self.hub, {'flows': True})))

    def test_a_failed_list_says_the_forms_could_not_load(self):
        with self.assertRaisesRegex(frappe.ValidationError, '^WhatsApp forms could not be loaded right now'):
            meta_flows.execute('list')
        self.assertEqual(self.hub.execute.call_args.args[0], {'operation': 'flows.list'})

    def test_a_failed_change_asks_to_refresh_before_retrying(self):
        with self.assertRaisesRegex(frappe.ValidationError, 'could not be confirmed. Refresh its status'):
            meta_flows.execute('publish', {'id': '333'})


if __name__ == '__main__':
    unittest.main()
