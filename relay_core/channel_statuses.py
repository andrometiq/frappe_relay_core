"""Apply durable channel receipts without making a provider or Hub request."""
import json
import frappe
from relay_core import messaging
from relay_core.settings import value as connection_value


def project_batch(event, rows):
    if event.account != connection_value('relay_hub_account'):
        raise ValueError('Status batch belongs to another account')
    original = frappe.session.user
    unresolved = False
    try:
        for row in rows:
            name = frappe.db.get_value('Relay Message Action', {'request_key':row['request_key']}, 'name')
            if not name:
                # Hub is also usable independently of Core; not every send has a Core action.
                continue
            frappe.db.get_value('Relay Message Action', name, 'name', for_update=True)
            action = frappe.get_doc('Relay Message Action', name)
            evidence = row['operation'] == 'email.send' and row['state'] in ('delayed', 'bounced', 'delivered')
            if action.status == 'Submitted' and not evidence:
                continue
            previous = messaging.object_value(action.result or {}).get('_relay_status_id', 0)
            if not evidence and type(previous) is int and previous >= row['id']:
                continue
            if not frappe.db.get_value('User',action.owner,'enabled'):
                unresolved = True
                continue
            frappe.set_user(action.owner)
            try:
                action.check_permission('read')
                source,channel,context=messaging.action_target(action)
                medium={'telegram.message':'Telegram','email.send':'Email','whatsapp.execute':'WhatsApp'}[row['operation']]
                if channel.channel!=medium or channel.account!=event.account:
                    raise ValueError('Status receipt channel mismatch')
                if medium=='Email' and action.operation != 'business_prompt':
                    if evidence:
                        if not apply_email_evidence(action, row):
                            unresolved = True
                    else:
                        apply_email(action,row)
                    continue
                content=messaging.object_value(action.payload).get('content')
                if not isinstance(content,dict):
                    unresolved=True
                    continue
                receipt=dict(row['receipt']) if row['state']=='submitted' else {'delivery':{'state':row['state']}}
                if medium == 'WhatsApp' and row['state'] == 'submitted' and not receipt.get('messages') and receipt.get('message_id'):
                    receipt['messages'] = [{'id': str(receipt['message_id'])}]
                receipt['_relay_status_id']=row['id']
                messaging.finish(action,source,channel,context,content,receipt,commit=False)
            except (frappe.PermissionError,frappe.DoesNotExistError):
                unresolved=True
            finally:
                frappe.set_user(original)
    finally:
        frappe.set_user(original)
    frappe.db.set_value('Relay Hub Event',event.name,'projection_status','Uncategorized' if unresolved else 'Projected')


def apply_email(action,row):
    from relay_core import email
    payload=messaging.object_value(action.payload)
    if action.operation!='email' or not isinstance(payload.get('email_values'),dict):
        raise ValueError('Email receipt does not match an email action')
    receipt=dict(row['receipt']) if row['state']=='submitted' else {'delivery':{'state':row['state']}}
    receipt['_relay_status_id']=row['id']
    email.finish(action,receipt,commit=False)


def apply_email_evidence(action, row):
    from relay_core.email import recipients
    from relay_core.automation.service import internal_save
    from relay_core.realtime import changed
    payload = messaging.object_value(action.payload)
    values = payload.get('email_values')
    if action.operation != 'email' or not isinstance(values, dict):
        raise ValueError('Email evidence does not match an email action')
    receipt = row['receipt']
    envelope = {address for field in ('to', 'cc', 'bcc') for address in recipients(values.get(field))}
    recipient = receipt['recipient']
    if recipient not in envelope:
        raise ValueError('Email evidence recipient mismatch')
    if not action.outbound_message:
        return False  # A DSN can overtake the submission callback; recovery will replay it.
    message = frappe.get_doc('Relay Message', action.outbound_message)
    from relay_core.automation.provenance import context_of
    if context_of(message).get('message_id') != receipt['message_id']:
        raise ValueError('Email evidence message mismatch')
    result = messaging.object_value(action.result or {})
    evidence = result.setdefault('_relay_email_receipts', {})
    rank = {'delayed': 1, 'bounced': 2, 'delivered': 3}
    previous = evidence.get(recipient, {})
    if rank.get(previous.get('delivery_status'), 0) >= rank[receipt['delivery_status']]:
        return True
    evidence[recipient] = dict(receipt, status_id=row['id'])
    states = {address: evidence.get(address, {}).get('delivery_status') for address in envelope}
    status = ('Failed' if 'bounced' in states.values() else
              'Delivered' if all(state == 'delivered' for state in states.values()) else 'Sent')
    frappe.db.set_value('Relay Message', message.name, 'status', status, update_modified=False)
    action.result = json.dumps(result)
    internal_save(action)
    changed(message)
    return True
