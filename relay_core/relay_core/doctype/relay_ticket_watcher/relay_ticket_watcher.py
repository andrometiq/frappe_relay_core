import frappe
from frappe.model.document import Document


class RelayTicketWatcher(Document):
    pass


def on_doctype_update():
    # Ticket scope and the Mentions view find the tickets that name one user.
    frappe.db.add_index('Relay Ticket Watcher', ['user', 'parent'], 'relay_ticket_watcher_user')
