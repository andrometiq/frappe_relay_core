"""Keep this site's Relay Channels in step with the channels the Hub assigns to it."""
import re
import frappe
from relay_core.hub import HubError
from relay_core.permissions import require_access
from relay_core.settings import value as connection_value

PROVIDERS = ('WhatsApp', 'Telegram', 'Email')
KEY = re.compile(r'[A-Za-z0-9_.:-]{1,140}')
FIELDS = ['name', 'channel', 'account', 'hub_channel', 'label', 'address', 'waba_id', 'enabled', 'is_default',
          'company', 'triage_owner', 'creation']


def listed_channels(result):
    """Validated `channels.list` rows as {key, provider, label, address, waba_id, enabled}."""
    rows = result.get('channels')
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError('Hub returned an invalid channel list')
    channels = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('key'), str) or not KEY.fullmatch(row['key']):
            raise ValueError('Hub returned an invalid channel key')
        if row.get('provider') not in PROVIDERS:
            raise ValueError('Hub returned an unsupported channel type')
        waba = str(row.get('waba_id') or '')
        if waba and not waba.isdigit():
            raise ValueError('Hub returned an invalid WhatsApp Business Account')
        channels.append({'key': row['key'], 'provider': row['provider'], 'label': text(row.get('label')),
                         'address': text(row.get('display_number') or row.get('address')),
                         'waba_id': waba[:40], 'enabled': row.get('enabled') is not False})
    return channels


def text(value, limit=140):
    if not isinstance(value, str):
        return ''
    return ' '.join(''.join(c if c.isprintable() else ' ' for c in value).split())[:limit]


def sync():
    """Upsert listed channels by Hub channel key and switch off the ones the Hub no longer lists.

    Rows are never deleted, as messages link to them. A Hub without `channels.list` changes nothing,
    so a legacy single-channel site keeps its channel."""
    account = connection_value('relay_hub_account')
    if not account or not connection_value('relay_hub_url') or not connection_value('relay_hub_token'):
        return {'synced': False}
    from relay_core.whatsapp import client
    try:
        listed = listed_channels(client().call_tool('channels.list', {}))
    except (HubError, ValueError) as error:
        return {'synced': False, 'error': getattr(error, 'detail', '') or str(error)}
    with frappe.cache.lock('relay-channel-sync', timeout=60, blocking_timeout=10):
        result = store(account, listed)
    frappe.db.commit()
    return dict(result, synced=True)


def store(account, listed):
    """The Hub owns which channels exist and whether they are enabled."""
    rows = frappe.get_all('Relay Channel', fields=FIELDS, filters={'hub_channel': ['is', 'set']},
                          order_by='creation asc')
    known = {(row.channel, row.hub_channel): row for row in rows}
    added = changed = disabled = 0
    for item in listed:
        row = known.get((item['provider'], item['key']))
        if not row:
            insert(account, item)
            added += 1
        elif update(row, account, item):
            changed += 1
    keys = {(item['provider'], item['key']) for item in listed}
    for row in rows:
        if row.account == account and row.enabled and (row.channel, row.hub_channel) not in keys:
            save(frappe.get_doc('Relay Channel', row.name), {'enabled': 0})
            disabled += 1
    keep_one_default(account)
    return {'channels': len(listed), 'added': added, 'changed': changed, 'disabled': disabled}


def values(account, item):
    return {'account': account, 'label': item['label'], 'address': item['address'], 'waba_id': item['waba_id'],
            'enabled': int(item['enabled'])}


def insert(account, item):
    """A new number or bot starts with the company and triage owner of the site's first channel of its type."""
    first = frappe.db.get_value('Relay Channel', {'account': account, 'channel': item['provider']},
                                ['company', 'triage_owner'], as_dict=True, order_by='is_default desc, creation asc')
    doc = frappe.get_doc(dict(values(account, item), doctype='Relay Channel', channel=item['provider'],
                              hub_channel=item['key'], title=(item['label'] or f"{item['provider']} {item['address'] or item['key']}")[:120],
                              company=(first or {}).get('company'), triage_owner=(first or {}).get('triage_owner')))
    doc.insert(ignore_permissions=True)


def update(row, account, item):
    wanted = values(account, item)
    if all(str(row.get(field) or '') == str(value or '') for field, value in wanted.items()):
        return False
    save(frappe.get_doc('Relay Channel', row.name), wanted)
    return True


def save(doc, changes):
    doc.update(changes)
    doc.save(ignore_permissions=True)


def keep_one_default(account):
    """Adding a second number must not change where existing flows send, so the oldest becomes the default."""
    for provider in PROVIDERS:
        rows = frappe.get_all('Relay Channel', fields=['name', 'is_default'], order_by='creation asc',
                              filters={'account': account, 'channel': provider, 'enabled': 1})
        if len(rows) > 1 and not any(row.is_default for row in rows):
            save(frappe.get_doc('Relay Channel', rows[0].name), {'is_default': 1})


def queue_sync():
    frappe.enqueue('relay_core.channel_sync.sync', queue='short', job_id='relay-channel-sync', deduplicate=True,
                   enqueue_after_commit=True)


@frappe.whitelist(methods=['POST'])
def refresh():
    require_access(configure=True)
    return sync()
