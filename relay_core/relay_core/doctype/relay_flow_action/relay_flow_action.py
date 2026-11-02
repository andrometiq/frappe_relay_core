import frappe
from frappe.model.document import Document

class RelayFlowAction(Document):
    def validate(self):
        if bool(self.run) == bool(self.automation_run):
            raise ValueError('An action must belong to exactly one flow or automation run')


def on_doctype_update():
    # Each AI proposal looks up an earlier live or completed proposal with the same input (flows.actions.duplicate_of).
    frappe.db.add_index('Relay Flow Action', ['input_hash', 'action', 'status', 'creation'], 'relay_flow_action_duplicate')
