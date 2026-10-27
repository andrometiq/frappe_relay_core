"""Inbox queue counts: permission scope, per-user cache and the deny case."""
import unittest
from unittest.mock import MagicMock, patch

from frappe.query_builder.utils import get_query_builder
from pypika import CustomFunction
from relay_core import inbox, inbox_filters, queue_counts
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
        self.enterContext(patch.object(inbox_filters, 'frappe', self.fake))
        self.access = self.enterContext(patch.object(queue_counts, 'require_access'))
        self.sql = []
        self.enterContext(patch.object(queue_counts, 'count', side_effect=lambda query: self.sql.append(query.get_sql()) or len(self.sql)))
        self.unread_sql = []
        def run(query, **kwargs):
            self.unread_sql.append(query.get_sql()); return [(4, 5)]
        from pypika.queries import QueryBuilder
        self.enterContext(patch.object(QueryBuilder, 'run', run, create=True))

    def scoped_query(self, doctype, fields, ignore_permissions, order_by, filters=None):
        """Stand-in for permission query conditions, marked so the SQL shows where scope applies."""
        self.assertFalse(ignore_permissions)
        table = self.qb.DocType(doctype)
        return self.qb.from_(table).select(*fields).where(CustomFunction(SCOPE, ['doctype'])(doctype) == 1)

    def test_every_count_uses_the_permission_scope_and_the_session_user(self):
        result = queue_counts.get_counts()

        self.assertEqual(result, {'all': 1, 'unread': 4, 'read': -3, 'unread_messages': 5})
        for sql in self.sql + self.unread_sql:
            self.assertIn(SCOPE + "('Relay Contact')", sql)
            self.assertNotIn('Relay Conversation Assignment', sql, 'Chat assignment does not decide any tab')
        [unread] = self.unread_sql
        self.assertIn(SCOPE + "('Relay Message')", unread, 'Unread counts keep the message scope too')
        self.assertIn("`user`='agent@example.invalid'", unread)
        self.assertIn('COUNT(DISTINCT', unread, 'One pass counts conversations and messages')

    def test_read_is_every_listed_conversation_without_unread_messages(self):
        self.enterContext(patch.object(queue_counts, 'count', return_value=10))
        self.assertEqual(queue_counts.get_counts(), {'all': 10, 'unread': 4, 'read': 6, 'unread_messages': 5})

    def test_channels_limit_contacts_and_unread_messages(self):
        queue_counts.get_counts(['TG-1'])

        for sql in self.sql + self.unread_sql:
            self.assertIn("IN ('TG-1')", sql)

    def test_no_channels_count_nothing_without_queries(self):
        self.assertEqual(queue_counts.get_counts([]), dict.fromkeys(('all', 'unread', 'read', 'unread_messages'), 0))
        self.assertEqual(self.sql + self.unread_sql, [])

    def test_a_business_record_limits_the_list_and_the_unread_counts(self):
        with patch('relay_core.api.business_types', return_value=['Customer', 'Supplier']):
            business = inbox_filters.business_filter('Customer', 'CUST-1')
        queue_counts.get_counts(['WA-1'], business)

        for sql in self.sql + self.unread_sql:
            self.assertIn("`link_doctype`='Customer' AND `link_name`='CUST-1'", sql)

    def test_read_denies_users_without_relay_access_and_bad_filters(self):
        self.access.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            queue_counts.read()
        self.access.side_effect = None
        for values in ({'medium': 'SMS'}, {'channels': 'not json'}, {'business_name': 'CUST-1'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                queue_counts.read(**values)
        self.assertEqual(self.sql, [])

    def test_read_counts_the_chosen_channels_of_a_medium(self):
        self.fake.get_list.side_effect = lambda doctype, filters, **kwargs: ['WA-1', 'WA-2'] if filters == {'channel': 'WhatsApp'} else []
        self.fake.cache.get_value.return_value = None
        with patch.object(queue_counts, 'get_counts', return_value={}) as compute:
            for medium, channels in (('Telegram', '["WA-1"]'), ('WhatsApp', '["WA-9"]'), (None, '["WA-1"]')):
                with self.subTest(medium=medium, channels=channels), self.assertRaises(ValueError):
                    queue_counts.read(medium, channels=channels)
            queue_counts.read('WhatsApp', channels='["WA-2"]')
            queue_counts.read('WhatsApp', 'WA-1')
        self.assertEqual([call.args for call in compute.call_args_list], [(['WA-2'], None), (['WA-1'], None)])

    def test_cache_is_per_user_and_dropped_by_a_new_generation(self):
        store = {}
        self.fake.cache.get_value.side_effect = store.get
        self.fake.cache.set_value.side_effect = lambda key, value, **kwargs: store.__setitem__(key, value)
        with patch.object(queue_counts, 'get_counts', side_effect=lambda *args, **kwargs: {'user': self.fake.session.user}) as compute:
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
