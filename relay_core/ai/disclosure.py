"""One assistant notice per ticket, before its first AI reply."""
import frappe

DISCLOSURE = "This is Relay's assistant. Reply 'person' to reach our team."


def due(ticket) -> bool:
    return not ticket.ai_disclosed


def send(run, message) -> dict:
    """Journal the notice and set `ai_disclosed` in one commit; a retry reuses the request key."""
    from relay_core.ai.language import message_notice
    from relay_core.ai.service import send_reply
    frappe.db.savepoint('relay_disclosure')
    frappe.db.set_value('Relay Ticket', run.ticket, 'ai_disclosed', 1, update_modified=False)
    try:
        return send_reply(message, message_notice('disclosure', message, DISCLOSURE), slot='disclosure')
    except Exception:
        frappe.db.rollback(save_point='relay_disclosure')  # The flag never commits without its journal row.
        raise
