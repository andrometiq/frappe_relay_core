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
        # Atomic with the message: even death before after_commit is recoverable.
        self.automation_status = (
            'Pending' if self.direction == 'Incoming' and not self.get('legacy_source') else ''
        )
