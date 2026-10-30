import frappe

from relay_core import ticket_settings

TYPE_OF_OLD_STATE = {'Open': 'Open', 'In progress': 'Open', 'Resolved': 'Closed', 'Closed': 'Closed'}


def execute():
    """Give each status the type Open or Closed, and give each ticket without a status one of its old state's type.

    Safe to run again: it changes no row that already has a valid type or a status."""
    for state, status_type in TYPE_OF_OLD_STATE.items():
        if state != status_type:
            frappe.db.sql('update `tabRelay Ticket Status` set state = %s where state = %s', (status_type, state))
    ticket_settings.seed_defaults()
    if not frappe.db.has_column('Relay Ticket', 'status'):
        return
    for state, status_type in TYPE_OF_OLD_STATE.items():
        frappe.db.sql("update `tabRelay Ticket` set ticket_status = %s where status = %s "
                      "and (ticket_status is null or ticket_status = '')", (ticket_settings.status_of(status_type), state))
