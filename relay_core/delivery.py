import frappe
from relay_core.permissions import require_access
from relay_core.whatsapp import client, deliveries


@frappe.whitelist(methods=['POST'])
def page(channel='WhatsApp', after=None, cancel_id=None):
    require_access(manage=True)
    for value in (after,cancel_id):
        if value is not None and (isinstance(value,bool) or not str(value).isdigit()):frappe.throw('Invalid delivery cursor')
    if channel=='WhatsApp':return deliveries(after=str(after or ''),cancel_id=str(cancel_id) if cancel_id is not None else None)
    if channel!='Telegram and email':frappe.throw('Invalid delivery channel')
    return client().call_tool('channels.deliveries',{**({'after':int(after)} if after else {}),**({'cancel_id':int(cancel_id)} if cancel_id else {})})


@frappe.whitelist(methods=['POST'])
def resolve(delivery_id, outcome, note, channel="Telegram and email", provider_id=""):
    require_access(manage=True)
    if isinstance(delivery_id, bool) or not str(delivery_id).isdigit() or int(delivery_id)<1:
        frappe.throw('Invalid delivery ID')
    if outcome not in ('submitted','rejected') or not isinstance(note,str) or not 10<=len(note.strip())<=2000:
        frappe.throw('Choose the verified outcome and describe your evidence in 10–2000 characters')
    if channel == 'WhatsApp':
        if not isinstance(provider_id,str) or len(provider_id)>300 or any(c.isspace() for c in provider_id): frappe.throw('Invalid provider message ID')
        return client().call_tool('whatsapp.resolve',{'id':int(delivery_id),'outcome':outcome,'note':note.strip(),'provider_id':provider_id})
    if channel != 'Telegram and email': frappe.throw('Invalid delivery channel')
    return client().call_tool('channels.resolve',{'id':int(delivery_id),'outcome':outcome,'note':note.strip()})
