"""The one site switch for Relay AI features. Off by default."""
from functools import wraps

import frappe

from relay_core import features

OFF_MESSAGE = features.OFF_MESSAGES['ai']


def is_enabled() -> bool:
    return features.is_enabled('ai')


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


def document_permission(doc=None, user=None, permission_type=None):
    # None preserves DocPerm and other hooks when enabled.
    return None if is_enabled() else False


def query_condition(user=None):
    return '' if is_enabled() else '1=0'


def validate_document(doc, method=None):
    if not (frappe.flags.in_install or frappe.flags.in_migrate):
        require()
