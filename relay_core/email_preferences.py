"""Per-user signatures and explicitly enabled, loop-safe automatic replies."""
import hashlib
import frappe
from relay_core.permissions import require_access


def validate_preference(doc):
    require_access()
    if doc.user!=frappe.session.user or doc.owner!=frappe.session.user:frappe.throw('Email preferences belong to their user',frappe.PermissionError)
    if not isinstance(doc.signature or '',str) or len(doc.signature or '')>2000:frappe.throw('Signature exceeds 2000 characters')


def validate_rule(doc):
    require_access(configure=True)
    from relay_core.automation.service import check_actor
    check_actor(doc)
    if frappe.db.get_value('Relay Channel',doc.channel,'channel')!='Email':frappe.throw('Choose an email channel')
    if not isinstance(doc.subject,str) or not doc.subject.strip() or len(doc.subject)>140 or any(c in doc.subject for c in '\r\n'):frappe.throw('Provide a single-line reply subject')
    if not isinstance(doc.body,str) or not doc.body.strip() or len(doc.body)>4000:frappe.throw('Reply body must contain 1–4000 characters')


@frappe.whitelist(methods=['GET'])
def read():
    require_access()
    return {'signature':frappe.db.get_value('Relay Email Preference',{'user':frappe.session.user},'signature') or ''}


@frappe.whitelist(methods=['POST'])
def save(signature):
    require_access()
    name=frappe.db.get_value('Relay Email Preference',{'user':frappe.session.user},'name')
    doc=frappe.get_doc('Relay Email Preference',name) if name else frappe.new_doc('Relay Email Preference')
    doc.user=frappe.session.user;doc.signature=signature;doc.save()
    return {'saved':True}


def on_message(doc,method=None):
    if not doc.get('legacy_source') and doc.direction=='Incoming' and frappe.db.exists('Relay Email Rule',{'channel':doc.channel,'enabled':1}):
        from relay_core.flows.service import claims
        if claims(doc):return
        frappe.enqueue('relay_core.email_preferences.auto_reply',message=doc.name,queue='short',timeout=60,enqueue_after_commit=True)


def auto_reply(message):
    original=frappe.session.user
    try:
        source=frappe.get_doc('Relay Message',message)
        name=frappe.db.get_value('Relay Email Rule',{'channel':source.channel,'enabled':1},'name')
        if not name or source.get('legacy_source') or source.direction!='Incoming':return
        rule=frappe.get_doc('Relay Email Rule',name)
        from relay_core.automation.service import check_actor
        from relay_core import messaging,email
        check_actor(rule);frappe.set_user(rule.execution_user)
        source,channel,context=messaging.readable_source(message)
        if channel.channel!='Email' or context.get('auto_submitted'):return
        # Fixed daily recipient key means event replay or an email loop cannot
        # produce repeated automatic replies. The Hub journal owns ambiguity.
        identity=source.channel+':'+source.sender_endpoint.lower()+':'+frappe.utils.nowdate()
        key='email_auto_'+hashlib.sha256(identity.encode()).hexdigest()
        return email.send([source.sender_endpoint],rule.subject,rule.body,request_key=key,auto_submitted=1,message=source.name)
    except Exception:
        frappe.log_error(title='Relay automatic email reply requires review',message='An automatic reply could not be confirmed. Review the Hub delivery journal before retrying.')
    finally:frappe.set_user(original)
