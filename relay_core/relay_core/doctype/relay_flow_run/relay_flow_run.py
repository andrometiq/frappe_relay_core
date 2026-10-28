import frappe
from relay_core.automation.documents import InternalRecord

class RelayFlowRun(InternalRecord):
    pass


def on_doctype_update():
    # Every incoming WhatsApp message looks up the active run of its conversation.
    frappe.db.add_index('Relay Flow Run', ['conversation_key', 'status'], 'relay_flow_run_conversation')
    frappe.db.add_index('Relay Flow Run', ['flow', 'name'], 'relay_flow_run_flow')
