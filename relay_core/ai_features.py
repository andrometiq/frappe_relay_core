"""The one site switch for Relay AI features. Off by default."""
from functools import wraps

import frappe

OFF_MESSAGE = 'AI features are turned off'


def is_enabled() -> bool:
    return bool(frappe.db.get_single_value('Relay Settings', 'enable_ai_features'))


def require():
    if not is_enabled():
        frappe.throw(OFF_MESSAGE, frappe.PermissionError)


def required(function):
    """Deny a whitelisted AI API while the switch is off."""
    @wraps(function)
    def guarded(*args, **kwargs):
        require()
        return function(*args, **kwargs)
    return guarded


def when_enabled(function):
    """Return at once from AI background work while the switch is off."""
    @wraps(function)
    def guarded(*args, **kwargs):
        if is_enabled():
            return function(*args, **kwargs)
    return guarded
