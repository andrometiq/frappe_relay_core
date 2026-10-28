"""Inbox page details in a fixed number of permission-scoped queries, and live row updates."""
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from frappe import _dict
from frappe.query_builder.utils import get_query_builder
from pypika import CustomFunction
from pypika.queries import QueryBuilder, _SetOperation
from relay_core import inbox, inbox_filters, timeline
from test_contact_primary import fake_frappe

SCOPE = 'relay_scope_marker'


class DirectoryQueryTests(unittest.TestCase):
    def setUp(self):
        self.fake = fake_frappe()
        self.fake.session.user = 'agent@example.invalid'
        self.fake.conf.db_type = 'mariadb'
        self.fake.db.has_column.return_value = True
        self.fake.utils.get_datetime = lambda value: datetime.fromisoformat(value) and value
        self.qb = MagicMock(wraps=get_query_builder('mariadb'))
        self.qb.DocType = get_query_builder('mariadb').DocType
        self.qb.get_query.side_effect = self.scoped_query
        self.fake.qb = self.qb
        self.enterContext(patch.object(inbox, 'frappe', self.fake))
        self.enterContext(patch.object(timeline, 'frappe', self.fake))
        self.enterContext(patch.object(inbox_filters, 'frappe', self.fake))
        self.statements, self.rows = [], []
        def run(query, **kwargs):
            self.statements.append(query.get_sql()); return self.rows
        self.enterContext(patch.object(QueryBuilder, 'run', run, create=True))
        self.enterContext(patch.object(_SetOperation, 'run', run, create=True))

    def scoped_query(self, doctype, fields, ignore_permissions, order_by, filters=None, limit=None):
        """Stand-in for permission query conditions, marked so the SQL shows where scope applies."""
        self.assertFalse(ignore_permissions)
        table = self.qb.DocType(doctype)
        query = self.qb.from_(table).select(*fields).where(CustomFunction(SCOPE, ['doctype'])(doctype) == 1)
        for field, value in (filters or {}).items():
            if isinstance(value, list) and value[0] == 'in': query = query.where(table[field].isin(value[1]))
            elif isinstance(value, list): query = query.where(table[field].isnull() | (table[field] == ''))
            else: query = query.where(table[field] == value)
        return query.limit(limit) if limit else query

    def test_read_position_follows_exact_reads_else_the_legacy_cursor(self):
        self.assertEqual(inbox.read_position(None), '')
        self.assertEqual(inbox.read_position({'exact_reads': 0, 'last_read': 'M-5', 'read_baseline': 'M-2'}), 'M-5')
        self.assertEqual(inbox.read_position({'exact_reads': 1, 'last_read': 'M-5', 'read_baseline': 'M-2'}), 'M-2')
        self.assertEqual(inbox.read_position({'exact_reads': 1, 'last_read': 'M-5', 'read_baseline': None}), '')

    def test_page_unread_counts_seek_each_contact_from_its_position_in_one_statement(self):
        self.rows = [('C-1', 2)]
        self.assertEqual(inbox.unread_counts({'C-1': 'M-9', 'C-2': ''}, channels=['WA-1']), {'C-1': 2})
        [sql] = self.statements
        self.assertEqual(sql.count('UNION ALL'), 1)
        self.assertIn("`relay_contact`='C-1' AND `tabRelay Message`.`name`>'M-9'", sql)
        self.assertIn("`relay_contact`='C-2' AND `tabRelay Message`.`name`>''", sql)
        self.assertEqual(sql.count(SCOPE + "('Relay Message')"), 2, 'Every part keeps the message permission scope')
        self.assertIn("`tabRelay Message Read`.`user`='agent@example.invalid'", sql)
        self.assertIn("IN ('WA-1')", sql)
        self.assertEqual(inbox.unread_counts({}), {})
        self.assertEqual(inbox.unread_counts({'C-1': ''}, channels=[]), {}, 'A medium without channels has nothing unread')
        self.assertEqual(len(self.statements), 1)

    def test_latest_messages_read_one_newest_message_per_contact_in_one_statement(self):
        self.rows = [_dict(relay_contact='C-1', name='M-9', channel='WA-1')]
        self.assertEqual(inbox.latest_messages(['C-1', 'C-2']), {'C-1': self.rows[0]})
        [sql] = self.statements
        self.assertEqual(sql.count('UNION ALL'), 1)
        self.assertEqual(sql.count('LIMIT 1'), 2)
        self.assertEqual(sql.count(SCOPE + "('Relay Message')"), 2)
        self.assertEqual(inbox.latest_messages(['C-1'], channels=[]), {})

    def test_page_items_use_set_lookups_and_drop_previews_from_unreadable_channels(self):
        rows = [_dict(name='C-1', contact='P-1', display_name='One', last_message_at='2026-10-27 10:00:00', creation='2026-10-01'),
                _dict(name='C-2', contact='P-2', display_name='Two', last_message_at='2026-10-27 09:00:00', creation='2026-10-01')]
        self.fake.get_list.return_value = [('WA-1', 'WhatsApp')]
        states = [_dict(relay_contact='C-1', starred=1, folder='Follow up', exact_reads=1, last_read='', read_baseline='M-3')]
        assignments = [_dict(relay_contact='C-2', team='Sales', assigned_to=None, assigned_by=None)]
        self.fake.get_all.side_effect = lambda doctype, **kwargs: states if doctype == 'Relay Conversation State' else assignments
        latest = {'C-1': _dict(name='M-9', channel='WA-1', content='Hello', business_doctype='Customer', business_name='CU-1'),
                  'C-2': _dict(name='M-8', channel='Hidden', content='Secret')}
        with patch('relay_core.api.business_types', return_value=['Customer']), \
                patch('relay_core.contacts.linked_contacts', return_value={'C-1'}), \
                patch.object(inbox, 'latest_messages', return_value=latest), \
                patch.object(inbox, 'unread_counts', return_value={'C-1': 4}) as unread:
            items = inbox.directory_items(rows)
        unread.assert_called_once_with({'C-1': 'M-3', 'C-2': ''}, None)
        first, second = items
        self.assertFalse(first['unlinked'])
        self.assertTrue(second['unlinked'])
        self.assertEqual((first['provider'], first['latest_preview'], first['unread'], first['starred'], first['folder']),
                         ('WhatsApp', 'Hello', 4, 1, 'Follow up'))
        self.assertEqual(first['business'], {'doctype': 'Customer', 'name': 'CU-1'})
        self.assertEqual(first['assignment'], {})
        self.assertEqual((second['provider'], second['latest_preview'], second['unread']), (None, '', 0))
        self.assertEqual(second['assignment'], {'team': 'Sales', 'assigned_to': None, 'assigned_by': None})
        self.assertEqual(self.fake.get_all.call_count, 2)
        self.assertEqual(inbox.directory_items([]), [])

    def test_live_update_filter_rejects_mixed_cursors_and_bad_times(self):
        with patch.object(inbox, 'require_access'):
            with self.assertRaises(ValueError): inbox.directory(since='2026-10-27 10:00:00', after='RELAY-CON-0000000001')
            with self.assertRaises(ValueError): inbox.directory(since='not a time')
            with self.assertRaises(ValueError): inbox.directory(since='2026-10-27 10:00:00' * 3)
        self.assertEqual(self.statements, [])

    def test_live_update_returns_only_conversations_active_since_the_time(self):
        with patch.object(inbox, 'require_access'), patch.object(inbox, 'directory_items', return_value=[]):
            inbox.directory(since='2026-10-27 10:00:00')
        self.assertIn("COALESCE(`last_message_at`,`creation`)>='2026-10-27 10:00:00'", self.statements[0])

    def test_number_filter_narrows_the_medium_to_one_channel(self):
        self.fake.get_list.side_effect = lambda doctype, filters, **kwargs: ['WA-1', 'WA-2'] if filters == {'channel': 'WhatsApp'} else []
        with patch.object(inbox, 'require_access'), patch.object(inbox, 'directory_items', return_value=[]) as items:
            inbox.directory(medium='WhatsApp', channel='WA-2')
            for medium, channel in (('WhatsApp', 'WA-9'), ('Telegram', 'WA-2'), (None, 'WA-2')):
                with self.subTest(medium=medium, channel=channel), self.assertRaises(ValueError):
                    inbox.directory(medium=medium, channel=channel)
        self.assertIn("`channel` IN ('WA-2')", self.statements[0])
        self.assertEqual(items.call_args.args[1], ['WA-2'])
        self.assertEqual(len(self.statements), 1)

    def test_several_channels_narrow_the_list_and_unread_tab(self):
        self.fake.get_list.side_effect = lambda doctype, filters, **kwargs: ['WA-1', 'WA-2', 'WA-3'] if filters == {'channel': 'WhatsApp'} else ['TG-1']
        with patch.object(inbox, 'require_access'), patch.object(inbox, 'directory_items', return_value=[]) as items:
            inbox.directory(medium='WhatsApp', channels='["WA-3", "WA-1"]', mode='unread')
            inbox.directory(channels=['TG-1'])
            for channels in ('["WA-1"', '{"a": 1}', '["bad\\nname"]', '[' + ','.join(['"WA-1"'] * 51) + ']'):
                with self.subTest(channels=channels), self.assertRaises(ValueError):
                    inbox.directory(medium='WhatsApp', channels=channels)
        self.assertEqual(items.call_args_list[0].args[1], ['WA-1', 'WA-3'])
        self.assertEqual(self.statements[0].count("IN ('WA-1','WA-3')"), 2, 'Contacts and unread messages use the same channels')
        self.assertIn("IN ('TG-1')", self.statements[1])

    def test_read_tab_lists_conversations_without_unread_messages(self):
        with patch.object(inbox, 'require_access'), patch.object(inbox, 'directory_items', return_value=[]):
            inbox.directory(mode='read')
            inbox.directory(mode='unread')
            for mode in ('mine', 'unassigned'):
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    inbox.directory(mode=mode)
        read, unread = self.statements
        self.assertIn('`name` NOT IN (SELECT `tabRelay Message`.`relay_contact`', read)
        self.assertIn('`name` IN (SELECT `tabRelay Message`.`relay_contact`', unread)
        self.assertIn("`tabRelay Message Read`.`user`='agent@example.invalid'", read, 'Read means read by the session user')
        self.assertNotIn('Relay Conversation Assignment', read + unread)

    def test_business_filter_keeps_chats_of_one_type_record_or_none(self):
        self.fake.get_all.return_value = ['Customer', 'Supplier']
        with patch.object(inbox, 'require_access'), patch.object(inbox, 'directory_items', return_value=[]), \
                patch('relay_core.api.business_types', return_value=['Customer', 'Supplier']):
            inbox.directory(business_type='Customer')
            inbox.directory(business_type='Customer', business_name='CUST-1', mode='read')
            inbox.directory(business_type='none')
            for values in ({'business_type': 'Employee'}, {'business_name': 'CUST-1'}, {'business_type': 'none', 'business_name': 'CUST-1'},
                           {'business_type': 'Customer', 'business_name': 'x' * 141}):
                with self.subTest(values=values), self.assertRaises(ValueError):
                    inbox.directory(**values)
        one_type, one_record, none = self.statements
        self.assertIn("`contact` IN (SELECT `parent` FROM `tabDynamic Link` WHERE `parenttype`='Contact' AND NOT `parent` IS NULL AND `link_doctype`='Customer')", one_type)
        self.assertIn("`link_doctype`='Customer' AND `link_name`='CUST-1'", one_record)
        self.assertIn("(`contact` IS NULL OR `contact` NOT IN (SELECT `parent` FROM `tabDynamic Link` WHERE `parenttype`='Contact' AND NOT `parent` IS NULL AND `link_doctype` IN ('Customer','Supplier')))", none)

    def test_a_medium_passes_every_one_of_its_channels_to_the_rows(self):
        names = [f'WA-{i}' for i in range(150)]
        self.fake.get_list.side_effect = lambda doctype, filters, limit_page_length, **kwargs: names[:limit_page_length or None]
        with patch.object(inbox, 'require_access'), patch.object(inbox, 'directory_items', return_value=[]) as items:
            inbox.directory(medium='WhatsApp', mode='unread')
        self.assertEqual(items.call_args.args[1], names, 'Row unread counts and previews must cover the same channels as the queue')


if __name__ == '__main__':
    unittest.main()
