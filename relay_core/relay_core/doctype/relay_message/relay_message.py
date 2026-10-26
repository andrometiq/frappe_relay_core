import re

import frappe
from frappe.model.document import Document
from relay_core.automation.provenance import email_message_id


class RelayMessage(Document):
    def validate(self):
        # Provider IDs are opaque text, not HTML. Preserve Message-ID brackets
        # while rejecting markup and control characters instead of sanitizing.
        value = self.provider_id
        if value and (not isinstance(value, str) or re.search(r'[\x00-\x20\x7f]', value)
                      or (('<' in value or '>' in value) and (not email_message_id(value) or '/' in value))):
            frappe.throw('Invalid provider message ID')

    def before_insert(self):
        # Content is plain text. JSON also keeps previews independent of legacy HTML.
        if not self.get('message_data') and self.get('message_type') in (None, '', 'text'):
            self.message_data = frappe.as_json({'kind': 'text', 'text': self.get('content') or ''})
        # Atomic with the message: even death before after_commit is recoverable.
        self.automation_status = (
            'Pending' if self.direction == 'Incoming' and not self.get('legacy_source') else ''
        )


def on_doctype_update():
    # Unread counts seek to each contact's read position and read only this index.
    frappe.db.add_index('Relay Message', ['direction', 'relay_contact', 'name', 'legacy_source', 'channel'], 'relay_unread_messages')
