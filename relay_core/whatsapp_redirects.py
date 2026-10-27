"""Old WhatsApp Core links open Relay once WhatsApp Core is switched off or removed.

While WhatsApp Core is installed and enabled, its own pages answer and nothing here applies.
"""
import re

import frappe
from frappe.website.utils import build_response
from relay_core.permissions import readable_contact, require_access

OLD_APP = 'frappe_whatsapp_core'
OLD_PAGE = re.compile(r'(whatsapp|whatsapp_core)(/.*)?')
# Sub-paths name a screen of the old app. A bare /whatsapp keeps its #/... part, which the Relay page maps.
SCREENS = {'templates': 'whatsapp', 'campaigns': 'whatsapp?tab=campaigns', 'flows': 'flows', 'teams': 'teams',
           'health': 'activity', 'ai-queue': 'tickets'}


def is_old_app_off() -> bool:
    if OLD_APP not in frappe.get_installed_apps():
        return True
    return not frappe.db.get_single_value('WhatsApp Core Settings', 'enabled')


def relay_location(path: str) -> str:
    screen = (path.split('/') + [''])[1]
    target = SCREENS.get(screen)
    return '/relay#/' + target if target else '/relay'


class WhatsAppRedirectPage:
    """A page renderer that runs before www pages, so it also wins over WhatsApp Core's own /whatsapp page."""

    def __init__(self, path, http_status_code=None):
        self.path = (path or '').strip('/ ')

    def can_render(self) -> bool:
        return bool(OLD_PAGE.fullmatch(self.path)) and is_old_app_off()

    def render(self):
        return build_response(self.path, '', 302, {'Location': relay_location(self.path)})


def boot_session(bootinfo):
    bootinfo.relay_whatsapp_redirect = int(is_old_app_off())


@frappe.whitelist(methods=['GET'])
def conversation_contact(conversation):
    """The Relay contact an imported WhatsApp Core conversation became, when the user may read it."""
    require_access()
    if not isinstance(conversation, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,140}', conversation):
        frappe.throw('Invalid conversation')
    contacts = frappe.get_all('Relay Legacy Import', filters={'source_conversation': conversation},
                              pluck='relay_contact', limit_page_length=5)
    for contact in contacts:
        try:
            readable_contact(contact)
        except (frappe.PermissionError, frappe.DoesNotExistError):
            continue
        return {'contact': contact}
    return {'contact': None}
