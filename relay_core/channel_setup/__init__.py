"""Channel setup from Relay: every account a site uses is configured here, never in the Hub admin.

Each provider module lists its accounts and runs their setup actions through the Hub's site tools, and
`channels_api.PROVIDERS` sends each endpoint to it. Credentials stay in the Hub: no action receives one."""
import re

import frappe
from relay_core.hub import HubError
from relay_core.settings import value as connection_value

TEXT = {
    'not_found': 'This number is no longer connected to this site. Refresh the page.',
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
}
CODE = re.compile(r'\bcode ([a-z][a-z_]{1,60})\b')


class SetupError(frappe.ValidationError):
    pass


def fail(code, detail=''):
    """Stop with the customer text of a code; Meta's own words follow where they are the reason."""
    text = TEXT.get(code, TEXT['hub_unavailable'])
    if code == 'meta_rejected' and detail:
        text = detail
    frappe.throw(text, SetupError)


def hub_call(tool, arguments):
    """One Hub site tool. A refusal becomes the customer text of its Hub code."""
    if not (connection_value('relay_hub_url') and connection_value('relay_hub_token')):
        fail('hub_not_connected')
    from relay_core.whatsapp import client
    try:
        return client().call_tool(tool, arguments)
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


def site_channels(provider, fields):
    """The site's Relay Channels of one provider that the Hub still lists, oldest first."""
    listed = {row.get('key') for row in (hub_call('channels.list', {}).get('channels') or [])
              if isinstance(row, dict) and row.get('provider') == provider}
    rows = frappe.get_all('Relay Channel', filters={'channel': provider, 'account': connection_value('relay_hub_account'),
                                                    'hub_channel': ['is', 'set']},
                          fields=fields, order_by='creation asc', limit_page_length=50)
    return [row for row in rows if row.hub_channel in listed]


def make_default(name, provider, disabled='number_disabled'):
    """The channel new conversations and API sends use when nothing else picks one. Relay owns this choice."""
    row = relay_channel(name, provider)
    if not row.enabled:
        fail(disabled)
    from relay_core.channel_sync import publish, save
    save(frappe.get_doc('Relay Channel', row.name), {'is_default': 1})  # RelayChannel.on_update clears the other default.
    publish()
    return {'default': row.name}
