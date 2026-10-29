"""Provider-specific campaign preparation and durable Telegram/email receipts."""
import time
import frappe
from relay_core.business_access import business_document, document_name
from relay_core import whatsapp
from relay_core.permissions import require_business_assignment, readable_contact
from relay_core.automation.service import internal_save
from relay_core.automation.provenance import integer


def prepare(doc, contact, args):
    document_name(contact)
    person=frappe.get_doc('Contact',contact)
    require_business_assignment(contact)
    business_document(doc.business_doctype,doc.business_name)
    if not whatsapp.configured_business_type(doc.business_doctype) or not any(link.link_doctype==doc.business_doctype and link.link_name==doc.business_name for link in person.links):
        frappe.throw('Contact is not linked to the selected configured business record')
    relay=frappe.db.get_value('Relay Contact',{'contact':contact},'name')
    if not relay:frappe.throw('Contact has no verified messaging identity')
    readable_contact(relay)
    endpoints=frappe.get_all('Relay Contact Endpoint',filters={'relay_contact':relay,'channel':doc.channel,'verified':1},pluck='endpoint',limit_page_length=2)
    if len(endpoints)!=1:frappe.throw('Campaign recipient must have exactly one verified endpoint on this channel')
    provider=frappe.db.get_value('Relay Channel',doc.channel,'channel')
    if provider=='Telegram':
        try:chat=integer(int(endpoints[0]))
        except (ValueError,TypeError):frappe.throw('Invalid Telegram recipient')
        if chat<0:frappe.throw('Campaigns require private Telegram recipients')
        return {'to':endpoints[0],'operation':'text','chat_id':chat,'text':args['body']}
    if provider=='Email':
        from relay_core.email import recipients
        address=recipients(endpoints,required=True)[0]
        return {'to':address,'subject':args['subject'],'body':args['body']}
    frappe.throw('Unsupported campaign channel')


def receipt(row, value, provider):
    from relay_core import campaigns
    if value.get('key')!=row.request_key:raise ValueError('Delivery key mismatch')
    expected='telegram.message' if provider=='Telegram' else 'email.send'
    if value.get('operation')!=expected:raise ValueError('Delivery provider mismatch')
    row.delivery_id=str(value.get('id') or '')
    row.status={'queued':'Queued','dispatching':'Queued','submitted':'Submitted','rejected':'Rejected','cancelled':'Cancelled','uncertain':'Uncertain'}.get(value.get('state'),'Uncertain')
    result=value.get('result') or {}
    if row.status=='Submitted':
        identifier=result.get('message_id')
        if provider=='Telegram':integer(identifier,positive=True)
        elif not isinstance(identifier,str) or not identifier:raise ValueError('Missing email provider receipt')
        row.provider_id=str(identifier)
    row.reason='Provider rejected this delivery.' if row.status=='Rejected' else ''
    internal_save(row)
    if row.status=='Submitted':campaigns.record_message(row)


def tick(doc, refresh_only, deadline):
    """Called under the campaign lock and execution-user permission context."""
    from relay_core import campaigns
    provider=frappe.db.get_value('Relay Channel',doc.channel,'channel')
    hub=whatsapp.client()
    states=['Dispatching','Queued','Uncertain']+(['Submitted'] if refresh_only else [])
    inflight=frappe.get_all('Relay Campaign Recipient',filters={'campaign':doc.name,'status':['in',states]},pluck='name',order_by='modified asc',limit_page_length=20)
    for name in inflight:
        if time.monotonic()>deadline:break
        row=frappe.get_doc('Relay Campaign Recipient',name)
        try:
            found=hub.call_tool('channels.deliveries',{'request_key':row.request_key}).get('deliveries') or []
            if len(found)==1:
                receipt(row,found[0],provider)
                if doc.status=='Cancelling' and row.status=='Queued':
                    hub.call_tool('channels.deliveries',{'cancel_id':int(row.delivery_id)})
                    # Confirm cancellation from the authoritative single receipt next tick.
            elif not found:
                row.status='Uncertain';row.reason='Hub admission is unconfirmed; this recipient is not automatically resent.';internal_save(row)
            else:raise ValueError('Ambiguous delivery receipt')
        except whatsapp.HubError:
            row.reason='Delivery journal unavailable; checking will not resend this message.';internal_save(row)
        frappe.db.commit()
    if doc.status=='Cancelling':
        for name in frappe.get_all('Relay Campaign Recipient',filters={'campaign':doc.name,'status':'Pending'},pluck='name',limit_page_length=50):
            frappe.db.set_value('Relay Campaign Recipient',name,'status','Cancelled')
    elif doc.status=='Running' and not refresh_only:
        for name in frappe.get_all('Relay Campaign Recipient',filters={'campaign':doc.name,'status':'Pending'},pluck='name',order_by='name asc',limit_page_length=10):
            if time.monotonic()>deadline:break
            row=frappe.get_doc('Relay Campaign Recipient',name)
            try:
                payload=campaigns.prepared(doc,row.contact,row.arguments)
                if campaigns.digest(payload)!=row.prepared_hash:raise ValueError('Recipient or content changed')
            except (ValueError,frappe.PermissionError,frappe.ValidationError):
                row.status='Rejected';row.reason='Recipient, content or business access changed.';internal_save(row);frappe.db.commit();continue
            row.status='Dispatching';row.attempted=1;internal_save(row);frappe.db.commit()
            tool='telegram.message' if provider=='Telegram' else 'email.send'
            args={key:value for key,value in payload.items() if key!='to'} if provider=='Telegram' else dict(payload,to=[payload['to']])
            try:
                result=hub.call_tool(tool,dict(args,request_key=row.request_key))
                receipt(row,{'key':row.request_key,'id':result.get('delivery_id'),'state':'submitted','operation':tool,'result':result},provider)
            except Exception:
                # Any response/projection failure after admission preserves uncertainty.
                frappe.db.rollback();row.reload();row.status='Uncertain';row.reason='Send outcome is unconfirmed; checking will not resend.';internal_save(row)
            frappe.db.commit()
    if not frappe.db.exists('Relay Campaign Recipient',{'campaign':doc.name,'status':['in',list(campaigns.ACTIVE)]}):
        doc.status='Cancelled' if doc.status=='Cancelling' else 'Completed'
    doc.last_error='';internal_save(doc);frappe.db.commit()
