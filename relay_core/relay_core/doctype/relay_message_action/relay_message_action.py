import frappe
from relay_core.automation.documents import InternalRecord


class RelayMessageAction(InternalRecord):
    def on_update(self):
        # A private invalidation only: the recipient must refetch with permissions.
        frappe.publish_realtime('relay_changed', {'kind': 'message_actions'},
                                user=self.owner, after_commit=True)
