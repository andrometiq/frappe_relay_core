"""Fold private receipts and retain early evidence until its message exists."""
import hashlib
import json
import frappe
from relay_core.receipt_order import advances


def collapse(updates):
    result = {}
    # Timestamp order makes same-batch application independent of transport order.
    for update in sorted(updates, key=lambda row: (row['timestamp'], row['status'])):
        key = (update['destination'], update['target'])
        previous = result.get(key)
        if previous is None or advances(previous['status'], update['status'], previous['timestamp'], update['timestamp']):
            result[key] = update
    return list(result.values())


def lock_endpoints(channel, destinations):
    keys = [hashlib.sha256((channel + ':' + value).encode()).hexdigest() for value in destinations]
    endpoint = frappe.qb.DocType('Relay Contact Endpoint')
    rows = (frappe.qb.from_(endpoint).select(endpoint.endpoint, endpoint.relay_contact)
            .where(endpoint.endpoint_key.isin(keys) & (endpoint.verified == 1))
            .orderby(endpoint.name).for_update().run(as_dict=True))
    return {row.endpoint: row.relay_contact for row in rows}


def apply_batch(updates, channel):
    from relay_core.message_updates import provider_key
    updates = collapse(updates)
    contacts = lock_endpoints(channel, {row['destination'] for row in updates})
    keys = {provider_key(channel, row['destination'], row['target']): row for row in updates}
    message = frappe.qb.DocType('Relay Message')
    rows = (frappe.qb.from_(message).select(message.name, message.provider_message_key, message.relay_contact, message.sender_endpoint,
            message.direction, message.status, message.message_updates, message.business_doctype, message.business_name).where(message.provider_message_key.isin(list(keys)))
            .orderby(message.name).for_update().run(as_dict=True))
    messages = {row.provider_message_key: row for row in rows}
    pending = {row.name: row for row in frappe.get_all('Relay Pending Receipt',
        filters={'name': ['in', list(keys)]}, fields=['name', 'status', 'provider_timestamp', 'event_id'])}
    writes, retained, inserts, notifications = {}, {}, [], {}
    unresolved = False
    stamp = frappe.utils.now_datetime()
    for key, update in keys.items():
        contact = contacts.get(update['destination'])
        if not contact:
            unresolved = True
            continue
        previous = pending.get(key)
        if previous and not advances(previous.status, update['status'], int(previous.provider_timestamp), update['timestamp']):
            update = dict(update, status=previous.status, timestamp=int(previous.provider_timestamp), event_id=previous.event_id)
        doc = messages.get(key)
        if doc is None:
            values = {'status': update['status'], 'provider_timestamp': str(update['timestamp']), 'event_id': update['event_id']}
            if previous:
                retained[key] = values
            else:
                inserts.append((key, key, channel, update['destination'], values['status'], values['provider_timestamp'], values['event_id'], stamp, stamp, frappe.session.user, frappe.session.user, 0, 0))
            continue
        if doc.relay_contact != contact or doc.sender_endpoint != update['destination']:
            unresolved = True
            continue
        if doc.direction != 'Outgoing': continue
        values = receipt_values(doc, update)
        if values:
            writes[doc.name] = values
            notifications[(doc.relay_contact, doc.business_doctype, doc.business_name)] = doc
    if inserts:
        frappe.db.bulk_insert('Relay Pending Receipt',
            ['name','record_key','channel','endpoint','status','provider_timestamp','event_id','creation','modified','owner','modified_by','docstatus','idx'], inserts)
    if retained: frappe.db.bulk_update('Relay Pending Receipt', retained, update_modified=False)
    if writes: frappe.db.bulk_update('Relay Message', writes, update_modified=False)
    from relay_core.realtime import changed
    for doc in notifications.values():
        doc.doctype = 'Relay Message'
        changed(doc)
    return 'Uncategorized' if unresolved else 'Projected'


def receipt_values(doc, update):
    history = json.loads(doc.message_updates or '{}') if isinstance(doc.message_updates, str) else doc.message_updates or {}
    previous = history.get('delivery', {})
    if not advances(doc.status, update['status'], int(previous.get('timestamp', 0)), update['timestamp']):
        return None
    history['delivery'] = {'timestamp': update['timestamp'], 'event_id': update['event_id']}
    return {'status': update['status'], 'message_updates': json.dumps(history)}


def apply_pending(doc):
    """Caller holds the endpoint lock across outgoing insertion and this read."""
    row = frappe.db.get_value('Relay Pending Receipt', doc.provider_message_key,
                              ['status', 'provider_timestamp', 'event_id'], as_dict=True)
    if not row: return
    values = receipt_values(doc, {'status': row.status, 'timestamp': int(row.provider_timestamp), 'event_id': row.event_id})
    if values:
        frappe.db.set_value('Relay Message', doc.name, values, update_modified=False)
        doc.update(values)
