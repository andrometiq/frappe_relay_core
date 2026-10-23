"""One idempotent, assigned human handoff for automation failures."""
import hashlib
import json
import frappe
from relay_core.ai.tools import as_user
from relay_core.automation.service import internal_save, lock_contact


def eligible(user, message):
    try:
        with as_user(user):
            from relay_core.permissions import require_access, readable_contact
            require_access()
            message.check_permission('read')
            readable_contact(message.relay_contact)
        return True
    except Exception:
        return False


def handoff(run, skill, reason):
    message = frappe.get_doc('Relay Message', run.message)
    contact = lock_contact(message.relay_contact)
    from relay_core.business_access import reference
    business = reference(message) or (None, None)
    key = hashlib.sha256(json.dumps(['handoff', message.get('conversation_key') or message.name,
        business, run.generation], separators=(',', ':')).encode()).hexdigest()
    existing = frappe.db.get_value('Relay Ticket', {'source_action_key': key}, 'name')
    original = frappe.session.user
    try:
        # A service write may route an authorization failure, but never disclose its data.
        frappe.set_user('Administrator')
        fallback = frappe.get_single('Relay Settings').get('ai_handoff_owner')
        owner = next((user for user in (skill.get('handoff_owner'), fallback) if eligible(user, message)), None)
        if not owner:
            raise ValueError('Configure an accessible handoff owner or fallback owner')
        if existing:
            ticket = frappe.get_doc('Relay Ticket', existing)
            ticket.assigned_to = owner
            ticket.save(ignore_permissions=True)
        else:
            ticket = frappe.get_doc({'doctype': 'Relay Ticket', 'subject': 'Conversation needs a person',
                'brief': reason[:500], 'category': 'Support', 'status': 'Open', 'assigned_to': owner,
                'business_doctype': business[0], 'business_name': business[1],
                'handoff_reason': reason[:500], 'source_run': run.name, 'source_action_key': key,
                'messages': [{'message': message.name}]}).insert(ignore_permissions=True)
        if not contact.automation_paused:
            contact.automation_paused = 1
            contact.automation_generation = int(contact.automation_generation or 0) + 1
            contact.save(ignore_permissions=True)
        run.ticket, run.status, run.reason = ticket.name, 'Handoff', reason[:500]
        internal_save(run)
        return ticket.name
    finally:
        frappe.set_user(original)
