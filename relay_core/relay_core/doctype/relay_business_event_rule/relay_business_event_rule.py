import frappe
from frappe.model.document import Document
from relay_core.business_events import clear_rule_cache, validate_rule


class RelayBusinessEventRule(Document):
    def validate(self):
        if self.run_as_user != frappe.session.user and 'System Manager' not in frappe.get_roles():
            frappe.throw('Only System Managers may save rules that run as another user', frappe.PermissionError)
        validate_rule(self)

    def on_update(self):
        clear_rule_cache()

    def on_trash(self):
        clear_rule_cache()
