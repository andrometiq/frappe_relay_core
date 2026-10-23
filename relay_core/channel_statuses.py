"""Apply durable channel receipts without making a provider or Hub request."""
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
            if action.status == 'Submitted':
                continue
            previous = messaging.object_value(action.result or {}).get('_relay_status_id', 0)
            if type(previous) is int and previous >= row['id']:
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
                if medium=='Email':
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
