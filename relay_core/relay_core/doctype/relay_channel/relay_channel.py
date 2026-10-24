from frappe.model.document import Document


class RelayChannel(Document):
    def before_naming(self):
        if not self.title:
            self.title = f"{self.channel} {self.account}"[:120]
