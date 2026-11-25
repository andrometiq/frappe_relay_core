import frappe
from relay_core.automation.documents import InternalRecord


class RelayMessageAction(InternalRecord):
    def before_insert(self):
        # Every send is journaled here before it reaches a provider.
        from relay_core.permissions import is_read_only
        if is_read_only():
            frappe.throw('Your Relay role can only read', frappe.PermissionError)

    def on_update(self):
        from relay_core.ticket_notifications import complete
        complete(self)
        from relay_core.business_events import complete as complete_event
        complete_event(self)
        from relay_core.ai.service import complete as complete_ai
        complete_ai(self)
        # A private invalidation only: the recipient must refetch with permissions.
        frappe.publish_realtime('relay_changed', {'kind': 'message_actions'},
                                user=self.owner, after_commit=True)
