"""Site-scoped Redis locks for Relay Core.

Use `lock()` for every Relay cache lock. The key carries the site prefix, so sites on one bench do not block each other,
and it starts with PREFIX, which hooks.persistent_cache_keys keeps when frappe.clear_cache() runs during a held lock.
Background job ids need no prefix: frappe.enqueue already scopes job_id to the site.
"""
import frappe

PREFIX = 'relay-lock:'


def key(name: str) -> bytes | str:
    return frappe.cache.make_key(PREFIX + name)


def lock(name: str, timeout: float, blocking_timeout: float | None = None):
    """A Redis lock named `name` for this site only."""
    return frappe.cache.lock(key(name), timeout=timeout, blocking_timeout=blocking_timeout)
