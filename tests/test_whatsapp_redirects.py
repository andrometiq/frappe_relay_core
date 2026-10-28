import unittest
from unittest.mock import Mock, patch

from frappe import _dict
from relay_core import whatsapp_redirects as redirects


class WhatsAppRedirects(unittest.TestCase):
    def fake(self, apps=('frappe', 'frappe_whatsapp_core', 'relay_core'), enabled=1):
        f = Mock(PermissionError=PermissionError, DoesNotExistError=LookupError)
        f.get_installed_apps.return_value = list(apps)
        f.db.get_single_value.return_value = enabled
        def throw(text, exception=ValueError): raise exception(text)
        f.throw = throw
        return f

    def can_render(self, path, **state):
        with patch.object(redirects, 'frappe', self.fake(**state)):
            return redirects.WhatsAppRedirectPage(path).can_render()

    def test_old_app_keeps_its_pages_while_it_is_enabled(self):
        self.assertFalse(self.can_render('whatsapp'))
        self.assertFalse(self.can_render('/whatsapp_core/'))

    def test_old_pages_redirect_when_the_old_app_is_off_or_removed(self):
        for state in ({'enabled': 0}, {'apps': ('frappe', 'relay_core')}):
            for path in ('whatsapp', '/whatsapp/', 'whatsapp_core', 'whatsapp/templates'):
                self.assertTrue(self.can_render(path, **state), (path, state))

    def test_other_pages_are_never_claimed(self):
        for path in ('relay', 'whatsapp-help', 'desk/whatsapp-flow-builder', 'app/whatsapp', 'whatsappx'):
            self.assertFalse(self.can_render(path, enabled=0), path)

    def test_old_screens_map_to_relay_screens(self):
        self.assertEqual(redirects.relay_location('whatsapp'), '/relay')
        self.assertEqual(redirects.relay_location('whatsapp/templates'), '/relay#/whatsapp')
        self.assertEqual(redirects.relay_location('whatsapp_core/campaigns'), '/relay#/whatsapp?tab=campaigns')
        self.assertEqual(redirects.relay_location('whatsapp/flows/abc'), '/relay#/flows')
        self.assertEqual(redirects.relay_location('whatsapp/unknown'), '/relay')

    def test_render_is_a_temporary_redirect(self):
        with patch.object(redirects, 'build_response', side_effect=lambda path, data, status, headers: (status, headers)):
            status, headers = redirects.WhatsAppRedirectPage('whatsapp/health').render()
        self.assertEqual((status, headers), (302, {'Location': '/relay#/activity'}))

    def test_boot_flag_follows_the_old_app_state(self):
        for enabled, expected in ((1, 0), (0, 1)):
            boot = _dict()
            with patch.object(redirects, 'frappe', self.fake(enabled=enabled)):
                redirects.boot_session(boot)
            self.assertEqual(boot.relay_whatsapp_redirect, expected)

    def test_imported_chat_link_returns_only_a_readable_contact(self):
        f = self.fake()
        f.get_all.return_value = ['CON-hidden', 'CON-shared']
        def readable(name):
            if name == 'CON-hidden': raise PermissionError(name)
        with patch.object(redirects, 'frappe', f), patch.object(redirects, 'require_access'), \
             patch.object(redirects, 'readable_contact', side_effect=readable):
            self.assertEqual(redirects.conversation_contact('vs31e5rmoj'), {'contact': 'CON-shared'})
            f.get_all.return_value = ['CON-hidden']
            self.assertEqual(redirects.conversation_contact('vs31e5rmoj'), {'contact': None})
            with self.assertRaises(ValueError):
                redirects.conversation_contact("x' or 1=1")
