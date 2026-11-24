import frappe
from frappe.model.document import Document


class RelayTeamMember(Document):
    pass


def on_doctype_update():
    # Record scope queries start from the teams of one user.
    frappe.db.add_index('Relay Team Member', ['user', 'parent'], 'relay_team_member_user')
