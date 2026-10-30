"""Explicit operator actions attached to published saved replies.

Installed handlers must enforce business permissions and be replay safe using the
provided idempotency_key, including a crash before the local receipt is stored.
No browser-supplied handler path or arguments are accepted.
"""
import hashlib
import json
import frappe
from relay_core.business_access import document_name
from relay_core.permissions import require_access
from relay_core.flows.actions import definitions
from relay_core.flows.action_contracts import inputs, resolve


def configured_action(reply):
    definition=definitions('relay_saved_reply_actions').get(reply.get('action_key'))
    if not definition:frappe.throw('Choose an installed, replay-safe saved reply action')
    try:
        raw=json.loads(reply.get('action_arguments') or '{}')
        values=inputs(raw,definition['parameters'],{})
    except (ValueError,TypeError) as exc:frappe.throw(str(exc))
    return definition,values


@frappe.whitelist(methods=['GET'])
def catalog():
    require_access(configure=True)
    return [{'key':key,'label':row.get('label') or key,'parameters':row['parameters']}
            for key,row in sorted(definitions('relay_saved_reply_actions').items())]


@frappe.whitelist(methods=['POST'])
def execute(message, reply, request_key):
    document_name(reply)
    require_access()
    if not isinstance(request_key,str) or not 16<=len(request_key)<=140:
        frappe.throw('A stable action request key is required')
    from relay_core.messaging import readable_source
    source,channel,_=readable_source(message)
    doc=frappe.get_doc('Relay Canned Reply',reply)
    if not doc.published or doc.channel!=channel.channel or channel.channel not in ('Telegram','WhatsApp'):
        frappe.throw('This saved reply is not available for the conversation',frappe.PermissionError)
    definition,values=configured_action(doc)
    actor=frappe.session.user
    key=hashlib.sha256(json.dumps([actor,request_key]).encode()).hexdigest()
    fingerprint=hashlib.sha256(json.dumps([source.name,source.relay_contact,doc.name,definition['method'],values],sort_keys=True).encode()).hexdigest()
    with frappe.cache.lock('relay-saved-action-'+key,timeout=300,blocking_timeout=3):
        previous=frappe.db.get_value('Relay Saved Reply Action',{'request_key':key},['name','input_hash','result'],as_dict=True)
        if previous:
            if previous.input_hash!=fingerprint:frappe.throw('This request belongs to a different saved reply action')
            return {'receipt':previous.name,'result':json.loads(previous.result),'replayed':True}
        result=frappe.get_attr(definition['method'])(action_input=values,relay_contact=source.relay_contact,
            source_message=source.name,idempotency_key=key)
        result=resolve(result,{},references=False)
        encoded=json.dumps(result,allow_nan=False)
        if len(encoded)>20000:frappe.throw('Action result exceeds 20,000 characters')
        from relay_core.automation.service import internal_save
        receipt=frappe.get_doc({'doctype':'Relay Saved Reply Action','request_key':key,'reply':doc.name,
            'source_message':source.name,'actor':actor,'input_hash':fingerprint,'result':encoded})
        internal_save(receipt,new=True);frappe.db.commit()
        return {'receipt':receipt.name,'result':result,'replayed':False}


def add_note(*, action_input, relay_contact, source_message, idempotency_key):
    from relay_core.collaboration import add
    note=add(relay_contact,action_input['note'],idempotency_key,messages=[source_message])
    return {'comment':note['name']}


NOTE_ACTION = {
    'label':'Add internal note',
    'method':'relay_core.saved_reply_actions.add_note',
    'replay_safe':True,
    'parameters':{'type':'object','properties':{'note':{'type':'string','minLength':1,'maxLength':4000}},'required':['note']},
}
