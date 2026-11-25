import frappe
from frappe.model.document import Document


class RelayTeamBusiness(Document):
    pass


def on_doctype_update():
    # Record scope queries read a type's groups and records of the user's teams.
    frappe.db.add_index('Relay Team Business', ['business_doctype', 'access', 'parent'], 'relay_team_business_scope')
