"""Site switches in Relay Settings that a System Manager turns on or off. Only auto seen is on by default."""
import frappe

FIELDS = {'ai': 'enable_ai_features', 'folders': 'enable_chat_folders', 'teams': 'enable_teams', 'flows': 'enable_flows',
          'auto_seen': 'send_whatsapp_read_receipts'}
OFF_MESSAGES = {'ai': 'AI features are turned off', 'folders': 'Chat folders are turned off', 'teams': 'Teams are turned off',
                'flows': 'Flows are turned off', 'auto_seen': 'Auto seen is turned off'}


def is_enabled(feature: str) -> bool:
    try:
        return bool(frappe.db.get_single_value('Relay Settings', FIELDS[feature]))
    except frappe.ValidationError:
        # Code runs before the migrate that adds a new switch; a switch the site does not have yet is off.
        frappe.clear_last_message()  # The missing-field text must not reach the response.
        return False


def automation_test_contacts() -> set[str]:
    """Relay Contacts that automation is limited to; empty means every contact."""
    try:
        value = frappe.db.get_single_value('Relay Settings', 'automation_test_contacts')
    except frappe.ValidationError:
        frappe.clear_last_message()
        return set()
    return {line.strip() for line in (value or '').splitlines() if line.strip()}


def is_automation_allowed(contact: str | None) -> bool:
    contacts = automation_test_contacts()
    return not contacts or contact in contacts


def require(feature: str):
    if not is_enabled(feature):
        frappe.throw(OFF_MESSAGES[feature], frappe.PermissionError)
