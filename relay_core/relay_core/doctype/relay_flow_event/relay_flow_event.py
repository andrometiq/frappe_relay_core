import frappe
from relay_core.automation.documents import InternalRecord

class RelayFlowEvent(InternalRecord):
    pass


def on_doctype_update():
    # Ordered per-conversation processing and the recovery pass read pending events by these keys.
    frappe.db.add_index('Relay Flow Event', ['conversation_key', 'status'], 'relay_flow_event_conversation')
    frappe.db.add_index('Relay Flow Event', ['status', 'next_attempt'], 'relay_flow_event_pending')
