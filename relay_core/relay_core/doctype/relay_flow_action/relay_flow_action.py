from frappe.model.document import Document

class RelayFlowAction(Document):
    def validate(self):
        if bool(self.run) == bool(self.automation_run):
            raise ValueError('An action must belong to exactly one flow or automation run')
