"""Mailboxes: connect, health, sign-in check, settings, default mailbox and removal, all through the Hub.

The SMTP and IMAP passwords are function arguments only: they go straight to the Hub and are never kept in Core.
The mailbox address list, company and triage owner stay on the Relay Channel, because only Core uses them."""
import frappe
from relay_core.channel_setup import connected, fail, hub_call, make_default, relay_channel, secret_value, site_channels
from relay_core.channel_sync import publish

PROVIDER = 'Email'
FIELDS = ['name', 'hub_channel', 'label', 'title', 'address', 'enabled', 'is_default']
SERVER = ('host', 'username', 'imap_host', 'imap_username', 'imap_folder', 'trusted_authserv_id', 'trusted_dsn_domain')
PORTS = ('port', 'imap_port')
SECRETS = ('password', 'imap_password')
HEALTH = ('address', 'connection_status', 'smtp_status', 'imap_status', 'checked_at', 'check_error', 'password_saved',
          'imap_password_saved', 'rejected')
SYNC = ('last_sync', 'error', 'failures', 'backoff')


def health_of(result):
    """The Hub's health fields; nothing else from the answer reaches the browser."""
    if not isinstance(result, dict):
        return {}
    health = {key: result.get(key) for key in HEALTH}
    server = result.get('server') if isinstance(result.get('server'), dict) else {}
    health['server'] = {key: server[key] for key in (*SERVER, *PORTS) if key in server}
    health['sync'] = [{key: row.get(key) for key in SYNC} for row in result.get('sync') or [] if isinstance(row, dict)][:10]
    return health


def shown(row):
    return {'name': row.name, 'label': row.label or row.title or row.name, 'address': row.address or '',
            'enabled': bool(row.enabled), 'is_default': bool(row.is_default)}


def accounts():
    """The site's mailboxes that the Hub still lists, with their Relay Channel and Hub health, oldest first."""
    return [dict(shown(row), health=health_of(hub_call('email.mailbox.health', {'channel': row.hub_channel})))
            for row in site_channels(PROVIDER, FIELDS)]


def account(name):
    row = relay_channel(name, PROVIDER)
    return dict(shown(row), health=health_of(hub_call('email.mailbox.health', {'channel': row.hub_channel})))


def server_values(values):
    """The server fields and passwords the person filled in. Blank fields are left out, so the Hub keeps its value."""
    result = {}
    for key in SERVER:
        value = values.get(key)
        if value in (None, ''):
            continue
        if not isinstance(value, str) or len(value.strip()) > 200:
            frappe.throw(f'Enter {key.replace("_", " ")} as text of at most 200 characters')
        result[key] = value.strip()
    for key in PORTS:
        if values.get(key) in (None, ''):
            continue
        try:
            result[key] = int(values[key])
        except (TypeError, ValueError):
            frappe.throw('Enter the port as a number')
        if not 0 < result[key] < 65536:
            frappe.throw('Enter the port as a number')
    for key in SECRETS:
        if value := secret_value(values, key):
            result[key] = value
    return result


def connect(values):
    """Connect a mailbox. The Hub signs in to SMTP and IMAP first and keeps nothing when that fails."""
    sender = values.get('from')
    if not isinstance(sender, str) or '@' not in sender or len(sender) > 200:
        frappe.throw('Enter the mailbox address, such as sales@example.com')
    arguments = {'from': sender.strip(), **server_values(values)}
    if isinstance(values.get('label'), str) and values['label'].strip():
        arguments['label'] = values['label'].strip()[:140]
    result = hub_call('email.mailbox.connect', arguments)
    return {'name': connected(PROVIDER, result), 'health': health_of(result)}


def check(name, repair=False):
    """Sign in to SMTP and IMAP with the saved settings. No mail is sent or read."""
    row = relay_channel(name, PROVIDER)
    result = hub_call('email.mailbox.check', {'channel': row.hub_channel})
    publish()
    return dict(shown(row), health=health_of(result))


def save_settings(name, settings):
    """Rename the mailbox, turn it on or off, or change how the Hub signs in."""
    row = relay_channel(name, PROVIDER)
    if not isinstance(settings, dict) or not settings or set(settings) - {'enabled', 'label', *SERVER, *PORTS, *SECRETS}:
        frappe.throw('Choose a mailbox setting to change')
    changes = server_values(settings)
    if 'enabled' in settings:
        changes['enabled'] = str(settings['enabled']) in ('1', 'true', 'True')
    if isinstance(settings.get('label'), str) and settings['label'].strip():
        changes['label'] = settings['label'].strip()[:140]
    if not changes:
        frappe.throw('Choose a mailbox setting to change')
    hub_call('email.mailbox.settings', {'channel': row.hub_channel, **changes})
    from relay_core.channel_sync import sync
    sync()
    return account(name)


def set_default(name):
    return make_default(name, PROVIDER, 'channel_disabled')


def remove(name, confirm=False):
    """Take the mailbox off this site. The Relay Channel stays, turned off, so its chats keep their history."""
    row = relay_channel(name, PROVIDER)
    if not confirm:
        fail('confirm_required')
    result = hub_call('email.mailbox.remove', {'channel': row.hub_channel, 'confirm': True})
    from relay_core.channel_sync import sync
    sync()
    return {'removed': result.get('removed') is True}
