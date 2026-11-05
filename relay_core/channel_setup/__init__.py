"""Channel setup from Relay: every account a site uses is configured here, never in the Hub admin.

Each provider module lists its accounts and runs their setup actions through the Hub's site tools, and
`channels_api.PROVIDERS` sends each endpoint to it. A bot token or mail password goes to the Hub once, in the
connect or settings call, and stays there: Core never stores, logs or returns it."""
import re
from urllib.parse import urlsplit

import frappe
from relay_core.hub import CREDENTIAL_TOOLS, HubError, OlderHubError, protected_transport
from relay_core.settings import value as connection_value

TEXT = {
    'not_found': 'This channel is no longer connected to this site. Refresh the page.',
    'no_number': 'This site has no WhatsApp number yet. Connect one first.',
    'channel_required': 'Choose the number to change.',
    'number_disabled': 'Turn the number on first.',
    'reconnect_required': 'Meta no longer accepts Relay’s access to this number. Select Connect again.',
    'meta_unavailable': 'Meta is not answering. Try again in a few minutes.',
    'outcome_unknown': 'Relay does not know whether Meta took the change. Try again.',
    'pending_sends': 'Messages are still being sent from this number. Wait until they finish, then try again.',
    'confirm_required': 'Confirm the change first.',
    'not_supported': 'This number is on the WhatsApp Business app, which keeps its own PIN.',
    'invalid_request': 'Choose a setting to change.',
    'hub_not_connected': 'Connect this site to Relay Hub first.',
    'hub_unavailable': 'Relay Hub could not finish this. Try again in a few minutes.',
    'insecure_hub': 'Relay sends tokens and passwords only over HTTPS. Ask your Relay provider for the HTTPS Hub address.',
    'no_bot': 'This site has no Telegram bot yet. Connect one first.',
    'invalid_token': 'Telegram did not accept this bot token. Copy the token from @BotFather again.',
    'bot_changed': 'This token belongs to another bot. Connect that bot as a new bot instead.',
    'telegram_unavailable': 'Telegram is not answering. Try again in a few minutes.',
    'channel_disabled': 'Turn the channel on first.',
    'in_use': 'This bot or mailbox is already connected to Relay. Remove it there first.',
    'not_available': 'Your Relay Hub does not let sites connect channels yet. Ask your Relay provider.',
    'rate_limited': 'Too many tries. Wait an hour, then try again.',
    'no_mailbox': 'This site has no mailbox yet. Connect one first.',
    'host_refused': 'Relay can only reach mail servers on the public internet. Check the host names.',
    'port_refused': 'Use SMTP port 25, 465, 587 or 2525 and IMAP port 143 or 993.',
    'login_failed': 'Relay could not sign in to the mailbox. Check the host, port, username and password.',
    'invalid_settings': 'Check the mailbox settings.',
    'host_unknown': 'Relay could not find the mail server. Check the host name.',
}
# The Hub's own words are the reason for these codes, and they never carry a credential.
HUB_WORDS = ('meta_rejected', 'login_failed', 'invalid_settings', 'host_unknown')
CODE = re.compile(r'\bcode ([a-z][a-z_]{1,60})\b')


class SetupError(frappe.ValidationError):
    pass


def fail(code, detail=''):
    """Stop with the customer text of a code; Meta's own words follow where they are the reason."""
    text = TEXT.get(code, TEXT['hub_unavailable'])
    if code in HUB_WORDS and detail:
        text = detail
    frappe.throw(text, SetupError)


def hub_call(tool, arguments, older=None):
    """One Hub site tool. A refusal becomes the customer text of its Hub code. A Hub version without the tool
    returns `older` when it is given, so a list still shows the site's channels, else it is not_available.

    A token or password in arguments goes only to an HTTPS or loopback Hub; it is never stored, logged or shown."""
    if not (connection_value('relay_hub_url') and connection_value('relay_hub_token')):
        fail('hub_not_connected')
    if tool in CREDENTIAL_TOOLS and not protected_transport(urlsplit(connection_value('relay_hub_url'))):
        fail('insecure_hub')
    from relay_core.whatsapp import client
    try:
        return client().call_tool(tool, arguments)
    except OlderHubError:
        if older is not None:
            return older
        fail('not_available')
    except HubError as error:
        detail = error.detail or ''
        found = CODE.search(detail)
        code = found.group(1) if found else 'hub_unavailable'
        fail(code, detail.split(' · ')[0].removeprefix(code + ': '))


def relay_channel(name, provider):
    """The site's Relay Channel of one provider by its name, with its Hub key."""
    row = frappe.db.get_value('Relay Channel', {'name': name, 'channel': provider, 'account': connection_value('relay_hub_account')},
                              ['name', 'hub_channel', 'enabled', 'is_default', 'label', 'title', 'address'], as_dict=True) \
        if isinstance(name, str) and name else None
    if not row or not row.hub_channel:
        fail('not_found')
    return row


def provider_of(name):
    """The provider of one Relay Channel of this site, or not_found."""
    provider = frappe.db.get_value('Relay Channel', {'name': name, 'account': connection_value('relay_hub_account')}, 'channel') \
        if isinstance(name, str) and name else None
    if not provider:
        fail('not_found')
    return provider


def site_rows(provider, fields):
    """The site's Relay Channels of one provider with a Hub key, oldest first."""
    return frappe.get_all('Relay Channel', filters={'channel': provider, 'account': connection_value('relay_hub_account'),
                                                    'hub_channel': ['is', 'set']},
                          fields=fields, order_by='creation asc', limit_page_length=50)


def site_accounts(provider, fields, health_tool, shown, health_of):
    """The site's channels of one provider that the Hub still lists, each with its Hub health, oldest first.

    One channels.health call reads every channel. An older Hub without it is asked channels.list and then each health."""
    batch = hub_call('channels.health', {'provider': provider}, older={})
    if provider not in batch:
        listed = {row.get('key') for row in (hub_call('channels.list', {}).get('channels') or [])
                  if isinstance(row, dict) and row.get('provider') == provider}
        return [dict(shown(row), health=health_of(hub_call(health_tool, {'channel': row.hub_channel}, older={})))
                for row in site_rows(provider, fields) if row.hub_channel in listed]
    health = {item.get('channel'): item for item in batch[provider] or [] if isinstance(item, dict)}
    return [dict(shown(row), health=health_of(health[row.hub_channel])) for row in site_rows(provider, fields) if row.hub_channel in health]


def make_default(name, provider, disabled='number_disabled'):
    """The channel new conversations and API sends use when nothing else picks one. Relay owns this choice."""
    row = relay_channel(name, provider)
    if not row.enabled:
        fail(disabled)
    from relay_core.channel_sync import publish, save
    save(frappe.get_doc('Relay Channel', row.name), {'is_default': 1})  # RelayChannel.on_update clears the other default.
    publish()
    return {'default': row.name}


def connected(provider, result):
    """The Relay Channel of a channel the Hub just connected, after Core read the channel list again."""
    from relay_core.channel_sync import sync
    sync()
    key = result.get('channel') if isinstance(result, dict) else None
    name = frappe.db.get_value('Relay Channel', {'channel': provider, 'hub_channel': key, 'account': connection_value('relay_hub_account')}, 'name') \
        if isinstance(key, str) and key else None
    if not name:
        fail('hub_unavailable')
    return name


def secret_value(values, field):
    """A token or password from the form as typed, or '' when the person left it blank. Never stored or echoed."""
    value = values.get(field) if isinstance(values, dict) else None
    if value is not None and not isinstance(value, str):
        frappe.throw('Enter the value as text')
    return value if value and value.strip() else ''
