"""Inbox queue counts: permission scope, per-user cache and the deny case."""
import unittest
from unittest.mock import MagicMock, patch

from frappe.query_builder.utils import get_query_builder
from pypika import CustomFunction
from relay_core import features, inbox, queue_counts
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
        self.teams_on = self.enterContext(patch.object(features, 'is_enabled', return_value=True))
        self.sql = []
        self.enterContext(patch.object(queue_counts, 'count', side_effect=lambda query: self.sql.append(query.get_sql()) or len(self.sql)))
        self.unread_sql = []
        def run(query, **kwargs):
            self.unread_sql.append(query.get_sql()); return [(4, 5)]
        from pypika.queries import QueryBuilder
        self.enterContext(patch.object(QueryBuilder, 'run', run, create=True))
        self.fake.get_all.side_effect = lambda doctype, filters, **kwargs: ['TG-1'] if filters == {'channel': 'Telegram'} else []

    def scoped_query(self, doctype, fields, ignore_permissions, order_by, filters=None):
        """Stand-in for permission query conditions, marked so the SQL shows where scope applies."""
        self.assertFalse(ignore_permissions)
        table = self.qb.DocType(doctype)
        return self.qb.from_(table).select(*fields).where(CustomFunction(SCOPE, ['doctype'])(doctype) == 1)

    def test_every_count_uses_the_permission_scope_and_the_session_user(self):
        result = queue_counts.get_counts()

        self.assertEqual(result, {'all': 1, 'mine': 2, 'unassigned': 3, 'unread': 4, 'unread_messages': 5})
        for sql in self.sql + self.unread_sql:
            self.assertIn(SCOPE + "('Relay Contact')", sql)
        self.assertIn("`assigned_to`='agent@example.invalid'", self.sql[1])
        self.assertIn('NOT IN', self.sql[2])
        [unread] = self.unread_sql
        self.assertIn(SCOPE + "('Relay Message')", unread, 'Unread counts keep the message scope too')
        self.assertIn("`user`='agent@example.invalid'", unread)
        self.assertIn('COUNT(DISTINCT', unread, 'One pass counts conversations and messages')

    def test_unassigned_counts_team_only_chats_while_teams_are_off(self):
        queue_counts.get_counts()
        self.assertIn('`team`', self.sql[2])
        self.sql.clear(); self.unread_sql.clear()
        self.teams_on.return_value = False
        queue_counts.get_counts()
        self.assertIn('`assigned_to`', self.sql[2])
        self.assertNotIn('`team`', self.sql[2], 'A chat with only a team and no agent is unassigned')
        self.teams_on.assert_called_with('teams')

    def test_medium_limits_contacts_and_unread_messages_to_its_channels(self):
        queue_counts.get_counts('Telegram')

        for sql in self.sql + self.unread_sql:
            self.assertIn("IN ('TG-1')", sql)

    def test_medium_without_channels_counts_nothing_without_queries(self):
        self.assertEqual(queue_counts.get_counts('Email'), dict.fromkeys(('all', 'mine', 'unassigned', 'unread', 'unread_messages'), 0))
        self.assertEqual(self.sql + self.unread_sql, [])

    def test_read_denies_users_without_relay_access_and_bad_mediums(self):
        self.access.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            queue_counts.read()
        self.access.side_effect = None
        with self.assertRaises(ValueError):
            queue_counts.read('SMS')
        self.assertEqual(self.sql, [])

    def test_one_number_limits_every_count_to_that_channel(self):
        queue_counts.get_counts('WhatsApp', ['WA-2'])

        for sql in self.sql + self.unread_sql:
            self.assertIn("IN ('WA-2')", sql)

    def test_read_rejects_a_number_of_another_medium(self):
        self.fake.get_all.side_effect = lambda doctype, filters, **kwargs: ['WA-1'] if filters == {'channel': 'WhatsApp'} else []
        self.fake.cache.get_value.return_value = None
        with patch.object(queue_counts, 'get_counts', return_value={}) as compute:
            for medium, channel in ((None, 'WA-1'), ('Telegram', 'WA-1'), ('WhatsApp', 'WA-9')):
                with self.subTest(medium=medium, channel=channel), self.assertRaises(ValueError):
                    queue_counts.read(medium, channel)
            queue_counts.read('WhatsApp', 'WA-1')
        compute.assert_called_once_with('WhatsApp', ['WA-1'])

    def test_number_counts_scope_each_number_and_all_numbers(self):
        self.fake.cache.get_value.return_value = None
        numbers = [{'name': 'WA-1', 'label': 'Sales', 'address': '+91 1'}, {'name': 'WA-2', 'label': 'Support', 'address': '+91 2'}]
        with patch('relay_core.hub_channels.site_numbers', return_value=numbers):
            result = queue_counts.numbers()
        self.assertEqual(result, {'all': 1, 'numbers': {'WA-1': 2, 'WA-2': 3}})
        self.assertIn("IN ('WA-1','WA-2')", self.sql[0])
        self.assertIn("IN ('WA-1')", self.sql[1])
        for sql in self.sql:
            self.assertIn(SCOPE + "('Relay Contact')", sql)

    def test_number_counts_deny_users_without_relay_access(self):
        self.access.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            queue_counts.numbers()

    def test_cache_is_per_user_and_dropped_by_a_new_generation(self):
        store = {}
        self.fake.cache.get_value.side_effect = store.get
        self.fake.cache.set_value.side_effect = lambda key, value, **kwargs: store.__setitem__(key, value)
        with patch.object(queue_counts, 'get_counts', side_effect=lambda *args: {'user': self.fake.session.user}) as compute:
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
