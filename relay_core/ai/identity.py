"""Before any capability read, the verified sender must belong to the business record."""
import hashlib
import frappe
from relay_core.ai.tools import PrivacyDenied


def linked_contact(scope: dict, business: tuple[str, str]) -> bool:
    """The verified endpoint is bound to the scope's Relay Contact, and its Contact links the business."""
    from relay_core.business_access import candidates
    key = hashlib.sha256((scope['channel'] + ':' + scope['endpoint']).encode()).hexdigest()
    binding = frappe.db.get_value('Relay Contact Endpoint', {'endpoint_key': key}, ['relay_contact', 'verified'], as_dict=True)
    return bool(binding and binding.verified and binding.relay_contact == scope['contact']
                and tuple(business) in candidates(scope['contact']))


def validate(manifest: dict, scope: dict, business: tuple[str, str]) -> None:
    """Core and the pack's own validator must both return True; anything else denies the read."""
    checks = [linked_contact, *([frappe.get_attr(manifest['identity'])] if manifest.get('identity') else [])]
    for check in checks:
        try:
            allowed = check(scope, business)
        except Exception:
            allowed = False
        if allowed is not True:
            raise PrivacyDenied('The sender is not linked to this business record')
