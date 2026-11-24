"""Canonical endpoint patch: every stored endpoint, legacy aliases included, gets the value identity.bindings reads."""
import unittest
from unittest.mock import MagicMock, patch

from frappe import _dict

from relay_core.patches.v1_0 import fill_canonical_endpoints as module


class CanonicalEndpointPatchTests(unittest.TestCase):
    def run_patch(self, endpoints):
        fake = MagicMock()
        fake.get_all.side_effect = lambda doctype, **kwargs: (
            [('CH-WA', 'WhatsApp'), ('CH-TG', 'Telegram')] if doctype == 'Relay Channel' else endpoints)
        with patch.object(module, 'frappe', fake):
            module.execute()
        return [call.args[1:4] for call in fake.db.set_value.call_args_list]

    def test_legacy_aliases_get_their_canonical_value_and_filled_rows_are_left_alone(self):
        changes = self.run_patch([
            _dict(name='E-LEGACY', channel='CH-WA', endpoint='+91 98765-43210', canonical_endpoint=None),
            _dict(name='E-NEW', channel='CH-WA', endpoint='919123456789', canonical_endpoint=None),
            _dict(name='E-DONE', channel='CH-TG', endpoint='123456', canonical_endpoint='123456'),
            _dict(name='E-BAD', channel='CH-TG', endpoint='@username', canonical_endpoint=None),
        ])
        self.assertEqual(changes, [('E-LEGACY', 'canonical_endpoint', '919876543210'),
                                   ('E-NEW', 'canonical_endpoint', '919123456789')])


if __name__ == '__main__':
    unittest.main()
