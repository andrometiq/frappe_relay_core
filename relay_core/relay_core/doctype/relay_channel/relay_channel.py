import frappe
from frappe.model.document import Document


class RelayChannel(Document):
    def before_naming(self):
        if not self.title:
            self.title = (self.label or f"{self.channel} {self.account}")[:120]

    def validate(self):
        from relay_core.automation.channel import FIELDS, steps, validate
        previous = self.get_doc_before_save()
        if not previous or steps(self) != steps(previous) or any(self.get(key) != previous.get(key) for key in FIELDS):
            validate(self)
        if self.hub_channel and frappe.db.exists('Relay Channel', {
                'channel': self.channel, 'hub_channel': self.hub_channel, 'name': ['!=', self.name]}):
            frappe.throw(f'Another {self.channel} channel already has Hub channel {self.hub_channel}',
                         frappe.DuplicateEntryError)

    def on_update(self):
        if self.is_default:
            # One default per channel type and Hub site.
            for name in frappe.get_all('Relay Channel', pluck='name', filters={
                    'channel': self.channel, 'account': self.account, 'is_default': 1, 'name': ['!=', self.name]}):
                frappe.db.set_value('Relay Channel', name, 'is_default', 0)


def on_doctype_update():
    frappe.db.add_unique('Relay Channel', ['channel', 'hub_channel'], 'relay_channel_hub_key')
