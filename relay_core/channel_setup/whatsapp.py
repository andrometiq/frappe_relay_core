"""WhatsApp numbers: health, check, switches, default number, PIN, profile and removal, all through the Hub."""
import base64

import frappe
from relay_core.channel_setup import fail, hub_call, make_default, relay_channel, site_accounts
from relay_core.channel_sync import publish

PROVIDER = 'WhatsApp'
SWITCHES = ('enabled', 'templates', 'sync_metadata')
PROFILE_FIELDS = ('about', 'address', 'description', 'email', 'websites', 'vertical')
PHOTO_TYPES = ('image/jpeg', 'image/png')
PHOTO_BYTES = 5 * 1024 * 1024
HEALTH = ('connection_status', 'partner_status', 'verified_at', 'checked_at', 'check_error', 'webhook_subscribed',
          'pin_kept', 'settings', 'delivery')


def health_of(result):
    """The Hub's health fields; nothing else from the answer reaches the browser."""
    return {key: result.get(key) for key in HEALTH} if isinstance(result, dict) else {}


def accounts():
    """The site's numbers that the Hub still lists, with their Relay Channel and Hub health, oldest first."""
    return site_accounts(PROVIDER, ['name', 'hub_channel', 'label', 'title', 'address', 'enabled', 'is_default', 'connection_type'],
                         'whatsapp.number.health', shown, health_of)


def shown(row):
    return {'name': row.name, 'label': row.label or row.title or row.name, 'address': row.address or '',
            'enabled': bool(row.enabled), 'is_default': bool(row.is_default),
            'coexistence': row.get('connection_type') == 'Coexistence'}


def account(name):
    row = relay_channel(name, PROVIDER)
    return dict(shown(row), health=health_of(hub_call('whatsapp.number.health', {'channel': row.hub_channel})))


def check(name, repair=True):
    """Check the number with Meta; with repair the Hub subscribes its webhooks again."""
    row = relay_channel(name, PROVIDER)
    result = hub_call('whatsapp.number.check', {'channel': row.hub_channel, 'repair': bool(repair)})
    publish()
    profile = result.get('profile') if isinstance(result.get('profile'), dict) else {}
    return dict(shown(row), health=health_of(result), reconnect_required=result.get('reconnect_required') is True,
                profile={key: str(value)[:200] for key, value in profile.items()})


def save_settings(name, settings):
    """Turn a number on or off and switch templates and the hourly Meta sync."""
    row = relay_channel(name, PROVIDER)
    if not isinstance(settings, dict) or not settings or set(settings) - set(SWITCHES):
        frappe.throw('Choose enabled, templates or sync_metadata')
    changes = {key: str(value) in ('1', 'true', 'True') for key, value in settings.items()}
    hub_call('whatsapp.number.settings', {'channel': row.hub_channel, **changes})
    from relay_core.channel_sync import sync
    from relay_core.whatsapp import clear_hub_capabilities
    sync()
    clear_hub_capabilities()
    return account(name)


def set_default(name):
    return make_default(name, PROVIDER)


def reset_pin(name):
    """A new two-step PIN that only the Hub knows."""
    row = relay_channel(name, PROVIDER)
    return {'health': health_of(hub_call('whatsapp.number.pin_reset', {'channel': row.hub_channel}))}


def remove(name, confirm=False):
    """Take the number off this site. The Relay Channel stays, turned off, so its chats keep their history."""
    row = relay_channel(name, PROVIDER)
    if not confirm:
        fail('confirm_required')
    result = hub_call('whatsapp.number.remove', {'channel': row.hub_channel, 'confirm': True})
    from relay_core.channel_sync import sync
    sync()
    return {'removed': result.get('removed') is True, 'deregistered': result.get('deregistered') is True,
            'unsubscribed': result.get('unsubscribed') is True}


def profile(name):
    row = relay_channel(name, PROVIDER)
    result = hub_call('whatsapp.execute', {'operation': 'profile.get', 'channel': row.hub_channel})
    values = result.get('profile') if isinstance(result.get('profile'), dict) else {}
    return {key: values.get(key) for key in (*PROFILE_FIELDS, 'profile_picture_url')}


def save_profile(name, values, photo_base64='', photo_type=''):
    """Change the public WhatsApp profile; the Hub checks Meta's limits."""
    row = relay_channel(name, PROVIDER)
    if not isinstance(values, dict) or set(values) - set(PROFILE_FIELDS):
        frappe.throw('Unsupported profile field')
    if 'websites' in values and (not isinstance(values['websites'], list) or not all(isinstance(site, str) for site in values['websites'])):
        frappe.throw('Websites must be a list of addresses')
    arguments = {'operation': 'profile.update', 'channel': row.hub_channel, 'profile': values}
    if photo_base64:
        checked_photo(photo_base64, photo_type)
        arguments.update(content_base64=photo_base64, mime_type=photo_type)
    hub_call('whatsapp.execute', arguments)
    return profile(name)


def checked_photo(content, mime):
    if mime not in PHOTO_TYPES:
        frappe.throw('Choose a JPEG or PNG photo')
    try:
        size = len(base64.b64decode(content, validate=True))
    except (ValueError, TypeError):
        frappe.throw('The photo could not be read')
    if not 0 < size <= PHOTO_BYTES:
        frappe.throw('The photo must be at most 5 MB')
