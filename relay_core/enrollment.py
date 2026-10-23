"""Explicit manager mapping of authenticated, previously uncategorized senders."""
import hashlib
import json
import frappe
from relay_core.permissions import require_access, readable_contact
from relay_core.automation.projection import extract_messages, project
from relay_core.settings import value as connection_value


def event_rows(name):
    event=frappe.get_doc('Relay Hub Event',name)
    if event.account!=connection_value('relay_hub_account'):frappe.throw('Event belongs to another Hub account',frappe.PermissionError)
    payload=json.loads(event.payload);medium=payload.get('channel','WhatsApp')
    channels=frappe.get_all('Relay Channel',filters={'account':event.account,'channel':medium,'enabled':1},pluck='name',limit_page_length=2)
    if len(channels)!=1:frappe.throw('Configure one enabled channel for this account in Desk')
    frappe.get_doc('Relay Channel',channels[0]).check_permission('read')
    return event,channels[0],medium,extract_messages(payload)


@frappe.whitelist(methods=['GET'])
def pending(after=None):
    require_access(manage=True)
    filters={'projection_status':'Uncategorized','account':connection_value('relay_hub_account')}
    if after:
        from relay_core.api import validate_reference
        validate_reference(after,'EVT');filters['name']=['>',after]
    events=frappe.get_all('Relay Hub Event',filters=filters,fields=['name'],order_by='name asc',limit_page_length=21)
    items=[]
    for event in events[:20]:
        try:doc,channel,medium,rows=event_rows(event.name)
        except (ValueError,frappe.ValidationError):
            items.append({'event':event.name,'configuration_required':True});continue
        for row in rows:
            key=hashlib.sha256((channel+':'+row['from']).encode()).hexdigest()
            contact = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key':key,'verified':1}, 'relay_contact')
            from relay_core.message_updates import provider_key
            if frappe.db.exists('Relay Message', {'provider_message_key': provider_key(channel, row['from'], row['id'])}): continue
            data=row.get('message_data') or {};detail=row.get('text') or {}
            items.append({'event':doc.name,'channel':channel,'medium':medium,'provider_id':row['id'],
                          'endpoint':row['from'],'preview':str(data.get('text') or data.get('caption') or detail.get('body') or '['+row.get('type','message')+']')[:300],
                          'received_at':doc.creation,'contact':contact,'ambiguous':bool(contact),
                          'routing_rule':json.loads(doc.get('routing_decisions') or '{}').get(row['id'])})
    return {'items':items,'next':events[19].name if len(events)>20 else None}


@frappe.whitelist(methods=['POST'])
def bind(event, provider_id, contact, business_doctype=None, business_name=None):
    require_access(manage=True);readable_contact(contact)
    doc,channel,medium,rows=event_rows(event)
    matches=[row for row in rows if row['id']==provider_id]
    if len(matches)!=1:frappe.throw('Select a sender from the authenticated incoming event')
    from relay_core.business_access import candidates
    links = candidates(contact)
    business = (business_doctype, business_name) if business_doctype or business_name else links[0] if len(links) == 1 else None
    if business not in links: frappe.throw('Choose a linked business record')
    frappe.get_doc(*business).check_permission('read')
    endpoint=matches[0]['from'];key=hashlib.sha256((channel+':'+endpoint).encode()).hexdigest()
    with frappe.cache.lock('relay-enroll:'+key,timeout=30):
        existing=frappe.db.get_value('Relay Contact Endpoint',{'endpoint_key':key},['name','relay_contact','verified'],as_dict=True)
        if existing:
            if existing.relay_contact!=contact:frappe.throw('This sender is already linked to another contact')
            if not existing.verified:frappe.throw('This binding was revoked. An administrator must review it in Desk')
        else:
            previous=getattr(frappe.flags,'relay_endpoint_enrollment',False);frappe.flags.relay_endpoint_enrollment=True
            try:frappe.get_doc(dict(doctype='Relay Contact Endpoint',channel=channel,relay_contact=contact,endpoint=endpoint,verified=1)).insert(ignore_permissions=True)
            finally:frappe.flags.relay_endpoint_enrollment=previous
        # Only project stored history. Existing message hooks retain their configured behavior.
        project(doc.name, business_overrides={provider_id: business});frappe.db.commit()
    return {'contact':contact,'event':doc.name,'status':frappe.db.get_value('Relay Hub Event',doc.name,'projection_status')}


@frappe.whitelist(methods=['GET'])
def businesses(contact):
    require_access(manage=True); readable_contact(contact)
    from relay_core.business_access import candidates
    return [{'doctype': dt, 'name': name} for dt, name in candidates(contact)
            if frappe.get_doc(dt, name).has_permission('read')]
