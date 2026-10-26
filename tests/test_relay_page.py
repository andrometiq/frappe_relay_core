"""The /relay page renders the shell's capabilities so the browser needs no extra request."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from relay_core.www import relay


class RelayPageTests(unittest.TestCase):
    def test_page_renders_the_capabilities_of_the_signed_in_user(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder, 'public', 'relay', '.vite')
            manifest.mkdir(parents=True)
            manifest.joinpath('manifest.json').write_text(json.dumps({'site.html': {'file': 'assets/site-1.js', 'css': ['assets/style-1.css']}}))
            page = SimpleNamespace(session=SimpleNamespace(user='agent@example.com'), local=SimpleNamespace(site='relay.example'),
                conf={}, request=None, as_json=frappe.as_json, get_app_path=lambda app, *parts: str(Path(folder, *parts)))
            granted = {'manage': False, 'enabled_channels': ['WhatsApp']}
            with patch.object(relay, 'frappe', page), patch.object(relay, 'require_access'), \
                    patch.object(relay, 'get_csrf_token', return_value='csrf'), patch.object(relay, 'capabilities', Mock(return_value=granted)):
                context = relay.get_context(frappe._dict())
        self.assertEqual(json.loads(context.relay_capabilities), granted)
        self.assertEqual(context.relay_script, '/assets/relay_core/relay/assets/site-1.js')


if __name__ == '__main__':
    unittest.main()
