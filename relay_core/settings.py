"""Site-owned connection settings. Password values never enter read responses."""
import re
import frappe
from relay_core.permissions import require_access
from relay_core.hub import HubClient

# Channels the Relay UI offers. Telegram and Email backends stay intact for a later switch-on.
ENABLED_CHANNELS=('WhatsApp',)

FIELDS={'relay_hub_url':'hub_url','relay_hub_account':'hub_account','relay_hub_token':'hub_token','relay_callback_secret':'callback_secret'}

def value(key):
    # Existing private site configuration remains supported on older installs.
    db=getattr(frappe,'db',None)
    if db is not None and hasattr(frappe,'get_single') and db.exists('DocType','Relay Settings'):
        doc=frappe.get_single('Relay Settings')
        field=FIELDS[key]
        result=doc.get_password(field,raise_exception=False) if field in ('hub_token','callback_secret') else doc.get(field)
        if result:return result
    return frappe.conf.get(key)

@frappe.whitelist(methods=['GET'])
def connection():
    require_access()
    return {'url':value('relay_hub_url') or '', 'account':value('relay_hub_account') or '',
            'token_configured':bool(value('relay_hub_token')),
            'callback_configured':bool(value('relay_callback_secret')),
            'can_configure':'System Manager' in frappe.get_roles()}

@frappe.whitelist(methods=['POST'])
def save_connection(url,account,token='',callback_secret=''):
    require_access(configure=True)
    if not isinstance(account,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',account):
        raise ValueError('Invalid Hub account')
    if not isinstance(token,str) or not isinstance(callback_secret,str):raise ValueError('Invalid credentials')
    credential=token or value('relay_hub_token') or ''
    hub=HubClient(url,credential)
    binding=hub.call_tool('account.get',{})
    if binding.get('account')!=account or str(binding.get('site','')).rstrip('/')!=frappe.utils.get_url().rstrip('/'):
        frappe.throw('Hub account does not match this Frappe site',frappe.PermissionError)
    if callback_secret and (len(callback_secret)<32 or len(callback_secret)>512 or any(ord(c)<32 for c in callback_secret)):
        raise ValueError('Callback secret must contain 32–512 printable characters')
    doc=frappe.get_single('Relay Settings')
    doc.hub_url=url;doc.hub_account=account
    if token:doc.hub_token=token
    if callback_secret:doc.callback_secret=callback_secret
    doc.save()
    from relay_core.channel_sync import sync
    return {'saved':True,'channels':sync()}


@frappe.whitelist(methods=['POST'])
def verify_connection():
    require_access(configure=True)
    hub=HubClient(value('relay_hub_url') or '',value('relay_hub_token') or '')
    binding=hub.call_tool('account.get',{})
    if binding.get('account')!=value('relay_hub_account') or str(binding.get('site','')).rstrip('/')!=frappe.utils.get_url().rstrip('/'):
        frappe.throw('Hub account does not match this Frappe site',frappe.PermissionError)
    from relay_core.channel_sync import sync
    return {'verified':True,'channels':sync()}
