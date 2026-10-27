"""Site switches in Relay Settings that a System Manager turns on or off. All are off by default."""
import frappe

FIELDS = {'ai': 'enable_ai_features', 'folders': 'enable_chat_folders', 'teams': 'enable_teams'}
OFF_MESSAGES = {'ai': 'AI features are turned off', 'folders': 'Chat folders are turned off', 'teams': 'Teams are turned off'}


def is_enabled(feature: str) -> bool:
    return bool(frappe.db.get_single_value('Relay Settings', FIELDS[feature]))


def require(feature: str):
    if not is_enabled(feature):
        frappe.throw(OFF_MESSAGES[feature], frappe.PermissionError)
