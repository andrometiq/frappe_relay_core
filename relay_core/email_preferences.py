"""Per-user signatures and explicitly enabled, loop-safe automatic replies."""
import hashlib
from relay_core.automation.provenance import context_of, email_message_id
import frappe
from relay_core.automation.queue import QUEUE, after_message_commit
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


@after_message_commit
def on_message(doc,method=None):
    if not doc.get('legacy_source') and doc.direction=='Incoming' and frappe.db.exists('Relay Email Rule',{'channel':doc.channel,'enabled':1}):
        if not automatic_allowed(context_of(doc)) or skill_claims(doc):return
        from relay_core.flows.service import claims
        if claims(doc):return
        frappe.enqueue('relay_core.email_preferences.auto_reply',message=doc.name,queue=QUEUE,timeout=60,enqueue_after_commit=True)


def auto_reply(message):
    original=frappe.session.user
    try:
        frappe.db.get_value('Relay Message',message,'name',for_update=True)
        source=frappe.get_doc('Relay Message',message)
        names=frappe.get_all('Relay Email Rule',filters={'channel':source.channel,'enabled':1},pluck='name',limit_page_length=2)
        if len(names)!=1 or source.get('legacy_source') or source.direction!='Incoming':return
        if skill_claims(source):return
        rule=frappe.get_doc('Relay Email Rule',names[0])
        from relay_core.automation.service import check_actor
        from relay_core import messaging,email
        check_actor(rule);frappe.set_user(rule.execution_user)
        source,channel,context=messaging.readable_source(message)
        if channel.channel!='Email' or not automatic_allowed(context):return
        # Fixed daily recipient key means event replay or an email loop cannot
        # produce repeated automatic replies. The Hub journal owns ambiguity.
        identity=':'.join((source.channel,source.sender_endpoint.lower(),source.business_doctype or '',source.business_name or '',frappe.utils.nowdate()))
        key='email_auto_'+hashlib.sha256(identity.encode()).hexdigest()
        return email.send([source.sender_endpoint],rule.subject,rule.body,request_key=key,auto_submitted=1,message=source.name)
    except Exception:
        frappe.log_error(title='Relay automatic email reply requires review',message='An automatic reply could not be confirmed. Review the Hub delivery journal before retrying.')
    finally:frappe.set_user(original)


def automatic_allowed(context):
    """Hub collapses Auto-Submitted, bulk/list mail and reports into one flag."""
    if context.get('provider') != 'Email':
        return True
    return (not context.get('auto_submitted')
            and context.get('authentication', {}).get('status') == 'pass'
            and bool(email_message_id(context.get('message_id'))))


def skill_claims(message):
    from relay_core.ai.service import skill_for
    from relay_core.automation.contracts import event_key
    if frappe.db.get_value('Relay Automation Run', {'event_key': event_key(message.name)}, 'name', for_update=True):
        return True
    return bool(frappe.conf.get('relay_automation_enabled') and skill_for(message))


def automatic_reply_exists(message):
    import json
    # The source lock serializes AI admission and fixed-rule journal creation.
    rows = frappe.db.get_values('Relay Message Action',
        {'source_message': message.name, 'operation': 'email'}, ['payload'], as_dict=True, for_update=True)
    return any(str(json.loads(row.payload).get('email_values', {}).get('auto_submitted', 0)) == '1'
               for row in rows)
