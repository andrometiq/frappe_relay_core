"""Where a site is in its setup: one read for the Get started page and the capability flag."""
import frappe
from relay_core.settings import value as connection_value

# Common business records chats can link to; checked by default when the site has the DocType.
SUGGESTED = ('Customer', 'Supplier', 'Lead')


def is_connected():
    return bool(connection_value('relay_hub_url') and connection_value('relay_hub_token')
                and connection_value('relay_hub_account'))


def is_completed():
    return bool(frappe.db.get_single_value('Relay Settings', 'onboarding_completed'))


def whatsapp_channels():
    account = connection_value('relay_hub_account')
    if not account:
        return []
    return frappe.get_all('Relay Channel', filters={'channel': 'WhatsApp', 'account': account},
                          fields=['name', 'label', 'title', 'address', 'waba_id', 'enabled', 'connection_type'],
                          order_by='creation asc', limit_page_length=50)


def other_channels():
    """Enabled Telegram and Email channels the Hub admin linked to this site; they need no WhatsApp number."""
    account = connection_value('relay_hub_account')
    if not account:
        return []
    return frappe.get_all('Relay Channel', filters={'channel': ['in', ('Telegram', 'Email')], 'account': account, 'enabled': 1},
                          fields=['name', 'channel', 'label', 'title', 'address'], order_by='creation asc', limit_page_length=50)


def current_step(channels=None, draft=None, others=None):
    """A site with a working channel of any kind is ready; WhatsApp needs business details and a number first."""
    if is_completed():
        return 'done'
    if not is_connected():
        return 'hub'
    channels = whatsapp_channels() if channels is None else channels
    if any(row.enabled for row in channels) or (other_channels() if others is None else others):
        return 'ready'
    from relay_core.onboarding.details import saved
    return 'number' if draft or saved() else 'business'


def capability():
    """`api.capabilities.onboarding`: whether the site still needs the Get started page."""
    step = current_step()
    return {'required': step != 'done', 'step': step}


def record_types():
    """Configured Relay Contact Types and the common DocTypes this site has, for the last step."""
    configured = {row.business_doctype: row for row in frappe.get_all(
        'Relay Contact Type', fields=['business_doctype', 'label', 'enabled'], limit_page_length=200)}
    names = list(configured) + [name for name in SUGGESTED if name not in configured and frappe.db.exists('DocType', name)]
    return [{'doctype': name, 'label': (configured[name].label if name in configured else '') or name,
             'enabled': bool(configured[name].enabled) if name in configured else name in SUGGESTED,
             'configured': name in configured} for name in sorted(names)]


def state():
    from relay_core.onboarding import details, enrolment, signup
    draft = details.saved()
    channels, others = whatsapp_channels(), other_channels()
    from relay_core.permissions import can_configure
    configure = can_configure()
    return {'step': current_step(channels, draft, others), 'completed': is_completed(), 'can_configure': configure,
            'hub': {'connected': is_connected(), 'account': connection_value('relay_hub_account') or '',
                    'hub_origin': signup.hub_origin() if is_connected() else '',
                    'enrolment_available': enrolment.available(),
                    'source': frappe.db.get_single_value('Relay Settings', 'enrolment_source') or ''},
            'draft': draft or (details.defaults() if configure else {}), 'draft_saved': bool(draft),
            'options': details.options() if configure else {}, 'signup': signup.latest(),
            'channels': [{'name': row.name, 'label': row.label or row.title, 'address': row.address or '',
                          'waba_id': row.waba_id or '', 'enabled': bool(row.enabled),
                          'connection_type': row.connection_type or 'Cloud API'} for row in channels],
            'other_channels': [{'name': row.name, 'channel': row.channel, 'label': row.label or row.title,
                                'address': row.address or ''} for row in others],
            'record_types': record_types() if configure else []}
