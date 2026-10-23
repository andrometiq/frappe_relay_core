"""Durable, authenticated batched callbacks from the site's Relay Hub account."""
import hashlib
import hmac
import json
import re
import time
import frappe
from relay_core.settings import value as connection_value


def authenticated_payload(raw, timestamp, signature, secret, expected_account):
    if not isinstance(secret, str) or len(secret) < 32:
        raise ValueError('Callback authentication is not configured')
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Callback is too large')
    try:
        age = abs(time.time() - int(timestamp))
    except (TypeError, ValueError):
        raise ValueError('Invalid callback timestamp') from None
    if age > 300:
        raise ValueError('Expired callback')
    expected = hmac.new(secret.encode(), str(timestamp).encode() + b'.' + raw, hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise ValueError('Invalid callback signature')
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get('account') != expected_account:
        raise ValueError('Callback account mismatch')
    return payload


def validate_callback(raw, timestamp, signature, secret, expected_account):
    payload = authenticated_payload(raw, timestamp, signature, secret, expected_account)
    events = payload.get('events')
    if not isinstance(events, list) or not 1 <= len(events) <= 50:
        raise ValueError('Expected 1 to 50 events')
    for event in events:
        if not isinstance(event, dict) or type(event.get('id')) is not int or not 1 <= event['id'] <= 9223372036854775807 or not isinstance(event.get('payload'), dict):
            raise ValueError('Invalid event')
    return payload


@frappe.whitelist(methods=['POST'])
def receive(**_ignored):
    if not {'System Manager', 'Relay Hub Service'}.intersection(frappe.get_roles(frappe.session.user)):
        frappe.throw('Not permitted', frappe.PermissionError)
    try:
        payload = validate_callback(
            frappe.request.get_data(), frappe.request.headers.get('X-Relay-Timestamp'),
            frappe.request.headers.get('X-Relay-Signature'), connection_value('relay_callback_secret'),
            connection_value('relay_hub_account'))
    except (ValueError, TypeError):
        frappe.throw('Invalid Relay callback', frappe.PermissionError)
    account = payload['account']
    if not isinstance(account, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', account):
        frappe.throw('Invalid account')
    for event in payload['events']:
        medium = event['payload'].get('channel', 'WhatsApp')
        if medium not in ('WhatsApp', 'Telegram', 'Email'):
            frappe.throw('Unsupported event channel')
        key = (f"{account}:{event['id']}" if medium == 'WhatsApp'
               else f"{account}:{medium}:{event['id']}")
        encoded = json.dumps(event['payload'], sort_keys=True, separators=(',', ':'))
        existing = frappe.db.get_value('Relay Hub Event', {'event_key': key}, ['name', 'payload'], as_dict=True)
        if existing:
            if json.loads(existing.payload) != event['payload']:
                frappe.throw('Conflicting Hub event')
            continue
        # A duplicate after an HTTP timeout is normal. The unique key protects
        # against concurrent retries; a failed transaction is retried by Hub.
        frappe.get_doc({'doctype': 'Relay Hub Event', 'event_key': key, 'account': account,
                        'hub_event_id': str(event['id']), 'payload': encoded}).insert()
    # Frappe commits successful POST methods before returning the acknowledgement.
    # Per-user notifications avoid broadcasting event contents to all site users.
    frappe.publish_realtime('relay_events_available', {'account': account}, user=frappe.session.user, after_commit=True)
    return {'accepted': len(payload['events'])}


def validate_status_callback(raw, timestamp, signature, secret, expected_account):
    payload = authenticated_payload(raw, timestamp, signature, secret, expected_account)
    if set(payload) != {'account', 'statuses'}:
        raise ValueError('Invalid status callback fields')
    statuses = payload['statuses']
    if not isinstance(statuses, list) or not 1 <= len(statuses) <= 500:
        raise ValueError('Expected 1 to 500 statuses')
    previous = (0, -1)
    for row in statuses:
        required={'event_id','position','message_id','recipient','status','timestamp'}
        if not isinstance(row, dict) or not required.issubset(row) or set(row)-required-{'participant','recipient_type'}:
            raise ValueError('Invalid compact status')
        if type(row['event_id']) is not int or not 1 <= row['event_id'] <= 9223372036854775807:
            raise ValueError('Invalid status event identity')
        if type(row['position']) is not int or not 0 <= row['position'] <= 1000000:
            raise ValueError('Invalid status position')
        identity = (row['event_id'], row['position'])
        if identity <= previous:
            raise ValueError('Status identities must be strictly ordered')
        previous = identity
        if row['status'] not in ('sent','delivered','read','failed'):
            raise ValueError('Invalid delivery status')
        for field, maximum in (('message_id',300),('recipient',200)):
            if not isinstance(row[field],str) or not 1 <= len(row[field]) <= maximum or '\x00' in row[field]:
                raise ValueError('Invalid receipt target')
        if 'recipient_type' in row and row['recipient_type'] not in ('group','individual'):
            raise ValueError('Invalid receipt recipient type')
        if 'participant' in row and (row.get('recipient_type')!='group' or not isinstance(row['participant'],str) or not 1<=len(row['participant'])<=200 or '\x00' in row['participant']):
            raise ValueError('Invalid receipt participant')
        if type(row['timestamp']) is not int or not 0 <= row['timestamp'] <= 9223372036854775807:
            raise ValueError('Invalid receipt timestamp')
    return payload


@frappe.whitelist(methods=['POST'])
def receive_statuses(**_ignored):
    """Durably accept a bounded compact receipt batch for background projection."""
    if not {'System Manager','Relay Hub Service'}.intersection(frappe.get_roles(frappe.session.user)):
        frappe.throw('Not permitted',frappe.PermissionError)
    try:
        payload = validate_status_callback(frappe.request.get_data(),
            frappe.request.headers.get('X-Relay-Timestamp'),frappe.request.headers.get('X-Relay-Signature'),
            connection_value('relay_callback_secret'),connection_value('relay_hub_account'))
    except (ValueError,TypeError):
        frappe.throw('Invalid Relay status callback',frappe.PermissionError)
    account = payload['account']
    if not isinstance(account,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',account):
        frappe.throw('Invalid account')
    encoded = json.dumps(payload,sort_keys=True,separators=(',',':'))
    key = 'statuses:' + hashlib.sha256(encoded.encode()).hexdigest()
    if not frappe.db.exists('Relay Hub Event', {'event_key':key}):
        # Retain the existing projection's verified endpoint binding, receipt
        # ordering, retry handling and update_modified=False behavior.
        statuses = [{'id':row['message_id'],'recipient_id':row['recipient'],
                     'status':row['status'],'timestamp':str(row['timestamp']),
                     **({'recipient_type':row['recipient_type']} if 'recipient_type' in row else {}),
                     **({'recipient_participant_id':row['participant']} if 'participant' in row else {})} for row in payload['statuses']]
        projection = {'entry':[{'changes':[{'value':{'statuses':statuses}}]}]}
        frappe.get_doc({'doctype':'Relay Hub Event','event_key':key,'account':account,
            'hub_event_id':str(payload['statuses'][-1]['event_id']),
            'payload':json.dumps(projection,sort_keys=True,separators=(',',':'))}).insert()
    return {'accepted':len(payload['statuses'])}


def validate_channel_status_callback(raw, timestamp, signature, secret, expected_account):
    """Validate the compact Telegram/email delivery-journal contract."""
    from datetime import datetime
    payload = authenticated_payload(raw, timestamp, signature, secret, expected_account)
    if set(payload) != {'account', 'statuses'}:
        raise ValueError('Invalid channel status fields')
    rows = payload['statuses']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        raise ValueError('Expected 1 to 500 channel statuses')
    if len(json.dumps(rows, separators=(',', ':'), ensure_ascii=False).encode()) > 512 * 1024:
        raise ValueError('Channel status batch exceeds byte limit')
    previous = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id','delivery_id','request_key','operation','state','receipt','occurred_at'}:
            raise ValueError('Invalid channel status row')
        if type(row['id']) is not int or not previous < row['id'] <= 9223372036854775807:
            raise ValueError('Invalid channel status identity')
        previous = row['id']
        if type(row['delivery_id']) is not int or not 0 < row['delivery_id'] <= 9223372036854775807:
            raise ValueError('Invalid delivery identity')
        if not isinstance(row['request_key'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', row['request_key']):
            raise ValueError('Invalid delivery request key')
        if row['operation'] not in ('telegram.message','email.send') or row['state'] not in ('submitted','rejected','uncertain','cancelled'):
            raise ValueError('Invalid channel delivery state')
        receipt = row['receipt']
        if not isinstance(receipt, dict) or set(receipt)-{'message_id','chat_id','operation','sent','result','manually_reconciled'}:
            raise ValueError('Invalid compact receipt')
        if len(json.dumps(receipt, separators=(',', ':')).encode()) > 8192:
            raise ValueError('Receipt exceeds byte limit')
        for field in ('sent','result','manually_reconciled'):
            if field in receipt and type(receipt[field]) is not bool:
                raise ValueError('Invalid receipt flag')
        for field in ('message_id','chat_id'):
            if field in receipt and (type(receipt[field]) not in (str,int) or len(str(receipt[field])) > 512):
                raise ValueError('Invalid provider receipt identity')
        if 'operation' in receipt and (not isinstance(receipt['operation'],str) or len(receipt['operation'])>64):
            raise ValueError('Invalid receipt operation')
        if not isinstance(row['occurred_at'],str) or len(row['occurred_at'])>40:
            raise ValueError('Invalid status timestamp')
        parsed = datetime.fromisoformat(row['occurred_at'].replace('Z','+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Status timestamp requires a timezone')
    return payload


@frappe.whitelist(methods=['POST'])
def receive_channel_statuses(**_ignored):
    """Acknowledge only after a signed channel status batch is durably stored."""
    if not {'System Manager','Relay Hub Service'}.intersection(frappe.get_roles(frappe.session.user)):
        frappe.throw('Not permitted',frappe.PermissionError)
    try:
        payload = validate_channel_status_callback(frappe.request.get_data(),
            frappe.request.headers.get('X-Relay-Timestamp'),frappe.request.headers.get('X-Relay-Signature'),
            connection_value('relay_callback_secret'),connection_value('relay_hub_account'))
    except (ValueError,TypeError):
        frappe.throw('Invalid Relay channel status callback',frappe.PermissionError)
    encoded=json.dumps(payload,sort_keys=True,separators=(',',':'))
    key='channel-statuses:'+hashlib.sha256(encoded.encode()).hexdigest()
    if not frappe.db.exists('Relay Hub Event',{'event_key':key}):
        frappe.get_doc({'doctype':'Relay Hub Event','event_key':key,'account':payload['account'],
            'hub_event_id':str(payload['statuses'][-1]['id']),
            'payload':json.dumps({'channel_statuses':payload['statuses']},sort_keys=True,separators=(',',':'))}).insert()
    return {'accepted':len(payload['statuses'])}
