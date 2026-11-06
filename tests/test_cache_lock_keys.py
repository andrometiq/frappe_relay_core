"""Relay locks are site-scoped and survive frappe.clear_cache(), which migrate and site setup run while jobs hold them."""
import ast
import fnmatch
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe
import redis
import redis.lock
from frappe.utils.redis_wrapper import RedisWrapper

from relay_core import hooks, locks

SOURCE = Path(__file__).resolve().parent.parent / 'relay_core'


class MemoryRedis(RedisWrapper):
    """Frappe's own RedisWrapper and redis-py's Lock over an in-memory store."""

    def __init__(self):
        super().__init__()
        self.store = {}

    def set(self, name, value, nx=False, px=None, **kwargs):
        if nx and name in self.store:
            return None
        self.store[name] = value
        return True

    def get(self, name):
        return self.store.get(name)

    def keys(self, pattern='*'):
        pattern = pattern.decode() if isinstance(pattern, bytes) else pattern
        return [key for key in self.store if fnmatch.fnmatchcase(key.decode(), pattern)]

    def unlink(self, *names):
        for name in names:
            self.store.pop(name, None)


def release_script(lock, keys, args, client):
    """redis-py's Lua release: delete the key only while it still holds this lock's token."""
    if client.store.get(keys[0]) != args[0]:
        return 0
    del client.store[keys[0]]
    return 1


def clear_site_cache(cache):
    """The key deletion of frappe.clear_cache(): every site key except the persistent_cache_keys matches."""
    keys = set(cache.get_keys(''))
    for pattern in hooks.persistent_cache_keys:
        keys.difference_update(cache.get_keys(pattern))
    cache.delete_value(list(keys), make_keys=False)


class SiteLockTests(unittest.TestCase):
    def setUp(self):
        self.cache = MemoryRedis()
        self.local = patch.object(frappe, 'local', frappe._dict(conf=frappe._dict(db_name='site_a'), cache={}))
        self.local.start()
        self.addCleanup(self.local.stop)
        for patcher in (patch.object(frappe, 'cache', self.cache, create=True),
                        patch.object(redis.lock.Lock, 'lua_release', release_script)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_two_sites_get_different_lock_keys(self):
        first = locks.key('relay-channel-sync')
        frappe.local.conf.db_name = 'site_b'
        self.assertNotEqual(first, locks.key('relay-channel-sync'))

    def test_two_sites_hold_the_same_lock_name_at_once(self):
        held = locks.lock('relay-channel-sync', timeout=60, blocking_timeout=0)
        self.assertTrue(held.acquire(blocking=False))
        frappe.local.conf.db_name = 'site_b'
        self.assertTrue(locks.lock('relay-channel-sync', timeout=60).acquire(blocking=False))

    def test_clear_cache_keeps_a_held_lock(self):
        held = locks.lock('relay-bulk-send:RELAY-BULK-0000000001', timeout=60)
        self.assertTrue(held.acquire(blocking=False))
        self.cache.set(self.cache.make_key('relay-whatsapp-template-sync-requested:acct'), b'1')

        clear_site_cache(self.cache)

        self.assertEqual([locks.key('relay-bulk-send:RELAY-BULK-0000000001')], list(self.cache.store))
        self.assertFalse(locks.lock('relay-bulk-send:RELAY-BULK-0000000001', timeout=60).acquire(blocking=False))
        held.release()

    def test_without_the_persistent_key_clear_cache_drops_the_lock(self):
        held = locks.lock('relay-channel-sync', timeout=60)
        self.assertTrue(held.acquire(blocking=False))
        with patch.object(hooks, 'persistent_cache_keys', []):
            clear_site_cache(self.cache)
        with self.assertRaises(redis.exceptions.LockNotOwnedError):
            held.release()

    def test_bulk_refresh_marks_are_persistent(self):
        from relay_core.bulk_updates import DIRTY
        self.cache.set(self.cache.make_key(DIRTY), b'1')
        clear_site_cache(self.cache)
        self.assertIn(self.cache.make_key(DIRTY), self.cache.store)


def calls():
    for path in SOURCE.rglob('*.py'):
        relative = str(path.relative_to(SOURCE))
        for node in ast.walk(ast.parse(path.read_text(), relative)):
            if isinstance(node, ast.Call):
                yield relative, node


class UnscopedLockTests(unittest.TestCase):
    """Every Relay lock goes through relay_core.locks; nothing builds a lock of its own."""

    def test_no_direct_cache_or_redis_locks(self):
        direct = [f'{path}:{node.lineno}' for path, node in calls() if path != 'locks.py'
                  and isinstance(node.func, ast.Attribute) and node.func.attr == 'lock'
                  and any(name in ast.unparse(node.func.value) for name in ('cache', 'redis', 'connection'))]
        self.assertEqual([], direct)

    def test_lock_names_are_not_prefixed_twice(self):
        prefixed = [f'{path}:{node.lineno}' for path, node in calls() if ast.unparse(node.func) == 'locks.lock'
                    and any(name in ast.unparse(node.args[0]) for name in ('make_key', 'local.site', 'db_name'))]
        self.assertEqual([], prefixed)

    def test_job_ids_rely_on_frappe_site_scope(self):
        """frappe.enqueue passes job_id through create_job_id, which adds the site; a second prefix breaks dedupe lookups."""
        prefixed = [f'{path}:{node.lineno}' for path, node in calls() for keyword in node.keywords
                    if keyword.arg == 'job_id' and 'create_job_id' not in ast.unparse(keyword.value)
                    and any(name in ast.unparse(keyword.value) for name in ('local.site', 'db_name', 'make_key'))]
        self.assertEqual([], prefixed)

    def test_no_file_or_database_locks_outside_the_drain(self):
        """Bench-wide locks need the site in their name; the automation drain hashes it into its database lock."""
        found = [str(path.relative_to(SOURCE)) for path in SOURCE.rglob('*.py')
                 if any(word in path.read_text() for word in ('filelock', 'get_lock(', 'advisory_lock', 'fcntl'))]
        self.assertEqual(['automation/queue.py'], found)

    def test_every_lock_key_is_persistent(self):
        self.assertIn(locks.PREFIX + '*', hooks.persistent_cache_keys)


if __name__ == '__main__':
    unittest.main()
