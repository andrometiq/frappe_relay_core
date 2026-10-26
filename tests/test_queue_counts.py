"""Inbox queue counts: permission scope, per-user cache and the deny case."""
import unittest
from unittest.mock import MagicMock, patch

from frappe.query_builder.utils import get_query_builder
from pypika import CustomFunction
from relay_core import inbox, queue_counts
from test_contact_primary import fake_frappe

SCOPE = 'relay_scope_marker'


class QueueCountTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_frappe()
        self.fake.session.user = 'agent@example.invalid'
        self.qb = MagicMock(wraps=get_query_builder('mariadb'))
        self.qb.DocType = get_query_builder('mariadb').DocType
        self.qb.get_query.side_effect = self.scoped_query
        self.fake.qb = self.qb
        self.enterContext(patch.object(queue_counts, 'frappe', self.fake))
        self.enterContext(patch.object(inbox, 'frappe', self.fake))
        self.access = self.enterContext(patch.object(queue_counts, 'require_access'))
        self.sql = []
        self.enterContext(patch.object(queue_counts, 'count', side_effect=lambda query: self.sql.append(query.get_sql()) or len(self.sql)))

    def scoped_query(self, doctype, fields, ignore_permissions, order_by, filters=None):
        """Stand-in for permission query conditions, marked so the SQL shows where scope applies."""
        self.assertFalse(ignore_permissions)
        table = self.qb.DocType(doctype)
        return self.qb.from_(table).select(*fields).where(CustomFunction(SCOPE, ['doctype'])(doctype) == 1)

    def test_every_count_uses_the_permission_scope_and_the_session_user(self):
        result = queue_counts.get_counts()

        self.assertEqual(result, {'all': 1, 'mine': 2, 'unassigned': 3, 'unread': 4, 'unread_messages': 5})
        for sql in self.sql:
            self.assertIn(SCOPE + "('Relay Contact')", sql)
        self.assertIn("`assigned_to`='agent@example.invalid'", self.sql[1])
        self.assertIn('NOT IN', self.sql[2])
        for sql in self.sql[3:]:
            self.assertIn(SCOPE + "('Relay Message')", sql, 'Unread counts keep the message scope too')
            self.assertIn("`user`='agent@example.invalid'", sql)

    def test_medium_limits_contacts_and_unread_messages_to_its_channels(self):
        queue_counts.get_counts('Telegram')

        for sql in self.sql:
            self.assertIn("`channel`='Telegram'", sql)

    def test_read_denies_users_without_relay_access_and_bad_mediums(self):
        self.access.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            queue_counts.read()
        self.access.side_effect = None
        with self.assertRaises(ValueError):
            queue_counts.read('SMS')
        self.assertEqual(self.sql, [])

    def test_cache_is_per_user_and_dropped_by_a_new_generation(self):
        store = {}
        self.fake.cache.get_value.side_effect = store.get
        self.fake.cache.set_value.side_effect = lambda key, value, **kwargs: store.__setitem__(key, value)
        with patch.object(queue_counts, 'get_counts', side_effect=lambda medium: {'user': self.fake.session.user}) as compute:
            self.assertEqual(queue_counts.read(), {'user': 'agent@example.invalid'})
            queue_counts.read()
            self.assertEqual(compute.call_count, 1)
            self.fake.session.user = 'other@example.invalid'
            self.assertEqual(queue_counts.read(), {'user': 'other@example.invalid'})
            self.assertEqual(compute.call_count, 2)
            store[queue_counts.GENERATION_KEY] = 'next'
            queue_counts.read()
            self.assertEqual(compute.call_count, 3)

    def test_invalidate_waits_for_the_commit(self):
        queue_counts.invalidate()
        self.fake.cache.set_value.assert_not_called()
        callback = self.fake.db.after_commit.add.call_args.args[0]
        callback()
        self.assertEqual(self.fake.cache.set_value.call_args.args[0], queue_counts.GENERATION_KEY)


if __name__ == '__main__':
    unittest.main()
