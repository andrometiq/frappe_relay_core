from frappe.model.document import Document


class RelayTeam(Document):
    def validate(self):
        from relay_core.teams import validate_team
        validate_team(self)
