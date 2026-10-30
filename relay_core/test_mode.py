"""Relay Settings test mode: outbound calls may reach only this machine."""
import ipaddress
from urllib.parse import urlsplit
import frappe

LOCAL_SUFFIXES = ('.localhost', '.test')


class TestModeBlocked(frappe.ValidationError):
    """Refused before any network call, so nothing was sent."""


def is_enabled() -> bool:
    db = getattr(getattr(frappe, 'local', None), 'db', None)
    if db is None:  # isolated contract tests run without a site
        return False
    return db.get_single_value('Relay Settings', 'test_mode') in (1, '1', True)


def is_local_url(url: str) -> bool:
    host = (urlsplit(url).hostname or '') if isinstance(url, str) else ''
    if host == 'localhost' or host.endswith(LOCAL_SUFFIXES):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def ensure_allowed(url: str, *, allowed: bool = False) -> None:
    """Refuse a non-loopback URL while test mode is on, unless the caller's record opted in."""
    if allowed or not is_enabled() or is_local_url(url):
        return
    host = urlsplit(url).hostname if isinstance(url, str) else None
    frappe.throw(f'Test mode is on: {host or "this address"} is outside this server. '
        'Only local simulator addresses are allowed.', TestModeBlocked)


def ensure_email_allowed() -> None:
    if is_enabled():
        frappe.throw('Test mode is on: email is not sent.', TestModeBlocked)
