"""One idempotent, assigned human handoff for automation failures."""
import frappe
from relay_core.automation.service import internal_save, lock_contact
from relay_core.tickets import ensure_episode, episode_owner_allowed as eligible


def handoff(run, skill, reason):
    message = frappe.get_doc('Relay Message', run.message)
    contact = lock_contact(message.relay_contact)
    original = frappe.session.user
    try:
        # A service write may route an authorization failure, but never disclose its data.
        frappe.set_user('Administrator')
        fallback = frappe.get_single('Relay Settings').get('ai_handoff_owner')
        owner = next((user for user in (skill.get('handoff_owner'), fallback) if eligible(user, message)), None)
        if not owner:
            raise ValueError('Configure an accessible handoff owner or fallback owner')
        ticket = ensure_episode(message, owner=owner, skill=skill, run=run,
                                subject='Conversation needs a person', reason=reason)
        if not contact.automation_paused:
            contact.automation_paused = 1
            contact.automation_generation = int(contact.automation_generation or 0) + 1
            contact.save(ignore_permissions=True)
        run.ticket, run.status, run.reason = ticket.name, 'Handoff', reason[:500]
        internal_save(run)
        return ticket.name
    finally:
        frappe.set_user(original)
