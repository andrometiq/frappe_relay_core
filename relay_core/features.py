"""Site switches in Relay Settings that a System Manager turns on or off. All are off by default."""
import frappe

FIELDS = {'ai': 'enable_ai_features', 'folders': 'enable_chat_folders', 'teams': 'enable_teams', 'flows': 'enable_flows'}
OFF_MESSAGES = {'ai': 'AI features are turned off', 'folders': 'Chat folders are turned off', 'teams': 'Teams are turned off',
                'flows': 'Flows are turned off'}


def is_enabled(feature: str) -> bool:
    try:
        return bool(frappe.db.get_single_value('Relay Settings', FIELDS[feature]))
    except frappe.ValidationError:
        # Code runs before the migrate that adds a new switch; a switch the site does not have yet is off.
        frappe.clear_last_message()  # The missing-field text must not reach the response.
        return False


def require(feature: str):
    if not is_enabled(feature):
        frappe.throw(OFF_MESSAGES[feature], frappe.PermissionError)
