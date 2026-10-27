"""Small login compatibility fixes owned by Relay Core.

Frappe 16.33 builds a complete table-count cache during login. On a development
bench with several large sites that query can remain in ``Opening tables`` long
enough for the login request to time out. Approximate table counts are only a
Desk optimization: when a count is absent, Desk performs an exact existence
check for the dependency it is rendering. Relay therefore preserves a warm
cache or seeds a minimal nonempty cache instead of scanning table metadata.
It is off unless site_config sets ``relay_bounded_login_cache``.
"""

import frappe


_original_table_count_builder = frappe.cache_manager.build_table_count_cache


def _bounded_table_counts():
	counts = frappe.cache.get_value("information_schema:counts")
	if not isinstance(counts, dict) or not counts:
		# A truthy cache prevents the eager global metadata query. Missing
		# dependencies still use Frappe's exact per-DocType fallback.
		counts = {"DocType": 1}
		frappe.cache.set_value("information_schema:counts", counts)
	return counts


def _relay_table_count_builder(*args, **kwargs):
	if (
		frappe.db.db_type == "mariadb"
		and getattr(frappe.flags, "relay_bounded_login_cache", False)
	):
		return _bounded_table_counts()
	return _original_table_count_builder(*args, **kwargs)


def use_site_scoped_boot_cache(login_manager):
	"""Keep Frappe's login boot cache bounded when site_config sets `relay_bounded_login_cache`."""
	if not frappe.conf.get("relay_bounded_login_cache") or frappe.db.db_type != "mariadb":
		return
	frappe.flags.relay_bounded_login_cache = True
	frappe.cache_manager.build_table_count_cache = _relay_table_count_builder
