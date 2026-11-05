"""Telegram bots: connect, health, check, name, default bot and removal, all through the Hub.

The bot token is a function argument only: it goes straight to the Hub and is never kept in Core."""
import frappe
from relay_core.channel_setup import connected, fail, hub_call, make_default, relay_channel, secret_value, site_accounts
from relay_core.channel_sync import publish

PROVIDER = 'Telegram'
FIELDS = ['name', 'hub_channel', 'label', 'title', 'address', 'enabled', 'is_default']
HEALTH = ('username', 'bot_id', 'webhook_status', 'checked_at', 'check_error', 'token_saved', 'webhook_missing', 'pending_updates')
SETTINGS = ('enabled', 'label', 'bot_token')


def health_of(result):
    """The Hub's health fields; nothing else from the answer reaches the browser."""
    return {key: result.get(key) for key in HEALTH} if isinstance(result, dict) else {}


def shown(row):
    return {'name': row.name, 'label': row.label or row.title or row.name, 'address': row.address or '',
            'enabled': bool(row.enabled), 'is_default': bool(row.is_default)}


def accounts():
    """The site's bots that the Hub still lists, with their Relay Channel and Hub health, oldest first."""
    return site_accounts(PROVIDER, FIELDS, 'telegram.bot.health', shown, health_of)


def account(name):
    row = relay_channel(name, PROVIDER)
    return dict(shown(row), health=health_of(hub_call('telegram.bot.health', {'channel': row.hub_channel})))


def connect(values):
    """Connect a bot with its @BotFather token. The Hub checks it, keeps it and registers the webhook."""
    bot_token = secret_value(values, 'bot_token').strip()
    if not bot_token:
        frappe.throw('Paste the bot token from @BotFather')
    label = values.get('label') if isinstance(values.get('label'), str) else ''
    result = hub_call('telegram.bot.connect', {'bot_token': bot_token, 'label': label.strip()[:140]})
    return {'name': connected(PROVIDER, result), 'health': health_of(result)}


def check(name, repair=True):
    """Check the bot with Telegram; with repair the Hub registers its webhook again."""
    row = relay_channel(name, PROVIDER)
    result = hub_call('telegram.bot.check', {'channel': row.hub_channel, 'repair': bool(repair)})
    publish()
    return dict(shown(row), health=health_of(result))


def save_settings(name, settings):
    """Rename the bot, turn it on or off, or save a new token of the same bot."""
    row = relay_channel(name, PROVIDER)
    if not isinstance(settings, dict) or not settings or set(settings) - set(SETTINGS):
        frappe.throw('Choose enabled, label or bot_token')
    changes = {}
    if 'enabled' in settings:
        changes['enabled'] = str(settings['enabled']) in ('1', 'true', 'True')
    if isinstance(settings.get('label'), str) and settings['label'].strip():
        changes['label'] = settings['label'].strip()[:140]
    if bot_token := secret_value(settings, 'bot_token').strip():
        changes['bot_token'] = bot_token
    if not changes:
        frappe.throw('Choose enabled, label or bot_token')
    hub_call('telegram.bot.settings', {'channel': row.hub_channel, **changes})
    from relay_core.channel_sync import sync
    sync()
    return account(name)


def set_default(name):
    return make_default(name, PROVIDER, 'channel_disabled')


def remove(name, confirm=False):
    """Take the bot off this site. The Relay Channel stays, turned off, so its chats keep their history."""
    row = relay_channel(name, PROVIDER)
    if not confirm:
        fail('confirm_required')
    result = hub_call('telegram.bot.remove', {'channel': row.hub_channel, 'confirm': True})
    from relay_core.channel_sync import sync
    sync()
    return {'removed': result.get('removed') is True, 'webhook_deleted': result.get('webhook_deleted') is True}
