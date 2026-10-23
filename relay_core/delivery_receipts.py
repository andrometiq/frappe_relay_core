"""Participant receipts stored separately so group size cannot grow message JSON."""
import hashlib
import re
import frappe

from relay_core.receipt_order import advances

def record(message, update):
    # Caller holds the Relay Message row lock and has verified its endpoint.
    key=hashlib.sha256((message.name+':'+update['participant']).encode()).hexdigest()
    existing=frappe.db.get_value('Relay Delivery Receipt',key,['status','provider_timestamp'],as_dict=True)
    if existing:
        if not advances(existing.status,update['status'],int(existing.provider_timestamp),update['timestamp']):return False
        frappe.db.set_value('Relay Delivery Receipt',key,{'status':update['status'],'provider_timestamp':str(update['timestamp'])},update_modified=False)
    else:
        previous=getattr(frappe.flags,'relay_receipt_write',False)
        frappe.flags.relay_receipt_write=True
        try:
            frappe.get_doc({'doctype':'Relay Delivery Receipt','receipt_key':key,'message':message.name,
                'participant':update['participant'],'status':update['status'],'provider_timestamp':str(update['timestamp'])}).insert(ignore_permissions=True)
        finally:frappe.flags.relay_receipt_write=previous
    return True

@frappe.whitelist(methods=['GET'])
def directory(message, after=None):
    from relay_core.messaging import readable_source
    source,channel,context=readable_source(message)
    if after and (not isinstance(after,str) or not re.fullmatch('[0-9a-f]{64}',after)):raise ValueError('Invalid receipt cursor')
    if channel.channel!='WhatsApp' or source.direction!='Outgoing' or not context.get('group_id'):
        return {'items':[],'next':None}
    filters={'message':source.name}
    if after:filters['name']=['>',after]
    rows=frappe.get_all('Relay Delivery Receipt',filters=filters,fields=['name','participant','status','provider_timestamp'],order_by='name asc',limit_page_length=51)
    return {'items':rows[:50],'next':rows[49].name if len(rows)>50 else None}
