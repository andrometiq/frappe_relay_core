from frappe.model.document import Document


class RelayMessage(Document):
    def before_insert(self):
        # Atomic with the message: even death before after_commit is recoverable.
        self.automation_status = (
            'Pending' if self.direction == 'Incoming' and not self.get('legacy_source') else ''
        )
