from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from relay_core import login


class LoginCompatibilityTests(TestCase):
	def test_mariadb_login_does_not_scan_table_metadata(self):
		database = SimpleNamespace(db_type="mariadb")
		cache = SimpleNamespace(get_value=Mock(return_value=None), set_value=Mock())
		cache_manager = SimpleNamespace(
			build_table_count_cache=Mock(),
		)
		flags = SimpleNamespace(relay_bounded_login_cache=False)

		with (
			patch.object(login.frappe, "conf", {"relay_bounded_login_cache": 1}),
			patch.object(login.frappe, "db", database),
			patch.object(login.frappe, "cache", cache),
			patch.object(login.frappe, "cache_manager", cache_manager),
			patch.object(login.frappe, "flags", flags),
		):
			login.use_site_scoped_boot_cache(SimpleNamespace())
			cache_manager.build_table_count_cache()

		self.assertTrue(flags.relay_bounded_login_cache)
		cache.set_value.assert_called_once_with(
			"information_schema:counts",
			{"DocType": 1},
		)

	def test_warm_table_count_cache_is_preserved(self):
		counts = {"Relay Message": 12}
		cache = SimpleNamespace(
			get_value=Mock(return_value=counts),
			set_value=Mock(),
		)

		with patch.object(login.frappe, "cache", cache):
			self.assertIs(login._bounded_table_counts(), counts)

		cache.set_value.assert_not_called()

	def test_non_mariadb_login_keeps_frappe_boot_cache(self):
		cache_manager = SimpleNamespace(build_table_count_cache=Mock())
		flags = SimpleNamespace(relay_bounded_login_cache=False)

		with (
			patch.object(login.frappe, "conf", {"relay_bounded_login_cache": 1}),
			patch.object(login.frappe, "db", SimpleNamespace(db_type="postgres")),
			patch.object(login.frappe, "cache_manager", cache_manager),
			patch.object(login.frappe, "flags", flags),
		):
			login.use_site_scoped_boot_cache(SimpleNamespace())

		self.assertFalse(flags.relay_bounded_login_cache)
		self.assertIsInstance(cache_manager.build_table_count_cache, Mock)

	def test_login_is_untouched_without_the_site_config_flag(self):
		cache_manager = SimpleNamespace(build_table_count_cache=Mock())
		original = cache_manager.build_table_count_cache
		flags = SimpleNamespace(relay_bounded_login_cache=False)

		with (
			patch.object(login.frappe, "conf", {}),
			patch.object(login.frappe, "db", SimpleNamespace(db_type="mariadb")),
			patch.object(login.frappe, "cache_manager", cache_manager),
			patch.object(login.frappe, "flags", flags),
		):
			login.use_site_scoped_boot_cache(SimpleNamespace())

		self.assertFalse(flags.relay_bounded_login_cache)
		self.assertIs(cache_manager.build_table_count_cache, original)
