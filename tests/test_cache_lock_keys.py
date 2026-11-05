"""Site-scoped locks survive frappe.clear_cache(), which migrate and site setup run while jobs hold them."""
import fnmatch
import re
import unittest
from pathlib import Path

from relay_core import hooks

LOCKED_KEY = re.compile(r"make_key\('(relay-[a-z-]+:?)'")


def site_scoped_lock_prefixes():
    prefixes = set()
    for path in Path('relay_core').rglob('*.py'):
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            if 'cache.lock' in ' '.join(lines[index:index + 2]):
                prefixes.update(LOCKED_KEY.findall(line))
    return prefixes


def survives_clear_cache(key):
    """Frappe keeps the site keys that match a persistent_cache_keys pattern and deletes the rest."""
    return any(fnmatch.fnmatchcase(key, pattern) for pattern in hooks.persistent_cache_keys)


class CacheLockKeyTests(unittest.TestCase):
    def test_every_site_scoped_lock_key_is_persistent(self):
        prefixes = site_scoped_lock_prefixes()
        self.assertTrue({'relay-ai-knowledge:', 'relay-ai-event:', 'relay-enrolment'} <= prefixes, prefixes)
        for prefix in prefixes:
            key = prefix + 'RELAY-AIKS-0000000007' if prefix.endswith(':') else prefix
            with self.subTest(key=key):
                self.assertTrue(survives_clear_cache(key))

    def test_bulk_refresh_marks_are_persistent_and_other_keys_are_not(self):
        from relay_core.bulk_updates import DIRTY
        self.assertTrue(survives_clear_cache(DIRTY))
        self.assertFalse(survives_clear_cache('relay-whatsapp-template-sync-requested:acct'))


if __name__ == '__main__':
    unittest.main()
