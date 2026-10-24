"""Explicit manager mapping of authenticated, previously uncategorized senders."""
import hashlib
import json
import frappe
from relay_core.permissions import require_access, readable_contact
from relay_core.automation.projection import extract_messages, project
from relay_core.settings import value as connection_value


def event_rows(name):
    require_access(manage=True)
    event=frappe.get_doc('Relay Hub Event',name)
    if event.account!=connection_value('relay_hub_account'):frappe.throw('Event belongs to another Hub account',frappe.PermissionError)
    payload=json.loads(event.payload);medium=payload.get('channel','WhatsApp')
    channels=frappe.get_all('Relay Channel',filters={'account':event.account,'channel':medium,'enabled':1},pluck='name',limit_page_length=2)
    if len(channels)!=1:frappe.throw('Configure one enabled channel for this account in Desk')
    channel = frappe.get_doc('Relay Channel',channels[0])
    channel.check_permission('read')
    from relay_core.permissions import company_allowed
    if not company_allowed(channel.get('company')):
        frappe.throw('Triage company is not accessible', frappe.PermissionError)
    return event,channels[0],medium,extract_messages(payload)


def source_ticket(channel, row):
    """The saved source company remains authoritative after channel reassignment."""
    from relay_core.tickets import source_episode
    from relay_core.permissions import company_allowed
    _, action = source_episode(channel, row)
    ticket = frappe.db.get_value('Relay Ticket', {'source_action_key': action}, ['name', 'company'], as_dict=True)
    if ticket and not company_allowed(ticket.company):
        frappe.throw('Source company is not accessible', frappe.PermissionError)
    return ticket


@frappe.whitelist(methods=['GET'])
def pending(after=None):
    # Unprojected events have no trustworthy business owner yet.
    require_access(manage=True)
    filters={'projection_status':'Uncategorized','account':connection_value('relay_hub_account')}
    if after:
        from relay_core.api import validate_reference
        validate_reference(after,'EVT');filters['name']=['>',after]
    events=frappe.get_all('Relay Hub Event',filters=filters,fields=['name'],order_by='name asc',limit_page_length=21)
    items=[]
    for event in events[:20]:
        try:doc,channel,medium,rows=event_rows(event.name)
        except frappe.PermissionError:
            continue
        except (ValueError,frappe.ValidationError):
            continue
        for row in rows:
            try:
                ticket = source_ticket(channel, row)
            except frappe.PermissionError:
                continue
            key=hashlib.sha256((channel+':'+row['from']).encode()).hexdigest()
            contact = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key':key}, 'relay_contact')
            from relay_core.tickets import source_episode
            message_key, _ = source_episode(channel, row)
            if frappe.db.exists('Relay Message', {'provider_message_key': message_key}): continue
            items.append({'event':doc.name,'channel':channel,'medium':medium,'provider_id':row['id'],
                          'endpoint':row['from'],'preview':'Incoming conversation needs triage', 'ticket':ticket.name if ticket else None,
                          'received_at':doc.creation,'contact':None,'ambiguous':bool(contact),
                          'routing_rule':json.loads(doc.get('routing_decisions') or '{}').get(row['id'])})
    return {'items':items,'next':events[19].name if len(events)>20 else None}


@frappe.whitelist(methods=['POST'])
def bind(event, provider_id, contact, business_doctype=None, business_name=None):
    require_access(manage=True);readable_contact(contact)
    doc,channel,medium,rows=event_rows(event)
    matches=[row for row in rows if row['id']==provider_id]
    if len(matches)!=1:frappe.throw('Select a sender from the authenticated incoming event')
    ticket = source_ticket(channel, matches[0])
    if ticket and ticket.company != frappe.db.get_value('Relay Channel', channel, 'company'):
        frappe.throw('Source company no longer matches the channel', frappe.PermissionError)
    from relay_core.business_access import candidates
    links = candidates(contact)
    business = (business_doctype, business_name) if business_doctype or business_name else links[0] if len(links) == 1 else None
    if business not in links: frappe.throw('Choose a linked business record')
    frappe.get_doc(*business).check_permission('read')
    from relay_core.identity import bindings, normalize
    endpoint=normalize(medium, matches[0]['from']);key=hashlib.sha256((channel+':'+endpoint).encode()).hexdigest()
    with frappe.cache.lock('relay-enroll:'+key,timeout=30):
        aliases = list(bindings(channel, medium, endpoint))
        if len(aliases) > 1:frappe.throw('Conflicting legacy bindings require administrator review')
        existing = aliases[0] if aliases else None
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


@frappe.whitelist(methods=['POST'])
def revoke(endpoint):
    require_access(manage=True)
    doc = frappe.get_doc('Relay Contact Endpoint', endpoint)
    readable_contact(doc.relay_contact)
    channel = frappe.get_doc('Relay Channel', doc.channel)
    channel.check_permission('read')
    if channel.account != connection_value('relay_hub_account'):
        frappe.throw('Endpoint belongs to another Hub account', frappe.PermissionError)
    previous = getattr(frappe.flags, 'relay_endpoint_enrollment', False)
    try:
        frappe.flags.relay_endpoint_enrollment = True
        doc.verified = 0
        doc.save(ignore_permissions=True)
    finally:
        frappe.flags.relay_endpoint_enrollment = previous
    return {'endpoint': doc.name, 'verified': False}
